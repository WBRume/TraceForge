"""Requirement preview 作业执行器：三段式（准备段 → CLI → 收尾段）。

事务与证据规则（doc §6/§7/§8）：
- DB 阶段在 ``run_db_txn`` 的 executor 线程内执行，CLI 调用期间不持有任何
  session；
- attempt 证据只能在事件循环线程解析（DB 线程读不到 attempt ContextVar），
  解析结果显式传入 DB finalizer；
- 终态写入经 ``converge_job_attempt_in_txn`` 统一 ownership 收敛，提交所有权
  归最外层 ``run_db_txn``；fence 命中抛 ``AttemptFencedError`` 整体回滚。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.agents import current_agent_attempt, current_agent_attempt_runtime
from app.agents.selection import resolve_workspace_backend
from app.core.logging import get_logger
from app.core.offload import run_db_txn
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptConvergenceRequest,
    AttemptFencedError,
    ConvergenceIntent,
    converge_job_attempt_in_txn,
    resolve_attempt_evidence,
)
from app.domains.ai.services.jobs.provider_turn import run_cli_single_turn
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.requirements.preview.job_service import (
    create_requirement_preview_batch,
    workspace_project_path_or_error,
)
from app.domains.workspace_asset.services.requirements.preview.prompt import (
    build_requirement_preview_prompt,
    coalesce_simple_import_preview_items,
    extract_json_object,
    normalize_ai_preview_items,
)
from app.domains.workspace_asset.services.requirements.queries import get_requirement
from app.domains.workspace_asset.services.requirements.segmentation import document_metadata

logger = get_logger(__name__, category="workspace_asset")


# ---------------------------------------------------------------------------
# Fence：无 ContextVar 依赖的 attempt 归属校验（DB 线程安全，doc §6.3）
# ---------------------------------------------------------------------------


def preview_attempt_is_current(
    job: SddAiJob,
    run_token: Optional[str],
    worker_boot_id: Optional[str] = None,
) -> bool:
    effective_token = run_token or None
    effective_boot_id = str(worker_boot_id or WORKER_BOOT_ID)
    if not effective_token:
        return True
    return bool(
        job.status == AiJobStatus.RUNNING
        and str(job.run_token or "") == str(effective_token)
        and str(job.worker_boot_id or "") == effective_boot_id
        and job.cancel_requested_at is None
    )


def assert_preview_attempt_current(
    job: SddAiJob,
    run_token: Optional[str],
    worker_boot_id: Optional[str] = None,
) -> None:
    if not preview_attempt_is_current(job, run_token, worker_boot_id):
        raise AttemptFencedError(
            f"Requirement preview attempt is no longer current: job_id={job.id}"
        )


def load_preview_job_sync(db: Session, job_id: str) -> Optional[SddAiJob]:
    return db.query(SddAiJob).filter(SddAiJob.id == job_id).first()


def update_preview_job_state(
    db: Session,
    job: SddAiJob,
    *,
    status: Optional[AiJobStatus] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
    context_patch: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    run_token: Optional[str] = None,
    worker_boot_id: Optional[str] = None,
    evidence: Optional[Any] = None,
) -> None:
    """preview job 状态写入（doc §6.3/§7.3）。

    evidence 与 run token / worker boot id 必须由调用方显式传入；本函数
    读取 attempt ContextVar（在 DB executor 线程中为空，导致 runtime
    evidence 丢失）。终态写入使用 ``converge_job_attempt_in_txn``，不在此
    处提交：job SUCCESS 与 batch/items/audit 必须由最外层事务原子提交。
    """
    effective_token = run_token or None
    effective_boot_id = str(worker_boot_id or WORKER_BOOT_ID)
    if effective_token and (
        str(job.run_token or "") != effective_token
        or str(job.worker_boot_id or "") != effective_boot_id
        or job.status in {AiJobStatus.TERMINATING, AiJobStatus.ORPHANED}
        or job.cancel_requested_at is not None
    ):
        logger.warning("Dropped fenced requirement preview write: job_id={}", job.id)
        raise AttemptFencedError(
            f"Requirement preview attempt is fenced: job_id={job.id}"
        )
    finalizing = status in {AiJobStatus.SUCCESS, AiJobStatus.FAILED, AiJobStatus.CANCELLED}
    if finalizing:
        # 统一 ownership 收敛（doc §11 / 修复方案 §7.3.1）：事务内核心，
        # 提交所有权归最外层 run_db_txn；fence 时抛出 AttemptFencedError
        # 让外层整体 rollback batch/items/audit。
        convergence_result = converge_job_attempt_in_txn(
            db,
            AttemptConvergenceRequest(
                job_id=str(job.id),
                run_token=str(effective_token or ""),
                worker_boot_id=effective_boot_id,
                requested_status=status,
                reason=str(error or ""),
                evidence=evidence
                if evidence is not None
                else resolve_attempt_evidence(
                    execution_kind=str(
                        getattr(job, "process_execution_kind", None) or ""
                    ).strip() or "LOCAL_PROCESS",
                ),
                message=message,
                error_message=error,
                result_patch=result,
                context_patch=context_patch,
                intent=ConvergenceIntent.NORMAL_FINALIZE,
            ),
        )
        if not convergence_result.changed:
            logger.warning(
                "Requirement preview convergence fenced: job_id={}, status={}",
                job.id,
                convergence_result.status,
            )
            raise AttemptFencedError(
                f"Requirement preview convergence fenced: job_id={job.id}"
            )
        # 注意：不得 expire/refresh —— convergence 的写入尚未 flush，
        # expire 会丢弃未提交修改；提交由最外层 run_db_txn 负责。
        return
    if status is not None:
        job.status = status
        if status == AiJobStatus.RUNNING and job.started_at is None:
            job.started_at = datetime.utcnow()
    if progress is not None:
        job.progress = max(0, min(100, int(progress)))
    if message is not None:
        job.message = message
    if error is not None:
        job.error_message = error
    if context_patch:
        context = job.context_json if isinstance(job.context_json, dict) else {}
        job.context_json = {**context, **context_patch}
    if result is not None:
        job.result_json = result
    db.commit()
    db.refresh(job)


def fail_requirement_preview_sync(
    db: Session,
    *,
    job_id: str,
    message: str,
    error: str,
    run_token: Optional[str] = None,
    worker_boot_id: Optional[str] = None,
    evidence: Optional[Any] = None,
) -> None:
    """preview job 失败终态（线程内单事务，重新加载 job 并加锁）。"""
    job = (
        db.query(SddAiJob)
        .filter(SddAiJob.id == job_id)
        .with_for_update()
        .first()
    )
    if not job:
        return
    if not preview_attempt_is_current(job, run_token, worker_boot_id):
        return
    update_preview_job_state(
        db,
        job,
        status=AiJobStatus.FAILED,
        progress=100,
        message=message,
        error=error,
        run_token=run_token,
        worker_boot_id=worker_boot_id,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# import preview 的三段
# ---------------------------------------------------------------------------


def load_requirement_import_context_sync(
    db: Session,
    *,
    job_id: str,
) -> Optional[Dict[str, Any]]:
    """恢复/执行前置查询：从 job.context_json 读取持久化的导入内容。"""
    job = load_preview_job_sync(db, job_id)
    if not job:
        return None
    context = job.context_json if isinstance(job.context_json, dict) else {}
    if str(context.get("job_kind") or "") != "REQUIREMENT_IMPORT_PREVIEW":
        return None
    markdown = str(context.get("normalized_markdown") or "").strip()
    if not markdown:
        raise WorkspaceAssetError(
            "Persisted import content is missing (job may have been created before a restart). Please re-upload the document.",
            status_code=422,
        )
    return {
        "markdown": markdown,
        "file_name": str(context.get("source_filename") or "requirements.md"),
        "source_kind": context.get("source_kind"),
        "source_uri": context.get("source_uri"),
        "source_ref": context.get("source_ref"),
        "source_ext": context.get("source_ext"),
        "source_mime": context.get("source_mime"),
        "render_json": context.get("render_json"),
    }


def prepare_requirement_import_sync(
    db: Session,
    *,
    job_id: str,
    markdown: str,
    source_kind: Optional[str],
    source_ref: Optional[str],
    source_uri: Optional[str],
    file_name: str,
    run_token: Optional[str] = None,
    worker_boot_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """import preview 准备段（线程内单事务）：状态推进 + prompt + backend。"""
    job = load_preview_job_sync(db, job_id)
    if not job:
        return None
    if not preview_attempt_is_current(job, run_token, worker_boot_id):
        raise WorkspaceAssetError("Requirement preview attempt is no longer current", status_code=409)
    update_preview_job_state(
        db, job, status=AiJobStatus.RUNNING, progress=8, message="Parsing requirement document",
        run_token=run_token, worker_boot_id=worker_boot_id,
    )
    project_path = workspace_project_path_or_error(db, job.workspace_id)
    prompt = build_requirement_preview_prompt(
        mode="import",
        markdown=markdown,
        source_kind=source_kind,
        source_ref=source_ref,
        source_uri=source_uri,
        file_name=file_name,
    )
    job.prompt_text = prompt
    update_preview_job_state(
        db, job, progress=28, message="Running agent CLI requirement preview",
        run_token=run_token, worker_boot_id=worker_boot_id,
    )
    backend_name = resolve_workspace_backend(db, job.workspace_id)
    return {
        "workspace_id": str(job.workspace_id),
        "creator_id": str(job.creator_id),
        "project_path": project_path,
        "prompt": prompt,
        "backend_name": backend_name,
    }


def finalize_requirement_import_sync(
    db: Session,
    *,
    job_id: str,
    file_name: str,
    markdown: str,
    source_kind: Optional[str],
    source_uri: Optional[str],
    source_ref: Optional[str],
    items: List[dict],
    metadata: dict,
    run_token: Optional[str] = None,
    worker_boot_id: Optional[str] = None,
    evidence: Optional[Any] = None,
) -> Dict[str, Any]:
    """import preview 收尾段（线程内单事务，doc §7.3.2）。

    正确顺序：先 ``FOR UPDATE`` 锁 job -> fence 校验 -> 创建 batch/items/
    audit -> 通过事务内 convergence 落业务终态。fence 失败抛出
    ``AttemptFencedError``，外层 ``run_db_txn`` 必须整体 rollback。
    """
    from app.domains.workspace_asset.models.workspace_asset import RequirementAuditAction

    job = (
        db.query(SddAiJob)
        .filter(SddAiJob.id == job_id)
        .with_for_update()
        .first()
    )
    if not job:
        raise WorkspaceAssetError("Requirement preview job not found", status_code=404)
    assert_preview_attempt_current(job, run_token, worker_boot_id)
    batch = create_requirement_preview_batch(
        db,
        workspace_id=job.workspace_id,
        actor_id=job.creator_id,
        file_name=file_name,
        markdown=markdown,
        source_kind=source_kind,
        source_uri=source_uri,
        source_ref=source_ref,
        source_metadata=metadata,
        items=items,
        audit_action=RequirementAuditAction.IMPORT_PREVIEW_CREATED,
    )
    update_preview_job_state(
        db,
        job,
        status=AiJobStatus.SUCCESS,
        progress=100,
        message="Requirement AI preview created",
        context_patch={"preview_batch_id": batch.id},
        result={"item_count": len(items), "batch_id": batch.id},
        run_token=run_token,
        worker_boot_id=worker_boot_id,
        evidence=evidence,
    )
    return {"batch_id": str(batch.id), "item_count": len(items)}


# ---------------------------------------------------------------------------
# split preview 的三段
# ---------------------------------------------------------------------------


def prepare_requirement_split_sync(
    db: Session,
    *,
    job_id: str,
    run_token: Optional[str] = None,
    worker_boot_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """split preview 准备段（线程内单事务）。"""
    job = load_preview_job_sync(db, job_id)
    if not job:
        return None
    if not preview_attempt_is_current(job, run_token, worker_boot_id):
        raise WorkspaceAssetError("Requirement preview attempt is no longer current", status_code=409)
    context = job.context_json if isinstance(job.context_json, dict) else {}
    requirement_id = str(context.get("requirement_id") or "").strip()
    requirement = get_requirement(db, job.workspace_id, requirement_id)
    if not requirement:
        raise WorkspaceAssetError("Requirement not found", status_code=404)
    content = (requirement.body or requirement.title or "").strip()
    if not content:
        raise WorkspaceAssetError("Requirement content is required for AI split preview.", status_code=422)
    project_path = workspace_project_path_or_error(db, job.workspace_id)
    update_preview_job_state(
        db, job, status=AiJobStatus.RUNNING, progress=16, message="Running Claude Code CLI split preview",
        run_token=run_token, worker_boot_id=worker_boot_id,
    )
    prompt = build_requirement_preview_prompt(
        mode="split",
        markdown=content,
        source_kind="split",
        source_ref=requirement.id,
        source_uri=requirement.source_uri,
        file_name=None,
    )
    job.prompt_text = prompt
    backend_name = resolve_workspace_backend(db, job.workspace_id)
    return {
        "requirement_id": str(requirement.id),
        "parent_source_metadata": requirement.source_metadata_json if isinstance(requirement.source_metadata_json, dict) else {},
        "requirement_source_uri": requirement.source_uri,
        "change_reason": context.get("change_reason"),
        "workspace_id": str(job.workspace_id),
        "creator_id": str(job.creator_id),
        "content": content,
        "project_path": project_path,
        "prompt": prompt,
        "backend_name": backend_name,
    }


def finalize_requirement_split_sync(
    db: Session,
    *,
    job_id: str,
    prepared: Dict[str, Any],
    items: List[dict],
    backend_name: Optional[str],
    session_id: Optional[str],
    run_token: Optional[str] = None,
    worker_boot_id: Optional[str] = None,
    evidence: Optional[Any] = None,
) -> Dict[str, Any]:
    """split preview 收尾段（线程内单事务，doc §7.3.2：先锁 job 再建副作用）。"""
    from app.domains.workspace_asset.models.workspace_asset import RequirementAuditAction

    job = (
        db.query(SddAiJob)
        .filter(SddAiJob.id == job_id)
        .with_for_update()
        .first()
    )
    if not job:
        raise WorkspaceAssetError("Requirement preview job not found", status_code=404)
    assert_preview_attempt_current(job, run_token, worker_boot_id)
    requirement = get_requirement(db, job.workspace_id, prepared["requirement_id"])
    if not requirement:
        raise WorkspaceAssetError("Requirement not found", status_code=404)
    metadata = {
        **prepared["parent_source_metadata"],
        "parent_requirement_id": prepared["requirement_id"],
        "ai_preview": True,
        "ai_job_id": job.id,
        "splitter": backend_name,
        "session_id": session_id,
    }
    for item in items:
        item["source_metadata"] = {
            **(item.get("source_metadata") or {}),
            "parent_requirement_id": prepared["requirement_id"],
        }
    batch = create_requirement_preview_batch(
        db,
        workspace_id=job.workspace_id,
        actor_id=job.creator_id,
        file_name=None,
        markdown=prepared["content"],
        source_kind="split",
        source_uri=prepared["requirement_source_uri"],
        source_ref=prepared["requirement_id"],
        source_metadata=metadata,
        items=items,
        audit_action=RequirementAuditAction.SPLIT_PREVIEW_CREATED,
        requirement_id=prepared["requirement_id"],
        reason=prepared["change_reason"],
    )
    update_preview_job_state(
        db,
        job,
        status=AiJobStatus.SUCCESS,
        progress=100,
        message="Requirement split preview created",
        context_patch={"preview_batch_id": batch.id},
        result={"item_count": len(items), "batch_id": batch.id},
        run_token=run_token,
        worker_boot_id=worker_boot_id,
        evidence=evidence,
    )
    return {"batch_id": str(batch.id), "item_count": len(items)}


# ---------------------------------------------------------------------------
# 事件循环侧 runner：attempt 证据解析 + 异常兜底
# ---------------------------------------------------------------------------


def _resolve_execution_kind(attempt) -> str:
    return str(getattr(attempt, "execution_kind", None) or "").strip() or "LOCAL_PROCESS"


def _resolve_evidence_or_none(execution_kind: str, exc: Exception):
    try:
        return resolve_attempt_evidence(
            execution_kind=execution_kind,
            runtime=current_agent_attempt_runtime(),
            typed_error=exc,
        )
    except Exception:
        logger.exception("Failed to resolve attempt evidence for preview failure")
        return None


def _prepare_attempt():
    """读取当前 attempt（事件循环线程专用）；DB 线程内不得调用。"""
    return current_agent_attempt()


def _attempt_run_token(attempt) -> Optional[str]:
    return attempt.run_token if attempt else None


def _attempt_boot_id(attempt) -> str:
    return str(attempt.worker_boot_id) if attempt else WORKER_BOOT_ID


async def run_requirement_import_preview_job(job_id: str, run_token: Optional[str] = None) -> bool:
    """三段式：准备段（DB 线程）→ CLI（零 session）→ 收尾段（DB 线程）。

    输入内容在作业创建时已解析并持久化到 job.context_json，
    服务重启后可由 recover_pending_queues 重新调度执行。

    返回 True 表示 CLI 产出了明确 result（provider outcome，doc §8.3）；
    evidence 在事件循环线程解析后显式传入 DB finalizer（doc §6.3）。
    """
    attempt = _prepare_attempt()
    run_token = run_token or _attempt_run_token(attempt)
    worker_boot_id = _attempt_boot_id(attempt)
    provider_outcome_seen = False
    # attempt-local 证据（doc 修复方案 §10.4）：只能在绑定 attempt runtime
    # 的事件循环 task 中解析；异常分支必须把已捕获证据显式传入 DB finalizer，
    # 绝不在 DB executor 线程重新读取 ContextVar。
    attempt_evidence: Optional[Any] = None
    resolved_execution_kind = _resolve_execution_kind(attempt)
    try:
        context = await run_db_txn(
            lambda db: load_requirement_import_context_sync(db, job_id=job_id)
        )
        if context is None:
            return False
        prepared = await run_db_txn(
            lambda db: prepare_requirement_import_sync(
                db,
                job_id=job_id,
                markdown=context["markdown"],
                source_kind=context["source_kind"],
                source_ref=context["source_ref"],
                source_uri=context["source_uri"],
                file_name=context["file_name"],
                run_token=run_token,
                worker_boot_id=worker_boot_id,
            )
        )
        if prepared is None:
            return False
        # CLI 调用期间不持有任何 DB session
        ai_result = await run_cli_single_turn(
            prepared["prompt"],
            prepared["project_path"],
            max_attempts=1,
            backend_name=prepared["backend_name"],
            **({"run_token": run_token} if run_token else {}),
        )
        # 证据必须在事件循环线程解析：DB executor 线程读取不到 attempt
        # ContextVar（doc §6.1）。provider 的终局结果对象必须在此处进入
        # evidence（doc 审计 P1-1）：远程会话已建立且 provider 正常返回时，
        # 收敛必须看到 provider_outcome_seen=True，否则业务 finalizer 先
        # 执行会被判 ORPHANED。
        attempt_evidence = resolve_attempt_evidence(
            execution_kind=resolved_execution_kind,
            runtime=current_agent_attempt_runtime(),
            provider_result=ai_result,
        )
        evidence = attempt_evidence
        # provider 终局结果对象非 None 即 outcome seen（正常结果/明确失败
        # 结果都算）；文本为空或解析失败仍走 FAILED，但绝不能被误认为
        # 远程仍在运行。
        provider_outcome_seen = ai_result is not None
        parsed_json = extract_json_object(str(ai_result.get("text") or ""))
        items = normalize_ai_preview_items(parsed_json)
        items = coalesce_simple_import_preview_items(
            markdown=context["markdown"],
            file_name=context["file_name"],
            items=items,
        )
        metadata = document_metadata(
            {
                "source_ext": context["source_ext"],
                "source_mime": context["source_mime"],
                "render_json": context["render_json"],
            },
            extra={
                "ai_preview": True,
                "ai_job_id": job_id,
                "splitter": "claude-code-cli",
                "session_id": ai_result.get("session_id"),
            },
        )
        await run_db_txn(
            lambda db: finalize_requirement_import_sync(
                db,
                job_id=job_id,
                file_name=context["file_name"],
                markdown=context["markdown"],
                source_kind=context["source_kind"],
                source_uri=context["source_uri"],
                source_ref=context["source_ref"],
                items=items,
                metadata=metadata,
                run_token=run_token,
                worker_boot_id=worker_boot_id,
                evidence=evidence,
            )
        )
        return provider_outcome_seen
    except Exception as exc:
        # 异常分支在事件循环线程补齐证据后显式传入 DB transaction；CLI 已
        # 确认退出的确定性解析失败必须落 FAILED，不得错误进入 ORPHANED
        # 重试（doc 修复方案 §10.2/§10.4）。
        if attempt_evidence is None:
            attempt_evidence = _resolve_evidence_or_none(resolved_execution_kind, exc)
        try:
            await run_db_txn(
                lambda db: fail_requirement_preview_sync(
                    db, job_id=job_id, message="Requirement AI preview failed", error=str(exc), run_token=run_token,
                    worker_boot_id=worker_boot_id,
                    evidence=attempt_evidence,
                )
            )
        except Exception:
            logger.exception("Failed to mark requirement import preview job failed")
        return provider_outcome_seen


async def run_requirement_split_preview_job(job_id: str, run_token: Optional[str] = None) -> bool:
    """三段式：准备段（DB 线程）→ CLI（零 session）→ 收尾段（DB 线程）。

    evidence 在事件循环线程解析后显式传入 DB finalizer（doc §6.3）。
    """
    attempt = _prepare_attempt()
    run_token = run_token or _attempt_run_token(attempt)
    worker_boot_id = _attempt_boot_id(attempt)
    provider_outcome_seen = False
    # attempt-local 证据（doc 修复方案 §10.4）：与 import preview 使用相同
    # helper，避免一条路径再次漏传。
    attempt_evidence: Optional[Any] = None
    resolved_execution_kind = _resolve_execution_kind(attempt)
    try:
        prepared = await run_db_txn(
            lambda db: prepare_requirement_split_sync(db, job_id=job_id, run_token=run_token, worker_boot_id=worker_boot_id)
        )
        if prepared is None:
            return False
        backend_name = prepared["backend_name"]
        # CLI 调用期间不持有任何 DB session
        ai_result = await run_cli_single_turn(
            prepared["prompt"],
            prepared["project_path"],
            max_attempts=1,
            backend_name=backend_name,
            **({"run_token": run_token} if run_token else {}),
        )
        # 证据必须在事件循环线程解析（doc §6.1）。provider 的终局结果对象
        # 必须在此处进入 evidence（doc 审计 P1-1）：远程会话已建立且
        # provider 正常返回时，收敛必须看到 provider_outcome_seen=True，
        # 否则业务 finalizer 先执行会被判 ORPHANED。
        attempt_evidence = resolve_attempt_evidence(
            execution_kind=resolved_execution_kind,
            runtime=current_agent_attempt_runtime(),
            provider_result=ai_result,
        )
        evidence = attempt_evidence
        provider_outcome_seen = ai_result is not None
        parsed_json = extract_json_object(str(ai_result.get("text") or ""))
        items = normalize_ai_preview_items(parsed_json)
        if len(items) <= 1:
            raise WorkspaceAssetError("AI split preview must produce at least two Requirement preview items.", status_code=422)
        await run_db_txn(
            lambda db: finalize_requirement_split_sync(
                db,
                job_id=job_id,
                prepared=prepared,
                items=items,
                backend_name=backend_name,
                session_id=ai_result.get("session_id"),
                run_token=run_token,
                worker_boot_id=worker_boot_id,
                evidence=evidence,
            )
        )
        return provider_outcome_seen
    except Exception as exc:
        # 异常分支在事件循环线程补齐证据后显式传入 DB transaction（doc
        # 修复方案 §10.4）：已确认退出的解析失败 → FAILED；死亡未证实的
        # 失败 → ORPHANED 保留 ownership。
        if attempt_evidence is None:
            attempt_evidence = _resolve_evidence_or_none(resolved_execution_kind, exc)
        try:
            await run_db_txn(
                lambda db: fail_requirement_preview_sync(
                    db, job_id=job_id, message="Requirement split preview failed", error=str(exc), run_token=run_token,
                    worker_boot_id=worker_boot_id,
                    evidence=attempt_evidence,
                )
            )
        except Exception:
            logger.exception("Failed to mark requirement split preview job failed")
        return provider_outcome_seen
