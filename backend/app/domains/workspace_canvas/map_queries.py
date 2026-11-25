from typing import Annotated

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.asset.models.asset import DOCUMENT_ASSET_TYPES, SddAsset
from app.domains.case_center.models.case import SddCase
from app.domains.diagnosis_playbook.models import CasePlaybookLink, PlaybookRun, TaskPlaybookBinding
from app.domains.task.models.task import SddTask, TaskType
from app.domains.workspace_asset.models.requirement_document import SddRequirementDocumentLink
from app.domains.workspace_asset.models.workspace_asset import SddRequirement, SddTaskRequirement
from app.domains.workspace_canvas import relations, sources
from app.domains.workspace_canvas.quarter_calendar import FiscalCalendar
from app.domains.workspace_canvas.schemas import CanvasAssetWindow, SourceReference

WINDOW_LIMIT = 12
RELATION_LIMIT = 128
VisibleAsset = Annotated[
    str, Field(pattern=r"^(requirement|task|case|playbook|document|requirement_document):[\w-]{1,36}$")
]
NEIGHBOR_KINDS = ("requirement", "requirement_document", "document", "case", "playbook", "task")


def search_assets(db: Session, workspace_id: str, kinds, query: str):
    refs = []
    name = query.lower()
    escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    for kind, _, title, base in sources.catalog_queries(db, workspace_id, kinds):
        prefix = func.lower(title)
        exact = base.filter(prefix == name).limit(4).all()
        matches = base.filter(prefix.like(escaped + "%", escape="\\"), prefix != name).limit(8 - len(exact))
        refs.extend(sources.reference_for(kind, row.id) for row in [*exact, *matches])
    assets = sources.assets_for_references(db, workspace_id, refs)
    return sorted(assets, key=lambda asset: (asset.details.title.casefold() != query.casefold(), asset.details.title))[
        :16
    ]


class Nearby:
    def __init__(self, db: Session, workspace_id: str, kinds, limit: int, cursor: str | None):
        self.db = db
        self.workspace_id = workspace_id
        self.kinds = kinds
        self.limit = limit
        kind, _, identifier = (cursor or "").partition(":")
        if cursor and (not identifier or len(identifier) > 36 or kind not in kinds or kind not in NEIGHBOR_KINDS):
            raise HTTPException(422, "CANVAS_INVALID_CURSOR")
        self.cursor = (NEIGHBOR_KINDS.index(kind), identifier) if cursor else (-1, "")
        self.refs: dict[tuple[int, str], SourceReference] = {}

    def add(self, kind, column, query):
        if kind not in self.kinds:
            return
        order = NEIGHBOR_KINDS.index(kind)
        previous_order, previous_id = self.cursor
        if order < previous_order:
            return
        after = column > previous_id if order == previous_order else column.is_not(None)
        for (identifier,) in (
            query.with_entities(column).filter(after).distinct().order_by(column).limit(self.limit + 1)
        ):
            self.refs[(order, identifier)] = sources.reference_for(kind, identifier)

    def requirement(self, rid: str):
        requirement = SddRequirement
        task_link = SddTaskRequirement
        document_link = SddRequirementDocumentLink
        own = self.db.query(requirement).filter(requirement.id == rid, requirement.workspace_id == self.workspace_id)
        self.add("requirement", requirement.parent_requirement_id, own)
        self.add("requirement", requirement.predecessor_id, own)
        self.add(
            "requirement",
            requirement.id,
            self.db.query(requirement).filter(
                requirement.parent_requirement_id == rid, requirement.workspace_id == self.workspace_id
            ),
        )
        self.add(
            "requirement",
            requirement.id,
            self.db.query(requirement).filter(
                requirement.predecessor_id == rid, requirement.workspace_id == self.workspace_id
            ),
        )
        self.add(
            "task",
            task_link.task_id,
            self.db.query(task_link).filter(
                task_link.requirement_id == rid, task_link.workspace_id == self.workspace_id
            ),
        )
        links = self.db.query(document_link).filter(document_link.requirement_id == rid)
        self.add("requirement_document", document_link.document_id, links)
        self.add("document", document_link.task_asset_id, links)

    def task(self, tid: str):
        task_link = SddTaskRequirement
        self.add(
            "requirement",
            task_link.requirement_id,
            self.db.query(task_link).filter(task_link.task_id == tid, task_link.workspace_id == self.workspace_id),
        )
        self.add(
            "document",
            SddAsset.id,
            self.db.query(SddAsset).filter(
                SddAsset.task_id == tid,
                SddAsset.workspace_id == self.workspace_id,
                SddAsset.asset_type.in_(DOCUMENT_ASSET_TYPES),
            ),
        )
        self.add(
            "case",
            SddCase.id,
            self.db.query(SddCase).filter(SddCase.source_task_id == tid, SddCase.workspace_id == self.workspace_id),
        )
        guide = SddTask.task_meta_json["diagnosis_playbook_guide"]["spec_id"].as_string()
        self.add(
            "playbook",
            guide,
            self.db.query(SddTask).filter(SddTask.id == tid, SddTask.workspace_id == self.workspace_id),
        )
        run = PlaybookRun
        self.add(
            "playbook",
            run.spec_id,
            self.db.query(run)
            .join(TaskPlaybookBinding, TaskPlaybookBinding.active_run_id == run.id)
            .filter(run.task_id == tid, run.workspace_id == self.workspace_id),
        )

    def document(self, did: str, native: bool):
        link = SddRequirementDocumentLink
        column = link.document_id if native else link.task_asset_id
        self.add("requirement", link.requirement_id, self.db.query(link).filter(column == did))
        if not native:
            self.add(
                "task",
                SddAsset.task_id,
                self.db.query(SddAsset).filter(SddAsset.id == did, SddAsset.workspace_id == self.workspace_id),
            )

    def case(self, cid: str):
        self.add(
            "task",
            SddCase.source_task_id,
            self.db.query(SddCase)
            .join(SddTask, SddTask.id == SddCase.source_task_id)
            .filter(
                SddCase.id == cid,
                SddCase.workspace_id == self.workspace_id,
                SddTask.workspace_id == self.workspace_id,
                SddTask.task_type == TaskType.DIAGNOSIS,
            ),
        )
        self.add(
            "playbook",
            CasePlaybookLink.spec_id,
            self.db.query(CasePlaybookLink).filter(CasePlaybookLink.case_id == cid),
        )

    def playbook(self, pid: str):
        self.add(
            "case", CasePlaybookLink.case_id, self.db.query(CasePlaybookLink).filter(CasePlaybookLink.spec_id == pid)
        )

    def candidates(self, ref: SourceReference):
        if ref.kind in {"document", "requirement_document"}:
            self.document(ref.id, ref.kind == "requirement_document")
        elif ref.kind != "plan_document":
            getattr(self, ref.kind)(ref.id)
        return [candidate for _, candidate in sorted(self.refs.items())]


