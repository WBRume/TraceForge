import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, literal, or_, tuple_
from sqlalchemy.orm import Session, aliased

from app.domains.asset.models.asset import DOCUMENT_ASSET_TYPES, SddAsset
from app.domains.case_center.models.case import SddCase
from app.domains.diagnosis_playbook.models import CasePlaybookLink, PlaybookSpec, TaskPlaybookBinding
from app.domains.task.models.task import SddTask, TaskStatus, TaskType
from app.domains.workspace_asset.models.requirement_document import (
    SddRequirementDocument,
    SddRequirementDocumentLink,
)
from app.domains.workspace_asset.models.workspace_asset import SddRequirement, SddTaskRequirement
from app.domains.workspace_canvas import relations, sources, tree_children, tree_preview
from app.domains.workspace_canvas.quarter_calendar import FiscalCalendar
from app.domains.workspace_canvas.schemas import CanvasRootQuery, CanvasRootWindow

# Priority only reorders a bounded window of IDs. Its cursor exhausts both
# ranks before scanning another window, including quarters with sparse roots.
SCAN_LIMIT = 256
TYPE_PAGE = 8
OVERVIEW_LIMITS = {
    "requirement": 2,
    "task": 2,
    "case": 1,
    "playbook": 1,
    "requirement_document": 1,
    "document": 1,
}


def _cursor(value):
    if value is None:
        return {}
    try:
        data = json.loads(value)
        if not isinstance(data, dict) or data.keys() - OVERVIEW_LIMITS.keys():
            raise ValueError
        for position in data.values():
            if position is None:
                continue
            after, seen = position
            if after is not None:
                _date_key(after)
            if seen is not None:
                rank, *key = seen
                if rank not in (0, 1):
                    raise ValueError
                _date_key(key)
        return data
    except (TypeError, ValueError, AttributeError) as error:
        raise HTTPException(422, "CANVAS_INVALID_CURSOR") from error


def _date_key(key):
    timestamp, identifier = key
    instant = datetime.fromisoformat(timestamp)
    if instant.tzinfo is not None or not isinstance(identifier, str) or not 0 < len(identifier) <= 36:
        raise ValueError
    return instant, identifier


def _markers(db, workspace_id, kinds, dates, kind):
    req, task, case = SddRequirement, SddTask, SddCase
    task_link, doc_link = SddTaskRequirement, SddRequirementDocumentLink
    start, end = dates.utc_bounds

    def in_quarter(model):
        return (model.workspace_id == workspace_id) & (model.created_at >= start) & (model.created_at < end)

    def root_if_absent(query, owner_kind):
        return ~query.exists() if owner_kind in kinds else literal(True)

    if kind == "requirement":
        relative = aliased(req)
        parent = db.query(relative.id).filter(relative.id == req.parent_requirement_id, in_quarter(relative))
        child = db.query(relative.id).filter(
            relative.workspace_id == workspace_id, relative.parent_requirement_id == req.id
        )
        successor = db.query(relative.id).filter(
            relative.workspace_id == workspace_id, relative.predecessor_id == req.id
        )
        linked = [
            req.parent_requirement_id.is_not(None),
            req.predecessor_id.is_not(None),
            child.exists(),
            successor.exists(),
        ]
        if "task" in kinds:
            linked.append(
                db.query(task_link.id)
                .filter(task_link.requirement_id == req.id, task_link.workspace_id == workspace_id)
                .exists()
            )
        if "document" in kinds or "requirement_document" in kinds:
            linked.append(db.query(doc_link.id).filter(doc_link.requirement_id == req.id).exists())
        return ~parent.exists(), or_(*linked)
    if kind == "task":
        requirements = db.query(task_link.id).filter(
            task_link.workspace_id == workspace_id, task_link.task_id == task.id
        )
        local = requirements.join(req, req.id == task_link.requirement_id).filter(in_quarter(req))
        linked = [requirements.exists()] if "requirement" in kinds else [literal(False)]
        if "document" in kinds:
            linked.append(
                db.query(SddAsset.id)
                .filter(
                    SddAsset.workspace_id == workspace_id,
                    SddAsset.task_id == task.id,
                    SddAsset.asset_type.in_(DOCUMENT_ASSET_TYPES),
                )
                .exists()
            )
        if "case" in kinds:
            linked.append(
                db.query(case.id).filter(case.workspace_id == workspace_id, case.source_task_id == task.id).exists()
            )
        if "playbook" in kinds:
            linked.append(
                (task.task_type == TaskType.DIAGNOSIS)
                & or_(
                    task.task_meta_json["diagnosis_playbook_guide"]["spec_id"].as_string().is_not(None),
                    db.query(TaskPlaybookBinding.task_id)
                    .filter(TaskPlaybookBinding.task_id == task.id, TaskPlaybookBinding.active_run_id.is_not(None))
                    .exists(),
                )
            )
        return root_if_absent(local, "requirement"), or_(*linked)
    if kind == "case":
        owner = db.query(task.id).filter(
            task.id == case.source_task_id, task.task_type == TaskType.DIAGNOSIS, in_quarter(task)
        )
        links = [case.source_task_id.is_not(None)] if "task" in kinds else [literal(False)]
        if "playbook" in kinds:
            links.append(db.query(CasePlaybookLink.case_id).filter(CasePlaybookLink.case_id == case.id).exists())
        return root_if_absent(owner, "task"), or_(*links)
    if kind == "playbook":
        links = db.query(CasePlaybookLink.case_id).filter(CasePlaybookLink.spec_id == PlaybookSpec.id)
        local = links.join(case, case.id == CasePlaybookLink.case_id).filter(in_quarter(case))
        return root_if_absent(local, "case"), links.exists() if "case" in kinds else literal(False)
    if kind == "requirement_document":
        attached = db.query(doc_link.id).filter(doc_link.document_id == SddRequirementDocument.id)
        local = attached.join(req, req.id == doc_link.requirement_id).filter(in_quarter(req))
        return root_if_absent(local, "requirement"), attached.exists() if "requirement" in kinds else literal(False)
    attached = db.query(doc_link.id).filter(doc_link.task_asset_id == SddAsset.id)
    local_req = attached.join(req, req.id == doc_link.requirement_id).filter(in_quarter(req))
    local_task = db.query(task.id).filter(task.id == SddAsset.task_id, in_quarter(task))
    return root_if_absent(local_req, "requirement") & root_if_absent(local_task, "task"), literal(True)


