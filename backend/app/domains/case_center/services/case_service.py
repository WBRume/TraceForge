"""
案例知识中心服务：案例 CRUD、生命周期状态机与「一键转案例」。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from app.core.logging import audit_log, get_logger
from app.domains.auth.models.user import User, Workspace
from app.domains.case_center.models.case import (
    CaseCategory,
    CasePriority,
    CaseReviewAction,
    CaseStatus,
    SddCase,
    SddCaseReviewRecord,
)
from app.domains.case_center.schemas.case import (
    CaseCreateRequest,
    CaseDraftCreateRequest,
    CaseUpdateRequest,
)
from app.domains.task.models.task import SddTask, TaskType
from app.domains.task.services import task_service
from app.domains.workspace.models.workspace_repository import SddWorkspaceRepository
from app.domains.workspace.services import workspace_service
from app.domains.rag.services import outbox_service as rag_outbox_service

logger = get_logger(__name__, category="case")


class CaseError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


_EDITABLE_STATUSES = {CaseStatus.DRAFT.value, CaseStatus.REJECTED.value}
_TERMINAL_EDIT_STATUSES = {CaseStatus.APPROVED.value}


def _clean(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def _case_query(db: Session):
    return db.query(SddCase).options(
        joinedload(SddCase.creator),
        joinedload(SddCase.source_task),
        joinedload(SddCase.workspace).joinedload(Workspace.project),
        joinedload(SddCase.workspace).joinedload(Workspace.repositories),
        joinedload(SddCase.review_records).joinedload(SddCaseReviewRecord.reviewer),
    )


def serialize_case(case: SddCase) -> dict:
    records = []
    for record in case.review_records or []:
        reviewer_name = None
        reviewer = getattr(record, "reviewer", None)
        if reviewer is not None:
            reviewer_name = reviewer.display_name
        records.append(
            {
                "id": record.id,
                "action": record.action,
                "comment": record.comment,
                "reviewer_id": record.reviewer_id,
                "reviewer_name": reviewer_name,
                "created_at": record.created_at,
            }
        )
    snapshot = case.conversation_snapshot_json
    diagnosis_detail = case.diagnosis_detail_json

    workspace = case.workspace
    project = workspace.project if workspace else None
    project_products = []
    if project:
        for link in project.products or []:
            product = link.product
            if product is None:
                continue
            project_products.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "code": product.code,
                    "version_no": product.version_no,
                }
            )

    repositories = []
    if workspace:
        repositories = [
            {
                "id": repo.id,
                "name": repo.repo_name,
                "repo_name": repo.repo_name,
                "repo_url": repo.repo_url,
                "repo_slug": repo.repo_slug,
                "branch_name": repo.branch_name,
            }
            for repo in workspace.repositories or []
        ]

    product_name = _clean(case.product_name) or (_clean(project_products[0]["name"]) if project_products else None)
    product_version = _clean(case.product_version) or (
        _clean(project_products[0].get("version_no")) if project_products else None
    )

    return {
        "id": case.id,
        "workspace_id": case.workspace_id,
        "workspace_name": workspace.name if workspace else None,
        "project_name": project.name if project else None,
        "project_products": project_products,
        "repositories": repositories,
        "creator_id": case.creator_id,
        "source_task_id": case.source_task_id,
        "title": case.title,
        "problem_description": case.problem_description,
        "product_name": product_name,
        "product_version": product_version,
        "site_name": case.site_name,
        "code_context": case.code_context,
        "analysis_process": case.analysis_process,
        "root_cause": case.root_cause,
        "solution": case.solution,
        "category": case.category,
        "priority": case.priority,
        "status": case.status,
        "review_round": case.review_round,
        "conversation_snapshot": snapshot if isinstance(snapshot, list) else None,
        "diagnosis_detail": diagnosis_detail if isinstance(diagnosis_detail, dict) else None,
        "submitted_at": case.submitted_at,
        "reviewed_at": case.reviewed_at,
        "rejected_comment": case.rejected_comment,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "creator_name": case.creator.display_name if case.creator else None,
        "source_task_name": case.source_task.name if case.source_task else None,
        "review_records": records,
    }


def _apply_case_filters(
    query,
    *,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    source_task_id: Optional[str] = None,
):
    if source_task_id:
        query = query.filter(SddCase.source_task_id == source_task_id)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            SddCase.title.ilike(like)
            | SddCase.problem_description.ilike(like)
            | SddCase.root_cause.ilike(like)
            | SddCase.solution.ilike(like)
            | SddCase.code_context.ilike(like)
            | SddCase.site_name.ilike(like)
        )
    if category:
        query = query.filter(SddCase.category == category)
    if status:
        query = query.filter(SddCase.status == status)
    if priority:
        query = query.filter(SddCase.priority == priority)
    return query


def _paginate_cases(query, page: int, page_size: int) -> Tuple[List[SddCase], int]:
    total = query.count()
    items = (
        query.order_by(SddCase.updated_at.desc(), SddCase.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def list_cases(
    db: Session,
    workspace_id: str,
    *,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    source_task_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[SddCase], int]:
    query = _apply_case_filters(
        _case_query(db).filter(SddCase.workspace_id == workspace_id),
        keyword=keyword,
        category=category,
        status=status,
        priority=priority,
        source_task_id=source_task_id,
    )
    return _paginate_cases(query, page, page_size)


def list_cases_in_workspaces(
    db: Session,
    workspace_ids: List[str],
    *,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[SddCase], int]:
    if not workspace_ids:
        return [], 0
    query = _apply_case_filters(
        _case_query(db).filter(SddCase.workspace_id.in_(workspace_ids)),
        keyword=keyword,
        category=category,
        status=status,
        priority=priority,
    )
    return _paginate_cases(query, page, page_size)


def get_case(db: Session, case_id: str, workspace_id: str) -> Optional[SddCase]:
    return (
        _case_query(db)
        .filter(SddCase.id == case_id, SddCase.workspace_id == workspace_id)
        .first()
    )


def _require_case(db: Session, case_id: str, workspace_id: str) -> SddCase:
    case = get_case(db, case_id, workspace_id)
    if not case:
        raise CaseError("Case not found", status_code=404)
    return case


def _apply_fields(case: SddCase, payload: dict) -> None:
    for field in (
        "title",
        "problem_description",
        "product_name",
        "product_version",
        "site_name",
        "code_context",
        "analysis_process",
        "root_cause",
        "solution",
    ):
        if field in payload:
            setattr(case, field, _clean(payload.get(field)) if payload.get(field) is not None else None)
    if payload.get("category") is not None:
        case.category = payload["category"]
    if payload.get("priority") is not None:
        case.priority = payload["priority"]


def create_case(
    db: Session,
    workspace_id: str,
    creator: User,
    data: CaseCreateRequest,
) -> SddCase:
    case = SddCase(
        workspace_id=workspace_id,
        creator_id=creator.id,
        title=_clean(data.title) or "未命名案例",
        problem_description=data.problem_description,
        product_name=_clean(data.product_name),
        product_version=_clean(data.product_version),
        site_name=_clean(data.site_name),
        code_context=data.code_context,
        analysis_process=data.analysis_process,
        root_cause=data.root_cause,
        solution=data.solution,
        category=data.category,
        priority=data.priority,
        status=CaseStatus.DRAFT.value,
        review_round=1,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    audit_log(
        action="case_create",
        outcome="success",
        resource_type="case",
        resource_id=case.id,
        user_id=creator.id,
        workspace_id=workspace_id,
    )
    return _require_case(db, case.id, workspace_id)


def update_case(
    db: Session,
    case_id: str,
    workspace_id: str,
    actor: User,
    data: CaseUpdateRequest,
) -> SddCase:
    case = _require_case(db, case_id, workspace_id)
    if case.status not in _EDITABLE_STATUSES:
        raise CaseError(
            f"Case can only be edited in DRAFT or REJECTED state (current: {case.status})",
            status_code=409,
        )
    _apply_fields(case, data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(case)
    audit_log(
        action="case_update",
        outcome="success",
        resource_type="case",
        resource_id=case.id,
        user_id=actor.id,
        workspace_id=workspace_id,
    )
    return _require_case(db, case.id, workspace_id)


def delete_case(
    db: Session,
    case_id: str,
    workspace_id: str,
    actor: User,
) -> None:
    case = _require_case(db, case_id, workspace_id)
    if case.status not in _EDITABLE_STATUSES and case.status not in _TERMINAL_EDIT_STATUSES:
        raise CaseError(
            f"Case cannot be deleted in state {case.status}",
            status_code=409,
        )
    db.delete(case)
    db.commit()
    audit_log(
        action="case_delete",
        outcome="success",
        resource_type="case",
        resource_id=case_id,
        user_id=actor.id,
        workspace_id=workspace_id,
    )


def submit_case(
    db: Session,
    case_id: str,
    workspace_id: str,
    actor: User,
) -> SddCase:
    case = _require_case(db, case_id, workspace_id)
    if case.status != CaseStatus.DRAFT.value:
        raise CaseError(f"Only DRAFT cases can be submitted (current: {case.status})", status_code=409)
    if not _clean(case.title) or not _clean(case.problem_description):
        raise CaseError("Title and problem description are required before submitting for review")
    case.status = CaseStatus.PENDING_REVIEW.value
    case.submitted_at = datetime.utcnow()
    case.reviewed_at = None
    case.rejected_comment = None
    db.commit()
    db.refresh(case)
    audit_log(
        action="case_submit",
        outcome="success",
        resource_type="case",
        resource_id=case.id,
        user_id=actor.id,
        workspace_id=workspace_id,
    )
    return _require_case(db, case.id, workspace_id)


def start_review(
    db: Session,
    case_id: str,
    workspace_id: str,
    reviewer: User,
) -> SddCase:
    case = _require_case(db, case_id, workspace_id)
    if case.status != CaseStatus.PENDING_REVIEW.value:
        raise CaseError(f"Only PENDING_REVIEW cases can be taken for review (current: {case.status})", status_code=409)
    case.status = CaseStatus.IN_REVIEW.value
    db.add(
        SddCaseReviewRecord(
            case_id=case.id,
            workspace_id=workspace_id,
            reviewer_id=reviewer.id,
            action=CaseReviewAction.START.value,
            comment=None,
        )
    )
    db.commit()
    db.refresh(case)
    audit_log(
        action="case_review_start",
        outcome="success",
        resource_type="case",
        resource_id=case.id,
        user_id=reviewer.id,
        workspace_id=workspace_id,
    )
    return _require_case(db, case.id, workspace_id)


def review_case(
    db: Session,
    case_id: str,
    workspace_id: str,
    reviewer: User,
    *,
    conclusion: str,
    comment: Optional[str],
) -> SddCase:
    case = _require_case(db, case_id, workspace_id)
    if case.status != CaseStatus.IN_REVIEW.value:
        raise CaseError(f"Only IN_REVIEW cases can be decided (current: {case.status})", status_code=409)

    if conclusion == "approve":
        case.status = CaseStatus.APPROVED.value
        action = CaseReviewAction.APPROVE.value
    elif conclusion == "reject":
        case.status = CaseStatus.REJECTED.value
        case.rejected_comment = _clean(comment)
        action = CaseReviewAction.REJECT.value
    else:
        raise CaseError(f"Unknown review conclusion: {conclusion}")

    case.reviewed_at = datetime.utcnow()
    db.add(
        SddCaseReviewRecord(
            case_id=case.id,
            workspace_id=workspace_id,
            reviewer_id=reviewer.id,
            action=action,
            comment=_clean(comment),
        )
    )
    db.commit()
    db.refresh(case)
    audit_log(
        action="case_review_decide",
        outcome="success",
        resource_type="case",
        resource_id=case.id,
        user_id=reviewer.id,
        workspace_id=workspace_id,
        conclusion=conclusion,
    )
    if conclusion == "approve":
        try:
            rag_outbox_service.enqueue_case_published(db, case)
        except Exception:
            logger.exception("Failed to enqueue RAG document for approved case %s", case.id)
    return _require_case(db, case.id, workspace_id)


def resubmit_case(
    db: Session,
    case_id: str,
    workspace_id: str,
    actor: User,
) -> SddCase:
    case = _require_case(db, case_id, workspace_id)
    if case.status != CaseStatus.REJECTED.value:
        raise CaseError(f"Only REJECTED cases can be resubmitted (current: {case.status})", status_code=409)
    if not _clean(case.title) or not _clean(case.problem_description):
        raise CaseError("Title and problem description are required before submitting for review")
    case.status = CaseStatus.PENDING_REVIEW.value
    case.review_round += 1
    case.submitted_at = datetime.utcnow()
    case.reviewed_at = None
    case.rejected_comment = None
    db.commit()
    db.refresh(case)
    audit_log(
        action="case_resubmit",
        outcome="success",
        resource_type="case",
        resource_id=case.id,
        user_id=actor.id,
        workspace_id=workspace_id,
        review_round=case.review_round,
    )
    return _require_case(db, case.id, workspace_id)


def _format_call_chain(items) -> Optional[str]:
    """调用链路 → 可读文本。"""
    lines = []
    for node in items or []:
        if not isinstance(node, dict):
            continue
        module = str(node.get("module") or "").strip()
        function = str(node.get("function") or "").strip()
        file_path = str(node.get("file_path") or "").strip()
        description = str(node.get("description") or "").strip()
        label = ".".join(part for part in (module, function) if part)
        if not label and not file_path:
            continue
        seq = node.get("seq")
        prefix = f"{seq}. " if seq is not None else ""
        body = " - ".join(part for part in (label or file_path, description) if part)
        lines.append(prefix + body)
    return "调用链路:\n" + "\n".join(lines) if lines else None


def _format_code_context_items(items) -> Optional[str]:
    """相关代码上下文条目 → 可读文本。"""
    lines = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file_path") or "").strip()
        if not file_path:
            continue
        start = item.get("start_line")
        end = item.get("end_line")
        if start and end and end != start:
            location = f":{start}-{end}"
        elif start:
            location = f":{start}"
        else:
            location = ""
        note = str(item.get("note") or "").strip()
        line = f"{file_path}{location}"
        if note:
            line += f" - {note}"
        lines.append(line)
    return "相关代码上下文:\n" + "\n".join(lines) if lines else None


def capture_conversation_snapshot(db: Session, task: SddTask) -> Optional[list]:
    """从任务会话历史生成对话回放快照（精简字段）。"""
    history = task_service.get_task_history(
        db,
        task.id,
        task.workspace_id,
        page=1,
        page_size=2000,
    )
    messages = history.get("messages") or []
    snapshot = []
    for msg in messages:
        snapshot.append(
            {
                "role": msg.get("role"),
                "content": msg.get("content"),
                "message_type": msg.get("type") or msg.get("message_type"),
                "created_at": msg.get("created_at"),
                "creator_display_name": msg.get("creator_display_name"),
            }
        )
    return snapshot or None


def _workspace_product_prefill(db: Session, workspace_id: str) -> Tuple[Optional[str], Optional[str]]:
    from app.domains.auth.models.user import Workspace
    from app.domains.management.models.management import (
        SddManagementProject,
        SddManagementProjectProduct,
    )

    workspace = (
        db.query(Workspace)
        .options(
            joinedload(Workspace.project)
            .joinedload(SddManagementProject.products)
            .joinedload(SddManagementProjectProduct.product)
        )
        .filter(Workspace.id == workspace_id)
        .first()
    )
    if not workspace or not workspace.project:
        return None, None
    products = workspace_service.serialize_workspace_products(workspace.project)
    if len(products) == 1:
        return products[0].get("name"), products[0].get("version_no")
    return None, None


def create_case_draft_from_task(
    db: Session,
    *,
    task: SddTask,
    creator: User,
    workspace_id: str,
    data: CaseDraftCreateRequest,
) -> SddCase:
    """问题定位任务「确认采纳 → 一键转案例」：生成案例草稿并携带对话快照。"""
    if task.task_type != TaskType.DIAGNOSIS.value:
        raise CaseError("Only diagnosis tasks can be converted to cases", status_code=403)

    existing = (
        db.query(SddCase)
        .filter(SddCase.workspace_id == workspace_id, SddCase.source_task_id == task.id)
        .first()
    )
    if existing:
        raise CaseError(
            f"Case already exists for this task: {existing.id}",
            status_code=409,
        )

    task_meta = task.task_meta_json if isinstance(task.task_meta_json, dict) else {}
    phenomenon = _clean(str(task_meta.get("phenomenon") or ""))
    description_parts = [part for part in [task.description, phenomenon] if part]
    problem_description = "\n\n".join(description_parts) or None

    prefill_product, prefill_version = _workspace_product_prefill(db, workspace_id)
    product_name = _clean(data.product_name) or prefill_product
    product_version = _clean(data.product_version) or prefill_version

    snapshot = capture_conversation_snapshot(db, task)

    repo_slugs = get_workspace_repo_slugs(db, workspace_id)
    code_context = None
    if repo_slugs:
        code_context = "工作区关联仓库: " + ", ".join(repo_slugs)

    case = SddCase(
        workspace_id=workspace_id,
        creator_id=creator.id,
        source_task_id=task.id,
        title=task.name,
        problem_description=problem_description,
        product_name=product_name,
        product_version=product_version,
        site_name=_clean(data.site_name),
        code_context=code_context,
        analysis_process=None,
        root_cause=None,
        solution=None,
        category=data.category,
        priority=data.priority,
        status=CaseStatus.DRAFT.value,
        review_round=1,
        conversation_snapshot_json=snapshot,
    )
    db.add(case)
    db.flush()

    diagnosis_result = getattr(task, "diagnosis_result", None)
    if diagnosis_result is not None:
        diagnosis_result.status = "CONFIRMED"
        # 定位结果 → 案例结构化字段映射：
        # 证据链+置信度 → 分析过程；调用链路 → diagnosis_detail_json；
        # 根因结论 → 根因；修复建议+修复代码 → 方案；
        # 相关代码上下文 → 代码上下文；结构化明细 → diagnosis_detail_json。
        analysis_parts = [part for part in [diagnosis_result.evidence_chain] if part]
        confidence = diagnosis_result.confidence if diagnosis_result.confidence is not None else 0
        analysis_parts.append(f"置信度: {confidence}%")
        case.analysis_process = "\n\n".join(analysis_parts) or None
        case.root_cause = diagnosis_result.root_cause or None

        solution_parts = [part for part in [diagnosis_result.fix_suggestion] if part]
        fix_code = str(diagnosis_result.fix_code or "").strip()
        if fix_code:
            solution_parts.append("修复代码:\n" + fix_code)
        case.solution = "\n\n".join(solution_parts) or None

        context_items_text = _format_code_context_items(diagnosis_result.code_context_json)
        context_parts = [part for part in [case.code_context] if part]
        if context_items_text:
            context_parts.append(context_items_text)
        case.code_context = "\n\n".join(context_parts) or None

        case.diagnosis_detail_json = {
            "similar_cases": (
                diagnosis_result.similar_cases_json
                if isinstance(diagnosis_result.similar_cases_json, list)
                else []
            ),
            "call_chain": (
                diagnosis_result.call_chain_json
                if isinstance(diagnosis_result.call_chain_json, list)
                else []
            ),
            "code_context": (
                diagnosis_result.code_context_json
                if isinstance(diagnosis_result.code_context_json, list)
                else []
            ),
            "fix_code": diagnosis_result.fix_code,
        }

    db.commit()
    db.refresh(case)

    audit_log(
        action="case_draft_from_task",
        outcome="success",
        resource_type="case",
        resource_id=case.id,
        user_id=creator.id,
        workspace_id=workspace_id,
        task_id=task.id,
    )

    case = _require_case(db, case.id, workspace_id)
    if data.submit_for_review:
        case = submit_case(db, case.id, workspace_id, creator)
    return case


def get_workspace_repo_slugs(db: Session, workspace_id: str) -> List[str]:
    rows = (
        db.query(SddWorkspaceRepository.repo_name)
        .filter(SddWorkspaceRepository.workspace_id == workspace_id)
        .all()
    )
    return [row[0] for row in rows if row[0]]
