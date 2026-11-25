from collections import defaultdict

from sqlalchemy import or_
from sqlalchemy.orm import aliased

from app.domains.asset.models.asset import DOCUMENT_ASSET_TYPES, SddAsset
from app.domains.case_center.models.case import SddCase
from app.domains.diagnosis_playbook.models import CasePlaybookLink, PlaybookRun, PlaybookSpec, TaskPlaybookBinding
from app.domains.task.models.task import SddTask, TaskType
from app.domains.workspace_asset.models.requirement_document import SddRequirementDocumentLink
from app.domains.workspace_asset.models.workspace_asset import SddRequirement, SddTaskRequirement

PARENT_MODELS = {"requirement": SddRequirement, "task": SddTask, "case": SddCase}


def _requirement_queries(db, workspace_id, identifier):
    child = aliased(SddRequirement)
    yield (
        "requirement",
        child.id,
        db.query(child).filter(child.workspace_id == workspace_id, child.parent_requirement_id == identifier),
    )
    link = SddTaskRequirement
    yield (
        "task",
        link.task_id,
        db.query(link).filter(link.workspace_id == workspace_id, link.requirement_id == identifier),
    )
    document = SddRequirementDocumentLink
    links = db.query(document).filter(document.requirement_id == identifier)
    yield "requirement_document", document.document_id, links
    yield (
        "document",
        document.task_asset_id,
        links.join(SddAsset, SddAsset.id == document.task_asset_id).filter(
            SddAsset.workspace_id == workspace_id, SddAsset.asset_type.in_(DOCUMENT_ASSET_TYPES)
        ),
    )


def _task_queries(db, workspace_id, identifier, dates, diagnosis):
    yield (
        "document",
        SddAsset.id,
        db.query(SddAsset).filter(
            SddAsset.workspace_id == workspace_id,
            SddAsset.task_id == identifier,
            SddAsset.asset_type.in_(DOCUMENT_ASSET_TYPES),
        ),
    )
    if dates:
        link, req = SddTaskRequirement, SddRequirement
        start, end = dates.utc_bounds
        yield (
            "requirement",
            req.id,
            db.query(req.id)
            .select_from(link)
            .join(req, req.id == link.requirement_id)
            .filter(
                link.workspace_id == workspace_id,
                link.task_id == identifier,
                req.workspace_id == workspace_id,
                or_(req.created_at < start, req.created_at >= end),
            ),
        )
    if not diagnosis:
        return
    yield (
        "case",
        SddCase.id,
        db.query(SddCase).filter(SddCase.workspace_id == workspace_id, SddCase.source_task_id == identifier),
    )
    owner = aliased(SddTask)
    guide = owner.task_meta_json["diagnosis_playbook_guide"]["spec_id"].as_string()
    yield (
        "playbook",
        PlaybookSpec.id,
        db.query(PlaybookSpec)
        .join(owner, guide == PlaybookSpec.id)
        .filter(owner.id == identifier, owner.workspace_id == workspace_id, PlaybookSpec.workspace_id == workspace_id),
    )
    run = PlaybookRun
    yield (
        "playbook",
        run.spec_id,
        db.query(run)
        .join(TaskPlaybookBinding, TaskPlaybookBinding.active_run_id == run.id)
        .filter(run.workspace_id == workspace_id, run.task_id == identifier, TaskPlaybookBinding.task_id == identifier),
    )


def child_queries(db, workspace_id, kinds, kind, identifier, dates, *, diagnosis=False):
    if kind == "requirement":
        queries = _requirement_queries(db, workspace_id, identifier)
    elif kind == "task":
        queries = _task_queries(db, workspace_id, identifier, dates, diagnosis)
    elif kind == "case":
        link = CasePlaybookLink
        queries = [
            (
                "playbook",
                link.spec_id,
                db.query(link)
                .join(PlaybookSpec, PlaybookSpec.id == link.spec_id)
                .filter(link.case_id == identifier, PlaybookSpec.workspace_id == workspace_id),
            )
        ]
    else:
        return
    for child_kind, column, query in queries:
        if child_kind in kinds:
            yield child_kind, column, query


def mark_children(db, workspace_id, kinds, dates, assets, *, known=()):
    visible = defaultdict(set)
    parents = defaultdict(list)
    for reference in known:
        visible[reference.kind].add(reference.id)
    for asset in assets:
        kind = asset.reference.kind
        visible[kind].add(asset.reference.id)
        historical = (
            kind == "requirement"
            and dates
            and asset.details.created_at
            and not dates.contains(asset.details.created_at)
        )
        if kind in PARENT_MODELS and not historical:
            parents[(kind, asset.details.task_type == TaskType.DIAGNOSIS.value)].append(asset)
    for (kind, diagnosis), group in parents.items():
        model = PARENT_MODELS[kind]
        queries = [
            (child_kind, column, query.with_entities(column).filter(column.is_not(None)))
            for child_kind, column, query in child_queries(
                db, workspace_id, kinds, kind, model.id, dates, diagnosis=diagnosis
            )
        ]
        if not queries:
            continue
        children = or_(*(query.exists() for _, _, query in queries))
        unseen = or_(*(query.filter(column.not_in(visible[kind])).exists() for kind, column, query in queries))
        rows = db.query(model.id, children, unseen).filter(
            model.workspace_id == workspace_id, model.id.in_([asset.reference.id for asset in group])
        )
        flags = {identifier: (bool(exists), bool(hidden)) for identifier, exists, hidden in rows}
        for asset in group:
            asset.has_tree_children, asset.has_unseen_children = flags.get(asset.reference.id, (False, False))
