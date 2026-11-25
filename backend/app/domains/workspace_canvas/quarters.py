from collections.abc import Collection
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, or_, tuple_
from sqlalchemy.orm import Session

from app.domains.asset.models.asset import DOCUMENT_ASSET_TYPES, SddAsset
from app.domains.auth.models.user import Workspace
from app.domains.case_center.models.case import SddCase
from app.domains.diagnosis_playbook.models import CasePlaybookLink
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace_asset.models.requirement_document import SddRequirementDocumentLink
from app.domains.workspace_asset.models.workspace_asset import (
    SddRequirement,
    SddTaskRequirement,
    TaskRequirementRelationType,
)
from app.domains.workspace_canvas import relations, root_tree, sources
from app.domains.workspace_canvas.quarter_calendar import (
    CanvasCalendarSettings,
    DateRange,
    FiscalCalendar,
    FiscalQuarter,
)
from app.domains.workspace_canvas.schemas import (
    CanvasBranch,
    CanvasBranchQuery,
    CanvasBranchWindow,
    CanvasRootQuery,
    SourceId,
    SourceKind,
    SourceReference,
)

REQUIREMENT_LIMIT = 20
TASK_PAGE_LIMIT = 20
STATS_LIMIT = 1024
SCAN_LIMIT = 96
EXTRA_ASSET_LIMIT = 26
RELATION_LIMIT = 128
OVERVIEW_DETAIL_LIMIT = 12
TASK_RELATIONS = ("COVERS", "RELATES_TO")
KNOWLEDGE_KINDS = ("requirement_document", "document", "case", "playbook")


def get_calendar(db: Session, workspace_id: str) -> FiscalCalendar:
    raw = db.query(Workspace.canvas_calendar).filter(Workspace.id == workspace_id).scalar()
    return FiscalCalendar(CanvasCalendarSettings.model_validate(raw or {}))


def in_range(query, column, dates: DateRange):
    start, end = dates.utc_bounds
    return query.filter(column >= start, column < end)


def _probe_count(query) -> tuple[int, bool]:
    amount = query.limit(STATS_LIMIT + 1).count()
    return min(amount, STATS_LIMIT), amount <= STATS_LIMIT


def _date_cursor(row, kind: str) -> str:
    return f"{kind}:{row.created_at.isoformat()}:{row.id}"


def _unpack_cursor(cursor: str) -> tuple[str, datetime, str]:
    kind, _, rest = cursor.partition(":")
    value, _, identifier = rest.rpartition(":")
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is not None or len(identifier) > 36 or not identifier:
            raise ValueError
    except ValueError as error:
        raise HTTPException(422, "CANVAS_INVALID_CURSOR") from error
    return kind, instant, identifier


def _date_page(query, model, kind: str, cursor: str | None, limit: int):
    if cursor:
        cursor_kind, instant, identifier = _unpack_cursor(cursor)
        if cursor_kind != kind:
            raise HTTPException(422, "CANVAS_INVALID_CURSOR")
        query = query.filter(tuple_(model.created_at, model.id) > (instant, identifier))
    return query.with_entities(model.id, model.created_at).order_by(model.created_at, model.id).limit(limit).all()


def _bundle(kind, identifier, count, exact=True, **details):
    return CanvasBranch(id=identifier, kind=kind, count=count, exact=exact, **details)


def _requirement_ids(db: Session, workspace_id: str, dates: DateRange):
    req = SddRequirement
    return in_range(db.query(req.id).filter(req.workspace_id == workspace_id), req.created_at, dates)


def _task_links(db: Session, workspace_id: str, requirement_id: SourceId, relation_type: str):
    link = SddTaskRequirement
    return db.query(link.task_id).filter(
        link.workspace_id == workspace_id,
        link.requirement_id == requirement_id,
        link.relation_type == TaskRequirementRelationType(relation_type),
    )