def _type_page(db, workspace_id, kinds, base, dates, kind, model, limit, position):
    after, seen = position
    key = tuple_(model.created_at, model.id)
    if after is not None:
        base = base.filter(key < _date_key(after))
    raw = (
        base.with_entities(model.id, model.created_at)
        .order_by(model.created_at.desc(), model.id.desc())
        .limit(SCAN_LIMIT + 1)
        .all()
    )
    if not raw:
        return [], None

    eligible, connected = _markers(db, workspace_id, kinds, dates, kind)
    rows = (
        db.query(model.id, model.created_at, connected)
        .filter(model.workspace_id == workspace_id, model.id.in_([row.id for row in raw[:SCAN_LIMIT]]), eligible)
        .all()
    )
    ranked = sorted(((int(related), created, identifier) for identifier, created, related in rows), reverse=True)
    if seen is not None:
        ranked = [row for row in ranked if row < (seen[0], *_date_key(seen[1:]))]
    page = ranked[:limit]
    if len(ranked) > limit:
        rank, created, identifier = page[-1]
        following = [after, [rank, created.isoformat(), identifier]]
    elif len(raw) > SCAN_LIMIT:
        last = raw[SCAN_LIMIT - 1]
        following = [[last.created_at.isoformat(), last.id], None]
    else:
        following = None
    return [(sources.reference_for(kind, identifier), bool(rank)) for rank, _, identifier in page], following


def read_roots(db: Session, workspace_id, kinds, calendar: FiscalCalendar, params: CanvasRootQuery) -> CanvasRootWindow:
    quarter = calendar.period(params.quarter)
    quarter_dates = calendar.dates(quarter)
    try:
        start, end = calendar.slice(quarter, params.slice).utc_bounds
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    cursors = _cursor(params.cursor)
    refs = []
    following = {}
    for kind, model, title, base in sources.catalog_queries(db, workspace_id, kinds):
        if kind not in OVERVIEW_LIMITS or (params.kind and kind != params.kind):
            continue
        position = cursors.get(kind, [None, None])
        following[kind] = None
        if position is None:
            continue
        base = base.filter(model.created_at >= start, model.created_at < end)
        if params.q:
            base = base.filter(func.lower(title).startswith(params.q.strip().lower(), autoescape=True))
        if kind == "task":
            if params.task_type:
                base = base.filter(SddTask.task_type == params.task_type)
            if params.status:
                try:
                    base = base.filter(SddTask.status == TaskStatus(params.status))
                except ValueError as error:
                    raise HTTPException(422, "CANVAS_INVALID_TASK_STATUS") from error
            if params.creator_id:
                base = base.filter(SddTask.creator_id == params.creator_id)
        page, following[kind] = _type_page(
            db,
            workspace_id,
            kinds,
            base,
            quarter_dates,
            kind,
            model,
            TYPE_PAGE if params.kind else OVERVIEW_LIMITS[kind],
            position,
        )
        refs.extend(page)

    loaded = sources.assets_for_references(db, workspace_id, [ref for ref, _ in refs])
    by_id = {asset.node_id: asset for asset in sources.assign_quarters(loaded, calendar)}
    assets = []
    for ref, related in refs:
        asset = by_id.get(sources.catalog_node_id(ref))
        if asset is not None:
            asset.has_related = related
            assets.append(asset)
    root_ids = [asset.node_id for asset in assets]
    children = {}
    if params.preview and assets:
        assets, children = tree_preview.read_preview(db, workspace_id, kinds, calendar, quarter_dates, assets)
    known = sources.visible_references(params.visible, kinds)
    tree_children.mark_children(db, workspace_id, kinds, quarter_dates, assets, known=known)
    shown = sources.assets_for_references(db, workspace_id, known) if assets and known else []
    return CanvasRootWindow(
        assets=assets,
        relations=relations.load_relations(
            db, workspace_id, [*assets, *shown], 384 if params.preview else 128, focus=assets
        )
        if assets
        else [],
        next_cursor=json.dumps(following, separators=(",", ":")) if any(following.values()) else None,
        root_ids=root_ids,
        preview_children=children,
    )