def read_window(
    db: Session,
    workspace_id: str,
    kinds,
    anchor: SourceReference,
    cursor: str | None,
    calendar: FiscalCalendar,
    quarter: str | None = None,
    visible: list[VisibleAsset] | None = None,
    reveal: VisibleAsset | None = None,
) -> CanvasAssetWindow:
    entry = sources.assign_quarters(sources.assets_for_references(db, workspace_id, [anchor]), calendar)
    if not entry:
        return CanvasAssetWindow(assets=[], relations=[])
    if quarter and anchor.kind == "requirement" and entry[0].quarter and entry[0].quarter.id != quarter:
        return CanvasAssetWindow(assets=entry, relations=[])
    candidates = Nearby(db, workspace_id, kinds, WINDOW_LIMIT, cursor).candidates(anchor)
    page = candidates[:WINDOW_LIMIT]
    ordered = page
    if reveal:
        kind, identifier = reveal.split(":", 1)
        if kind in kinds:
            selected = sources.reference_for(kind, identifier)
            ordered = [selected, *(ref for ref in page if ref != selected)]
    extra = sources.assets_for_references(db, workspace_id, [ref for ref in ordered if ref != anchor])
    indexed = {asset.node_id: asset for asset in sources.assign_quarters(extra, calendar)}
    neighbors = [*entry, *(indexed[key] for ref in ordered if (key := sources.catalog_node_id(ref)) in indexed)]
    direct = relations.load_relations(db, workspace_id, neighbors, RELATION_LIMIT, focus=entry)
    related = {ref.model_dump_json() for edge in direct for ref in (edge.source, edge.target)}
    assets = [*entry, *(asset for asset in neighbors[1:] if asset.reference.model_dump_json() in related)]
    window_ids = {asset.node_id for asset in assets}
    shown = []
    for item in visible or ():
        kind, identifier = item.split(":", 1)
        if kind in kinds:
            reference = sources.reference_for(kind, identifier)
            if sources.catalog_node_id(reference) not in window_ids:
                shown.append(reference)
    # The window stays one hop. Joining its endpoints to cards that are already
    # on the board keeps shared documents and promoted playbooks connected.
    cross = (
        relations.load_relations(
            db,
            workspace_id,
            [*assets, *sources.assets_for_references(db, workspace_id, shown)],
            RELATION_LIMIT * 2,
            focus=assets,
        )
        if shown or len(assets) > 2
        else []
    )
    edges = {
        (edge.source.model_dump_json(), edge.target.model_dump_json(), edge.relation_type): edge
        for edge in [*direct, *cross]
    }
    return CanvasAssetWindow(
        assets=assets,
        relations=list(edges.values()),
        next_cursor=f"{page[-1].kind}:{page[-1].id}" if len(candidates) > WINDOW_LIMIT else None,
    )