def _requirement_content(db: Session, workspace_id: str, kinds, requirement_ids: list[str], *, inline: bool):
    refs = [sources.reference_for("requirement", identifier) for identifier in requirement_ids]
    groups: list[CanvasBranch] = []
    if not requirement_ids:
        return refs, groups
    req = SddRequirement
    for parent, predecessor in db.query(req.parent_requirement_id, req.predecessor_id).filter(
        req.workspace_id == workspace_id, req.id.in_(requirement_ids)
    ):
        refs.extend(
            sources.reference_for("requirement", identifier) for identifier in (parent, predecessor) if identifier
        )
    if "task" in kinds:
        for identifier in requirement_ids:
            for relation_type in TASK_RELATIONS:
                query = _task_links(db, workspace_id, identifier, relation_type)
                count, exact = _probe_count(query)
                if not count:
                    continue
                if inline and exact and count <= 3 and len(refs) + count <= REQUIREMENT_LIMIT + 12:
                    refs.extend(
                        sources.reference_for("task", row.task_id)
                        for row in query.order_by(SddTaskRequirement.task_id).limit(3)
                    )
                else:
                    groups.append(
                        _bundle(
                            "requirement_tasks",
                            f"tasks-{identifier}-{relation_type.lower()}",
                            count,
                            exact,
                            requirement_id=identifier,
                            relation_type=relation_type,
                        )
                    )
    link = SddRequirementDocumentLink
    for document_id, asset_id, task_id in (
        db.query(link.document_id, link.task_asset_id, SddAsset.task_id)
        .outerjoin(SddAsset, SddAsset.id == link.task_asset_id)
        .filter(link.requirement_id.in_(requirement_ids))
        .order_by(link.requirement_id, link.id)
        .limit(12)
    ):
        if document_id and "requirement_document" in kinds:
            refs.append(sources.reference_for("requirement_document", document_id))
        elif asset_id and "document" in kinds:
            refs.append(sources.reference_for("document", asset_id))
            if task_id and "task" in kinds:
                refs.append(sources.reference_for("task", task_id))
    return refs, groups


def _task_markers(db: Session, workspace_id: str, task_id, dates: DateRange):
    link, req = SddTaskRequirement, SddRequirement
    links = db.query(link.id).filter(link.workspace_id == workspace_id, link.task_id == task_id)
    start, end = dates.utc_bounds
    cross = links.join(req, req.id == link.requirement_id).filter(
        req.workspace_id == workspace_id, or_(req.created_at < start, req.created_at >= end)
    )
    return links.exists(), cross.exists()


def _tasks_in_period(db: Session, workspace_id: str, dates: DateRange):
    task = SddTask
    return in_range(db.query(task.id).filter(task.workspace_id == workspace_id), task.created_at, dates)


def _task_overview(db: Session, workspace_id: str, dates: DateRange):
    task = SddTask
    limit = min(STATS_LIMIT, 24)
    scope = _tasks_in_period(db, workspace_id, dates).order_by(task.created_at, task.id).limit(limit + 1).subquery()
    attached, cross = _task_markers(db, workspace_id, scope.c.id, dates)
    rows = db.query(scope.c.id, attached, cross).all()
    cross_ids = [identifier for identifier, _, historical in rows[:limit] if historical]
    independent_ids = [identifier for identifier, linked, _ in rows[:limit] if not linked]
    return len(rows) <= limit, independent_ids, cross_ids


