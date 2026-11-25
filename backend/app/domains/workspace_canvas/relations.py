from collections import defaultdict, deque
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.domains.case_center.models.case import SddCase
from app.domains.diagnosis_playbook.models import CasePlaybookLink, PlaybookRun, TaskPlaybookBinding
from app.domains.task.models.task import SddTask, TaskType
from app.domains.workspace_asset.models.requirement_document import SddRequirementDocumentLink
from app.domains.workspace_asset.models.workspace_asset import SddRequirement, SddTaskRequirement
from app.domains.workspace_asset.services.requirements.documents import requirement_links
from app.domains.workspace_canvas.schemas import CanvasAsset, CanvasRelation, RelationType, SourceKind


def _promoted_specs(rows: list[CasePlaybookLink]) -> set[tuple[str, str]]:
    promoted = set()
    revisions = defaultdict(list)
    for row in rows:
        revision = row.revision_json or {}
        if revision.get("kind") == "CASE_PROMOTION":
            promoted.add((row.case_id, row.spec_id))
        elif revision.get("kind") == "PLAYBOOK_EDIT" and revision.get("previous_spec_id"):
            revisions[(row.case_id, revision["previous_spec_id"])].append((row.case_id, row.spec_id))
    pending = deque(promoted)
    while pending:
        for revision in revisions[pending.popleft()]:
            if revision not in promoted:
                promoted.add(revision)
                pending.append(revision)
    return promoted


def _diagnosis_relations(
    db: Session,
    workspace_id: str,
    by_kind: dict[SourceKind, dict[str, CanvasAsset]],
    connect: Callable[[SourceKind, str, SourceKind, str, RelationType], None],
) -> None:
    diagnosis_tasks = {
        task_id for task_id, asset in by_kind["task"].items() if asset.details.task_type == TaskType.DIAGNOSIS.value
    }
    cases = by_kind["case"].keys()
    playbooks = by_kind["playbook"].keys()

    if cases and diagnosis_tasks:
        for case_id, task_id in db.query(SddCase.id, SddCase.source_task_id).filter(
            SddCase.workspace_id == workspace_id, SddCase.id.in_(cases), SddCase.source_task_id.in_(diagnosis_tasks)
        ):
            connect("case", case_id, "task", task_id, "CASE_TASK")

    if cases and playbooks:
        rows = (
            db.query(CasePlaybookLink)
            .filter(CasePlaybookLink.case_id.in_(cases), CasePlaybookLink.spec_id.in_(playbooks))
            .all()
        )
        promoted = _promoted_specs(rows)
        for row in rows:
            relation_type = "CASE_PROMOTION" if (row.case_id, row.spec_id) in promoted else "CASE_PLAYBOOK"
            connect("case", row.case_id, "playbook", row.spec_id, relation_type)

    if diagnosis_tasks and playbooks:
        guide_id = SddTask.task_meta_json["diagnosis_playbook_guide"]["spec_id"].as_string()
        for task_id, spec_id in db.query(SddTask.id, guide_id).filter(
            SddTask.workspace_id == workspace_id,
            SddTask.id.in_(diagnosis_tasks),
            guide_id.in_(playbooks),
        ):
            connect("task", task_id, "playbook", spec_id, "TASK_PLAYBOOK")

        run = PlaybookRun
        binding = TaskPlaybookBinding
        for task_id, spec_id in (
            db.query(run.task_id, run.spec_id)
            .join(binding, (binding.active_run_id == run.id) & (binding.task_id == run.task_id))
            .filter(run.workspace_id == workspace_id, run.task_id.in_(diagnosis_tasks), run.spec_id.in_(playbooks))
        ):
            connect("task", task_id, "playbook", spec_id, "TASK_PLAYBOOK")


def load_relations(db: Session, workspace_id: str, assets: list[CanvasAsset]) -> list[CanvasRelation]:
    by_kind: dict[SourceKind, dict[str, CanvasAsset]] = defaultdict(dict)
    for asset in assets:
        by_kind[asset.reference.kind][asset.reference.id] = asset
    result = {}

    def connect(
        source_kind: SourceKind,
        source_id: str,
        target_kind: SourceKind,
        target_id: str,
        relation_type: RelationType,
        link_id: str | None = None,
    ) -> None:
        source, target = by_kind[source_kind].get(source_id), by_kind[target_kind].get(target_id)
        if source and target and source.node_id != target.node_id:
            result[(source.node_id, target.node_id, relation_type)] = CanvasRelation(
                source=source.reference,
                target=target.reference,
                relation_type=relation_type,
                link_id=link_id,
            )

    requirements = by_kind["requirement"].keys()
    tasks = by_kind["task"].keys()

    if requirements and tasks:
        task_link = SddTaskRequirement
        for row in db.query(task_link).filter(
            task_link.workspace_id == workspace_id,
            task_link.requirement_id.in_(requirements),
            task_link.task_id.in_(tasks),
        ):
            connect("task", row.task_id, "requirement", row.requirement_id, row.relation_type.value, row.id)

    if requirements:
        requirement = SddRequirement
        for requirement_id, parent_id, predecessor_id in db.query(
            requirement.id,
            requirement.parent_requirement_id,
            requirement.predecessor_id,
        ).filter(requirement.workspace_id == workspace_id, requirement.id.in_(requirements)):
            if parent_id:
                connect("requirement", requirement_id, "requirement", parent_id, "SUB_REQUIREMENT")
            if predecessor_id:
                connect("requirement", requirement_id, "requirement", predecessor_id, "PREREQUISITE")

        link = SddRequirementDocumentLink
        for link_id, requirement_id, document_id, asset_id in (
            requirement_links(db, workspace_id)
            .with_entities(link.id, link.requirement_id, link.document_id, link.task_asset_id)
            .filter(link.requirement_id.in_(requirements))
        ):
            if document_id:
                connect(
                    "requirement_document", document_id, "requirement", requirement_id, "DOCUMENT_REQUIREMENT", link_id
                )
            elif asset_id:
                connect("document", asset_id, "requirement", requirement_id, "DOCUMENT_REQUIREMENT", link_id)

    for asset in by_kind["document"].values():
        if asset.details.task_id:
            connect("document", asset.reference.id, "task", asset.details.task_id, "DOCUMENT_TASK")

    _diagnosis_relations(db, workspace_id, by_kind, connect)
    return [result[key] for key in sorted(result)]