def _task_neighbors(db: Session, workspace_id: str, kinds, task_ids: list[str], quarter: DateRange, *, cross=False):
    if not task_ids:
        return []
    result: list[SourceReference] = []
    link, req = SddTaskRequirement, SddRequirement
    if "requirement" in kinds:
        query = db.query(link.requirement_id).filter(link.workspace_id == workspace_id, link.task_id.in_(task_ids))
        if cross:
            start, end = quarter.utc_bounds
            query = query.join(req, req.id == link.requirement_id).filter(
                req.workspace_id == workspace_id, or_(req.created_at < start, req.created_at >= end)
            )
        result.extend(
            sources.reference_for("requirement", row.requirement_id)
            for row in query.distinct().order_by(link.requirement_id).limit(20 if cross else 8)
        )
    if "document" in kinds:
        result.extend(
            sources.reference_for("document", row.id)
            for row in db.query(SddAsset.id)
            .filter(
                SddAsset.workspace_id == workspace_id,
                SddAsset.task_id.in_(task_ids),
                SddAsset.asset_type.in_(DOCUMENT_ASSET_TYPES),
            )
            .order_by(SddAsset.task_id, SddAsset.id)
            .limit(8)
        )
    if "case" in kinds:
        cases = [
            row.id
            for row in db.query(SddCase.id)
            .filter(SddCase.workspace_id == workspace_id, SddCase.source_task_id.in_(task_ids))
            .order_by(SddCase.source_task_id, SddCase.id)
            .limit(8)
        ]
        result.extend(sources.reference_for("case", identifier) for identifier in cases)
        if cases and "playbook" in kinds:
            spec = CasePlaybookLink.spec_id
            result.extend(
                sources.reference_for("playbook", row.spec_id)
                for row in db.query(spec)
                .filter(CasePlaybookLink.case_id.in_(cases), spec.is_not(None))
                .distinct()
                .order_by(spec)
                .limit(4)
            )
    return result[:EXTRA_ASSET_LIMIT]


def _knowledge_overview(db: Session, workspace_id: str, kinds, dates: DateRange) -> int:
    return sum(
        in_range(query, model.created_at, dates).limit(OVERVIEW_DETAIL_LIMIT + 1).count()
        for _, model, _, query in sources.catalog_queries(
            db, workspace_id, [kind for kind in KNOWLEDGE_KINDS if kind in kinds]
        )
    )


def _load(db, workspace_id, calendar, refs, groups=(), cursor=None, loaded=0):
    unique = list({ref.model_dump_json(): ref for ref in refs}.values())
    assets = sources.assign_quarters(sources.assets_for_references(db, workspace_id, unique), calendar)
    by_id = {asset.node_id: asset for asset in assets}
    ordered = [by_id[key] for ref in unique if (key := sources.catalog_node_id(ref)) in by_id]
    return CanvasBranchWindow(
        assets=ordered,
        relations=relations.load_relations(db, workspace_id, ordered, RELATION_LIMIT),
        branches=list(groups),
        next_cursor=cursor,
        loaded_count=loaded,
    )


def read_quarter(
    db: Session, workspace_id: str, kinds: Collection[SourceKind], calendar: FiscalCalendar, period: FiscalQuarter
) -> CanvasBranchWindow:
    dates = calendar.dates(period)

    def roots():
        page = root_tree.read_roots(db, workspace_id, kinds, calendar, CanvasRootQuery(quarter=period.id))
        return CanvasBranchWindow(**page.model_dump(), root_tree=True)

    req_ids = []
    if "requirement" in kinds:
        query = _requirement_ids(db, workspace_id, dates)
        limit = min(REQUIREMENT_LIMIT, OVERVIEW_DETAIL_LIMIT)
        rows = _date_page(query, SddRequirement, "requirement", None, limit + 1)
        if len(rows) > limit:
            return roots()
        req_ids = [row.id for row in rows]
    independent_ids, cross_ids = [], []
    if "task" in kinds:
        exact, independent_ids, cross_ids = _task_overview(db, workspace_id, dates)
        if not exact or len(independent_ids) > 4 or len(cross_ids) > 6:
            return roots()
    refs, groups = _requirement_content(db, workspace_id, kinds, req_ids, inline=True)
    if groups:
        return roots()
    refs.extend(sources.reference_for("task", identifier) for identifier in [*independent_ids, *cross_ids])
    refs.extend(_task_neighbors(db, workspace_id, kinds, independent_ids, dates))
    refs.extend(_task_neighbors(db, workspace_id, kinds, cross_ids, dates, cross=True))
    knowledge = _knowledge_overview(db, workspace_id, kinds, dates)
    if knowledge > OVERVIEW_DETAIL_LIMIT:
        return roots()
    result = _load(db, workspace_id, calendar, refs)
    shown_knowledge = sum(
        asset.reference.kind in KNOWLEDGE_KINDS and asset.quarter is not None and asset.quarter.id == period.id
        for asset in result.assets
    )
    return roots() if knowledge > shown_knowledge or len(result.assets) > OVERVIEW_DETAIL_LIMIT else result


def _task_filter(query, params: CanvasBranchQuery):
    task = SddTask
    if params.task_type:
        query = query.filter(task.task_type == params.task_type)
    if params.status:
        try:
            query = query.filter(task.status == TaskStatus(params.status))
        except ValueError as error:
            raise HTTPException(422, "CANVAS_INVALID_TASK_STATUS") from error
    if params.creator_id:
        query = query.filter(task.creator_id == params.creator_id)
    if params.q and params.q.strip():
        query = query.filter(func.lower(task.name).contains(params.q.strip().lower(), autoescape=True))
    return query


def _period_task_page(db, workspace_id, dates, quarter_dates, params):
    task = SddTask
    base = _tasks_in_period(db, workspace_id, dates)
    raw = _date_page(base, task, "task", params.cursor, SCAN_LIMIT + 1)
    if not raw:
        return [], None
    attached, cross = _task_markers(db, workspace_id, task.id, quarter_dates)
    eligible = _task_filter(
        db.query(task.id).filter(
            task.workspace_id == workspace_id,
            task.id.in_([row.id for row in raw[:SCAN_LIMIT]]),
            cross if params.kind == "cross_quarter" else ~attached,
        ),
        params,
    )
    matches = {row.id for row in eligible}
    selected = [row for row in raw[:SCAN_LIMIT] if row.id in matches]
    if len(selected) > TASK_PAGE_LIMIT:
        page = selected[:TASK_PAGE_LIMIT]
        return [row.id for row in page], _date_cursor(page[-1], "task")
    return [row.id for row in selected], _date_cursor(raw[SCAN_LIMIT - 1], "task") if len(raw) > SCAN_LIMIT else None


def _linked_task_page(db, workspace_id, dates, quarter_dates, params):
    req = SddRequirement
    anchor = in_range(
        db.query(req.id).filter(req.workspace_id == workspace_id, req.id == params.requirement_id),
        req.created_at,
        quarter_dates,
    ).first()
    if not anchor:
        raise HTTPException(404, "Canvas requirement not found in this quarter")
    task, link = SddTask, SddTaskRequirement
    base = _task_links(db, workspace_id, params.requirement_id, params.relation_type)
    if params.cursor:
        if len(params.cursor) > 36:
            raise HTTPException(422, "CANVAS_INVALID_CURSOR")
        base = base.filter(link.task_id > params.cursor)
    raw = [row.task_id for row in base.order_by(link.task_id).limit(SCAN_LIMIT + 1)]
    eligible = db.query(task.id).filter(task.workspace_id == workspace_id, task.id.in_(raw[:SCAN_LIMIT]))
    if params.slice:
        eligible = in_range(eligible, task.created_at, dates)
    matches = {row.id for row in _task_filter(eligible, params)}
    selected = [identifier for identifier in raw[:SCAN_LIMIT] if identifier in matches]
    if len(selected) > TASK_PAGE_LIMIT:
        page = selected[:TASK_PAGE_LIMIT]
        return page, page[-1]
    return selected, raw[SCAN_LIMIT - 1] if len(raw) > SCAN_LIMIT else None


def _knowledge_page(db, workspace_id, kinds, dates, params):
    ordered = [
        kind for kind in KNOWLEDGE_KINDS if kind in kinds and (params.source_kind is None or params.source_kind == kind)
    ]
    cursor = params.cursor
    if cursor:
        kind = _unpack_cursor(cursor)[0]
        if kind not in ordered:
            raise HTTPException(422, "CANVAS_INVALID_CURSOR")
        ordered = ordered[ordered.index(kind) :]
    queries = {kind: (model, query) for kind, model, _, query in sources.catalog_queries(db, workspace_id, ordered)}
    selected = []
    for kind in ordered:
        model, query = queries[kind]
        rows = _date_page(in_range(query, model.created_at, dates), model, kind, cursor, TASK_PAGE_LIMIT + 1)
        cursor = None
        for row in rows:
            if len(selected) == TASK_PAGE_LIMIT:
                last_kind, last = selected[-1]
                return [sources.reference_for(tag, item.id) for tag, item in selected], _date_cursor(last, last_kind)
            selected.append((kind, row))
    return [sources.reference_for(tag, item.id) for tag, item in selected], None


def _knowledge_neighbors(db, workspace_id, kinds, refs):
    by_kind = {kind: [item.id for item in refs if item.kind == kind] for kind in KNOWLEDGE_KINDS}
    neighbors = []
    if "task" in kinds:
        for (identifier,) in (
            db.query(SddAsset.task_id)
            .filter(SddAsset.workspace_id == workspace_id, SddAsset.id.in_(by_kind["document"]))
            .distinct()
            .limit(12)
        ):
            neighbors.append(sources.reference_for("task", identifier))
        for (identifier,) in (
            db.query(SddCase.source_task_id)
            .filter(
                SddCase.workspace_id == workspace_id,
                SddCase.id.in_(by_kind["case"]),
                SddCase.source_task_id.is_not(None),
            )
            .distinct()
            .limit(12)
        ):
            neighbors.append(sources.reference_for("task", identifier))
    if "requirement" in kinds:
        link = SddRequirementDocumentLink
        for (identifier,) in (
            db.query(link.requirement_id)
            .filter(
                or_(link.document_id.in_(by_kind["requirement_document"]), link.task_asset_id.in_(by_kind["document"]))
            )
            .distinct()
            .limit(12)
        ):
            neighbors.append(sources.reference_for("requirement", identifier))
    if "playbook" in kinds and by_kind["case"]:
        link = CasePlaybookLink
        for (identifier,) in (
            db.query(link.spec_id)
            .filter(link.case_id.in_(by_kind["case"]), link.spec_id.is_not(None))
            .distinct()
            .limit(8)
        ):
            neighbors.append(sources.reference_for("playbook", identifier))
    return neighbors[:EXTRA_ASSET_LIMIT]


def read_branch(db: Session, workspace_id: str, kinds, calendar: FiscalCalendar, params: CanvasBranchQuery):
    quarter = calendar.period(params.quarter)
    quarter_dates = calendar.dates(quarter)
    try:
        dates = calendar.slice(quarter, params.slice)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if params.kind == "knowledge":
        refs, cursor = _knowledge_page(db, workspace_id, kinds, dates, params)
        return _load(
            db,
            workspace_id,
            calendar,
            [*refs, *_knowledge_neighbors(db, workspace_id, kinds, refs)],
            cursor=cursor,
            loaded=len(refs),
        )
    if (params.kind == "requirements" and "requirement" not in kinds) or (
        params.kind != "requirements" and "task" not in kinds
    ):
        return CanvasBranchWindow(assets=[], relations=[])
    if params.kind == "requirements":
        rows = _date_page(
            _requirement_ids(db, workspace_id, dates),
            SddRequirement,
            "requirement",
            params.cursor,
            REQUIREMENT_LIMIT + 1,
        )
        page = rows[:REQUIREMENT_LIMIT]
        refs, groups = _requirement_content(db, workspace_id, kinds, [row.id for row in page], inline=True)
        cursor = _date_cursor(page[-1], "requirement") if len(rows) > REQUIREMENT_LIMIT else None
        return _load(db, workspace_id, calendar, refs, groups, cursor, len(page))
    if params.kind == "requirement_tasks":
        if "requirement" not in kinds:
            return CanvasBranchWindow(assets=[], relations=[])
        task_ids, cursor = _linked_task_page(db, workspace_id, dates, quarter_dates, params)
        refs = [sources.reference_for("requirement", params.requirement_id)]
    else:
        task_ids, cursor = _period_task_page(db, workspace_id, dates, quarter_dates, params)
        refs = []
    refs.extend(sources.reference_for("task", identifier) for identifier in task_ids)
    refs.extend(_task_neighbors(db, workspace_id, kinds, task_ids, quarter_dates, cross=params.kind == "cross_quarter"))
    return _load(db, workspace_id, calendar, refs, cursor=cursor, loaded=len(task_ids))
