"""资产文档讨论线程的 AI 作业执行器。

三种作业类别共享同一条执行管线（准备上下文 → 构建 prompt → 单回合 CLI →
落库并广播）：

- ``THREAD_AI_REPLY``        讨论答疑，写回 AI 消息；
- ``RESOLUTION_PROPOSAL``    生成修改建议（resolution proposal）；
- ``RESOLUTION_REWRITE``     按建议改写锚点文本或整篇文档。

DB 段（准备/落库）经 ``run_db_txn`` 在线程内执行；CLI 调用期间不持有任何
session。所有业务写入都先做 attempt fence 校验。
"""

from __future__ import annotations

import os
from contextlib import ExitStack
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from app.agents import current_agent_attempt
from app.core.logging import bind_ai_context, bind_task_context, get_logger
from app.core.offload import run_db, run_db_txn
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.asset.models.asset import SddAssetResolutionProposal, SddAssetThread
from app.domains.asset.services import asset_discussion_service, asset_resolution_service
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.ai.services.jobs import provider_turn, state
from app.domains.ai.services.jobs.constants import (
    JOB_KIND_RESOLUTION_PROPOSAL,
    JOB_KIND_RESOLUTION_REWRITE,
    JOB_KIND_THREAD_AI_REPLY,
    as_status,
)
from app.domains.ai.services.jobs.registry import runtime
from app.domains.ai.services.jobs.fencing import (
    AgentAttemptFencedError,
    attempt_is_current_sync,
)
from app.domains.ai.services.jobs.store import (
    get_job_status,
    job_kind_from_job,
    job_prompt_text,
)
from app.domains.ai.services.jobs.executors.asset_prompts import (
    extract_block_text,
    normalize_relocated_anchor,
    parse_rewrite_payload,
    proposal_discussion_lines,
    proposal_source_message_ids,
    resolve_context_version,
    resolve_thread_anchor_text,
    serialize_proposal_for_ws,
    thread_history_lines,
)
from app.domains.task.services import task_cli_state_service
from app.domains.task.services.ai_context_service import (
    build_asset_thread_prompt,
    build_resolution_proposal_prompt,
    build_resolution_rewrite_prompt,
)

logger = get_logger(__name__, category="ai_session")


# ────────────────────────── 文本/锚点工具 ──────────────────────────


# ────────────────────────── DB 准备段 ──────────────────────────


def _prepare_asset_thread_context_sync(
    db: Session,
    job_id: str,
    run_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """asset thread job 上下文准备段 A（线程内执行，由 run_db_txn 包装）。

    只做读取与轻量状态推进，返回纯数据；CLI 前后的其余 DB 段各自独立事务。
    """
    job = (
        db.query(SddAiJob)
        .options(
            joinedload(SddAiJob.thread)
            .joinedload(SddAssetThread.task),
            joinedload(SddAiJob.thread).joinedload(SddAssetThread.asset),
        )
        .filter(SddAiJob.id == job_id)
        .first()
    )
    if not job or job.channel != AiJobChannel.ASSET_THREAD:
        return None
    if not attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
        raise AgentAttemptFencedError(f"Asset job attempt is no longer current: {job_id}")
    thread = job.thread
    if not thread:
        raise ValueError("Thread not found for AI job")
    job_kind = job_kind_from_job(job)
    task = thread.task
    if not thread.task_id or not task:
        raise ValueError("Thread task is required for AI job")

    bootstrap = task_cli_state_service.ensure_bootstrap_ready(
        db,
        workspace_id=thread.workspace_id,
        task_id=thread.task_id,
    )
    return {
        "job_id": str(job.id),
        "job_kind": job_kind,
        "run_token": run_token or str(job.run_token or "") or None,
        "creator_id": job.creator_id,
        "thread_id": thread.id,
        "asset_id": thread.asset_id,
        "task_id": thread.task_id,
        "workspace_id": thread.workspace_id,
        "task_name": str(task.name or ""),
        "task_project_path": str(task.project_path or ""),
        "document_name": thread.asset.name if thread.asset else "",
        "bootstrap_status": as_status(bootstrap.status),
        "bootstrap_version_id": bootstrap.spec_version_id,
        "context_json": job.context_json if isinstance(job.context_json, dict) else {},
    }


def _build_asset_thread_run_sync(
    db: Session,
    *,
    job_id: str,
    base: Dict[str, Any],
    session_plan,
) -> Dict[str, Any]:
    """asset thread job 准备段 B（线程内执行）：prompt 构建与执行参数解析。"""
    job_kind = base["job_kind"]
    thread = asset_discussion_service.get_thread(db, asset_id=base["asset_id"], thread_id=base["thread_id"])
    if not thread:
        raise ValueError("Thread not found for AI job")
    task = thread.task
    version = thread.version
    thread_backend = session_plan.backend
    resume_session_id = session_plan.session_id
    fork_first_turn = session_plan.fork_first_turn
    if not fork_first_turn:
        resume_session_id = (
            task_cli_state_service.get_latest_thread_session_id(db, thread.id)
            or resume_session_id
        )
    # 线程执行目录 = 任务目录（含 git worktree），评审答疑可直接读仓库内容
    from app.domains.task.services import task_service as task_service_module

    project_path = (
        task_service_module.resolve_task_cli_dir(db, task)
        if task
        else "."
    )
    if not os.path.isdir(project_path):
        project_path = (task.project_path if task and task.project_path else ".").strip() or "."
    if not os.path.isdir(project_path):
        project_path = "."
    thread_cwd = project_path

    run_state: Dict[str, Any] = {
        **base,
        "thread_backend": thread_backend,
        "resume_session_id": resume_session_id,
        "fork_first_turn": fork_first_turn,
        "thread_cwd": thread_cwd,
        "project_path": project_path,
    }

    if job_kind == JOB_KIND_RESOLUTION_PROPOSAL:
        context_json = base.get("context_json") or {}
        overwrite_existing_draft = bool(context_json.get("overwrite_existing_draft"))
        context_version = resolve_context_version(
            db,
            thread=thread,
            requested_version_id=str(context_json.get("context_version_id") or "").strip() or None,
        )
        anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
            db,
            thread=thread,
            context_version=context_version,
        )
        effective_anchor = anchor_eval.get("effective_anchor") if isinstance(anchor_eval, dict) else {}
        effective_block_id = str(
            (effective_anchor or {}).get("block_id")
            or thread.block_id
            or ""
        ).strip() or thread.block_id
        selected_block = (
            asset_discussion_service.get_block_by_id(context_version, effective_block_id)
            if context_version
            else None
        )
        if not selected_block and version:
            selected_block = asset_discussion_service.get_block_by_id(version, thread.block_id)
            effective_block_id = thread.block_id
            effective_anchor = {
                "block_id": thread.block_id,
                "selected_text": thread.selected_text,
                "char_start": thread.char_start,
                "char_end": thread.char_end,
            }
        anchor_meta = resolve_thread_anchor_text(
            thread,
            selected_block,
            selected_text=(effective_anchor or {}).get("selected_text"),
            char_start=(effective_anchor or {}).get("char_start"),
            char_end=(effective_anchor or {}).get("char_end"),
        )
        discussion_lines = proposal_discussion_lines(thread)
        source_message_ids = proposal_source_message_ids(thread)
        prompt = build_resolution_proposal_prompt(
            task_name=task.name if task else "",
            document_name=thread.asset.name if thread.asset else "",
            document_version_label=(f"v{context_version.version_no}" if context_version else "unknown"),
            block_id=effective_block_id or "",
            thread_id=thread.id or "",
            anchor_text=anchor_meta["anchor_text"],
            block_context_text=anchor_meta["block_text"],
            discussion_lines=discussion_lines,
        )
        run_state.update({
            "prompt": prompt,
            "overwrite_existing_draft": overwrite_existing_draft,
            "source_message_ids": source_message_ids,
            "effective_anchor": effective_anchor,
            "context_version_id": context_version.id if context_version else None,
            "anchor_text": anchor_meta["anchor_text"],
            "block_text": anchor_meta["block_text"],
            "discussion_lines_tail": discussion_lines[-12:],
        })
        return run_state

    if job_kind == JOB_KIND_RESOLUTION_REWRITE:
        context_json = base.get("context_json") or {}
        proposal_id = str(context_json.get("proposal_id") or "").strip()
        if not proposal_id:
            raise ValueError("proposal_id is required for rewrite job")

        proposal = (
            db.query(SddAssetResolutionProposal)
            .filter(
                SddAssetResolutionProposal.id == proposal_id,
                SddAssetResolutionProposal.thread_id == thread.id,
            )
            .first()
        )
        if not proposal:
            raise ValueError("Resolution proposal not found for rewrite")

        proposal_text = str(context_json.get("proposal_text") or "").strip()
        if not proposal_text:
            patch = proposal.proposed_patch_json if isinstance(proposal.proposed_patch_json, dict) else {}
            proposal_text = str(patch.get("proposal_text") or "").strip()
        if not proposal_text:
            raise ValueError("proposal_text is required for rewrite")
        requested_scope = str(context_json.get("rewrite_scope") or "").strip().lower()
        if requested_scope not in {"anchor", "document"}:
            requested_scope = "anchor"
        context_version = resolve_context_version(
            db,
            thread=thread,
            requested_version_id=str(context_json.get("context_version_id") or "").strip() or proposal.base_version_id,
        )
        anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
            db,
            thread=thread,
            context_version=context_version,
        )
        effective_anchor = anchor_eval.get("effective_anchor") if isinstance(anchor_eval, dict) else {}
        relocated_anchor = normalize_relocated_anchor(context_json.get("relocated_anchor"))
        if relocated_anchor:
            effective_anchor = relocated_anchor
        effective_block_id = str(
            (effective_anchor or {}).get("block_id")
            or thread.block_id
            or ""
        ).strip() or thread.block_id
        selected_block = (
            asset_discussion_service.get_block_by_id(context_version, effective_block_id)
            if context_version
            else None
        )
        if not selected_block:
            raise ValueError("Anchor block not found for rewrite context")
        anchor_meta = resolve_thread_anchor_text(
            thread,
            selected_block,
            selected_text=(effective_anchor or {}).get("selected_text"),
            char_start=(effective_anchor or {}).get("char_start"),
            char_end=(effective_anchor or {}).get("char_end"),
        )
        selection_mode = bool(anchor_meta["selected_text"])
        prompt = build_resolution_rewrite_prompt(
            task_name=task.name if task else "",
            document_name=thread.asset.name if thread.asset else "",
            document_version_label=(f"v{context_version.version_no}" if context_version else "unknown"),
            block_id=effective_block_id or "",
            thread_id=thread.id or "",
            anchor_text=anchor_meta["anchor_text"],
            block_context_text=anchor_meta["block_text"],
            proposal_text=proposal_text,
            rewrite_scope=requested_scope,
            selection_mode=selection_mode,
        )
        run_state.update({
            "prompt": prompt,
            "proposal_id": proposal_id,
            "proposal_text": proposal_text,
            "rewrite_scope": requested_scope,
            "selection_mode": selection_mode,
            "effective_anchor": effective_anchor,
            "context_version_id": context_version.id if context_version else None,
            "anchor_text": anchor_meta["anchor_text"],
            "block_text": anchor_meta["block_text"],
        })
        return run_state

    context = (
        asset_discussion_service.get_block_context(version, thread.block_id)
        if version else {"selected": None, "neighbors": []}
    )
    selected_block = context.get("selected") if isinstance(context, dict) else None
    neighbor_blocks = context.get("neighbors") if isinstance(context, dict) else []
    anchor_meta = resolve_thread_anchor_text(thread, selected_block)
    selected_text = anchor_meta["anchor_text"]
    anchor_block_text = anchor_meta["block_text"]
    neighbor_text = "\n".join(
        f"- {extract_block_text(item)}"
        for item in (neighbor_blocks or [])
        if extract_block_text(item)
    ).strip()
    history_lines = thread_history_lines(thread)
    prompt = build_asset_thread_prompt(
        task_name=task.name if task else "",
        document_name=thread.asset.name if thread.asset else "",
        document_version_label=(f"v{version.version_no}" if version else "unknown"),
        block_id=thread.block_id or "",
        thread_id=thread.id or "",
        project_path=project_path,
        selected_text=selected_text or (thread.selected_text or ""),
        anchor_block_text=anchor_block_text,
        neighbor_text=neighbor_text,
        history_lines=history_lines,
        manual_prompt=job_prompt_text(db, base["thread_id"]),
    )
    run_state.update({
        "prompt": prompt,
        "selected_text": selected_text,
        "anchor_block_text": anchor_block_text,
        "neighbor_text": neighbor_text,
        "history_lines": history_lines,
    })
    return run_state


# ────────────────────────── DB 落库段 ──────────────────────────


def _persist_asset_proposal_sync(
    db: Session,
    *,
    base: Dict[str, Any],
    proposal_text: str,
    run_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not attempt_is_current_sync(db, job_id=str(base.get("job_id") or ""), run_token=run_token):
        raise AgentAttemptFencedError("Asset proposal attempt is no longer current")
    thread = asset_discussion_service.get_thread(db, asset_id=base["asset_id"], thread_id=base["thread_id"])
    if not thread:
        raise ValueError("Thread disappeared during proposal generation")
    context_version = resolve_context_version(
        db,
        thread=thread,
        requested_version_id=base.get("context_version_id"),
    )
    proposal = asset_resolution_service.create_resolution_proposal(
        db,
        thread=thread,
        creator_id=base["creator_id"],
        proposed_text=proposal_text,
        overwrite_existing_draft=bool(base.get("overwrite_existing_draft")),
        source_message_ids=base.get("source_message_ids") or [],
        version=context_version,
        effective_anchor=base.get("effective_anchor") if isinstance(base.get("effective_anchor"), dict) else None,
    )
    db.commit()
    db.refresh(proposal)
    return {
        "proposal": serialize_proposal_for_ws(proposal),
        "proposal_id": str(proposal.id),
    }


def _persist_asset_rewrite_sync(
    db: Session,
    *,
    base: Dict[str, Any],
    proposal_text: str,
    rewritten_text: str,
    rewrite_scope: str,
    rewritten_markdown: str,
    selection_mode: bool,
    run_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not attempt_is_current_sync(db, job_id=str(base.get("job_id") or ""), run_token=run_token):
        raise AgentAttemptFencedError("Asset rewrite attempt is no longer current")
    thread = asset_discussion_service.get_thread(db, asset_id=base["asset_id"], thread_id=base["thread_id"])
    if not thread:
        raise ValueError("Thread disappeared during proposal rewrite")
    proposal = (
        db.query(SddAssetResolutionProposal)
        .filter(
            SddAssetResolutionProposal.id == base["proposal_id"],
            SddAssetResolutionProposal.thread_id == thread.id,
        )
        .first()
    )
    if not proposal:
        raise ValueError("Resolution proposal not found after rewrite")

    proposal = asset_resolution_service.update_resolution_proposal_rewrite(
        db,
        thread=thread,
        proposal=proposal,
        proposal_text=proposal_text,
        rewritten_text=rewritten_text,
        rewrite_scope=rewrite_scope,
        rewritten_markdown=rewritten_markdown or None,
        selection_mode=selection_mode,
        context_version_id=base.get("context_version_id"),
        relocated_anchor=base.get("effective_anchor") if isinstance(base.get("effective_anchor"), dict) else None,
    )
    db.commit()
    db.refresh(proposal)
    proposal_patch = proposal.proposed_patch_json if isinstance(proposal.proposed_patch_json, dict) else {}
    rewrite_ready = str(proposal_patch.get("rewrite_status") or "").strip().lower() == "ready"
    has_merged = bool(
        (isinstance(proposal_patch.get("merged_block_ast"), dict) and proposal_patch.get("merged_block_ast"))
        or (
            isinstance(proposal_patch.get("merged_blocks_ast"), list)
            and len(proposal_patch.get("merged_blocks_ast") or []) > 0
        )
    )
    if not rewrite_ready or not has_merged:
        raise ValueError(
            "Resolution rewrite persisted without merged AST payload"
        )
    return {
        "proposal": serialize_proposal_for_ws(proposal),
        "proposal_id": str(proposal.id),
    }


def _persist_asset_reply_sync(
    db: Session,
    *,
    base: Dict[str, Any],
    reply: str,
    thread_backend: Optional[str],
    job_id: str,
    run_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
        raise AgentAttemptFencedError("Asset reply attempt is no longer current")
    thread = asset_discussion_service.get_thread(db, asset_id=base["asset_id"], thread_id=base["thread_id"])
    if not thread:
        raise ValueError("Thread disappeared during AI execution")

    ai_message = asset_discussion_service.add_thread_message(
        db,
        thread=thread,
        role=AssetThreadMessageRole.AI,
        content=reply,
        creator_id=None,
        metadata_json={"provider": thread_backend or "claude-cli", "job_id": job_id},
    )
    db.commit()
    db.refresh(ai_message)
    return {
        "message": {
            "id": ai_message.id,
            "thread_id": ai_message.thread_id,
            "role": as_status(ai_message.role),
            "content": ai_message.content,
            "creator_id": ai_message.creator_id,
            "creator_display_name": None,
            "creator_avatar_svg": None,
            "metadata_json": ai_message.metadata_json,
            "created_at": ai_message.created_at.isoformat() if ai_message.created_at else None,
        },
        "message_id": str(ai_message.id),
    }


def _persist_asset_failure_message_sync(
    db: Session,
    *,
    job_id: str,
    error_text: str,
    run_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    failed_job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not failed_job or not failed_job.thread_id:
        return None
    if not attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
        return None
    thread = asset_discussion_service.get_thread(
        db, asset_id=failed_job.asset_id, thread_id=failed_job.thread_id
    )
    if not thread:
        return None
    failure_message = asset_discussion_service.add_thread_message(
        db,
        thread=thread,
        role=AssetThreadMessageRole.SYSTEM,
        content=f"AI 回复失败: {error_text}\n\n可重试：已自动采用超时重试策略，如仍失败请稍后再次触发。",
        creator_id=failed_job.creator_id,
        metadata_json={"error": error_text, "job_id": job_id},
    )
    db.commit()
    db.refresh(failure_message)
    return {
        "asset_id": thread.asset_id,
        "message": {
            "id": failure_message.id,
            "thread_id": failure_message.thread_id,
            "role": as_status(failure_message.role),
            "content": failure_message.content,
            "creator_id": failure_message.creator_id,
            "creator_display_name": None,
            "creator_avatar_svg": None,
            "metadata_json": failure_message.metadata_json,
            "created_at": failure_message.created_at.isoformat() if failure_message.created_at else None,
        },
    }


# ────────────────────────── 执行器 ──────────────────────────


async def execute_asset_thread_job(job_id: str) -> Optional[bool]:
    job_kind = JOB_KIND_THREAD_AI_REPLY
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    provider_seen = False
    try:
        base = await run_db_txn(
            lambda db: _prepare_asset_thread_context_sync(db, job_id, run_token)
        )
        if base is None:
            return None
        job_kind = base["job_kind"]
        with ExitStack() as context_stack:
            context_stack.enter_context(
                bind_task_context(
                    task_id=base["task_id"],
                    workspace_id=base["workspace_id"],
                    user_id=base["creator_id"],
                )
            )
            context_stack.enter_context(
                bind_ai_context(
                    job_id=job_id,
                    task_id=base["task_id"],
                    session_id=None,
                    event_type=job_kind,
                )
            )

            await state.update_job_state(job_id, progress=12, message="Building discussion context")

            await state.update_job_state(
                job_id,
                progress=18,
                message="Preparing isolated thread workspace",
                context_patch={
                    "bootstrap_status": base["bootstrap_status"],
                    "bootstrap_version_id": base["bootstrap_version_id"],
                    "job_kind": job_kind,
                },
            )
            # 线程专属会话：首次使用时从 baseline fork（各讨论上下文独立），
            # 之后一直用线程自己的会话；绝不直接 resume baseline 会话。
            session_plan = await task_cli_state_service.ensure_thread_session(
                base["thread_id"],
                require_ready=True,
            )
            # 准备段 B：prompt 构建 + 执行参数（线程内，无长持 session）
            run_state = await run_db_txn(
                lambda db: _build_asset_thread_run_sync(db, job_id=job_id, base=base, session_plan=session_plan)
            )
            thread_cwd = run_state["thread_cwd"]
            thread_backend = run_state["thread_backend"]
            resume_session_id = run_state["resume_session_id"]
            fork_first_turn = run_state["fork_first_turn"]
            prompt = run_state["prompt"]

            if job_kind == JOB_KIND_RESOLUTION_PROPOSAL:
                await state.update_job_state(
                    job_id,
                    progress=46,
                    message="Generating resolution proposal",
                    context_patch={
                        "thread_workspace": thread_cwd,
                        "discussion_lines": run_state["discussion_lines_tail"],
                        "anchor_text": run_state["anchor_text"],
                        "block_text": run_state["block_text"],
                        "context_version_id": run_state["context_version_id"],
                        "effective_anchor": run_state["effective_anchor"],
                    },
                )
                result = await provider_turn.run_cli_single_turn(
                    prompt,
                    thread_cwd,
                    session_id=resume_session_id,
                    should_cancel=lambda: runtime.is_cancel_requested(job_id),
                    backend_name=thread_backend,
                    fork_session=fork_first_turn,
                )
                provider_seen = bool(str(result.get("text") or "").strip())
                if fork_first_turn:
                    await task_cli_state_service.record_thread_session_id_async(
                        base["thread_id"], str(result.get("session_id") or "")
                    )
                proposal_text = str(result.get("text") or "").strip()
                final_session_id = str(result.get("session_id") or "").strip()
                if not proposal_text:
                    raise ValueError("Resolution proposal text is empty")

                persisted = await run_db_txn(
                    lambda db: _persist_asset_proposal_sync(
                        db,
                        base=run_state,
                        proposal_text=proposal_text,
                        run_token=run_token,
                    )
                )
                await asset_discussion_ws_manager.broadcast(
                    base["asset_id"],
                    {
                        "type": "proposal_created",
                        "asset_id": base["asset_id"],
                        "thread_id": base["thread_id"],
                        "proposal": persisted["proposal"],
                    },
                )
                await state.update_job_state(
                    job_id,
                    status=AiJobStatus.SUCCESS,
                    progress=100,
                    message="Resolution proposal generated",
                    result_patch={
                        "proposal_id": persisted["proposal_id"],
                        "proposal_excerpt": proposal_text[:1200],
                    },
                    session_id=final_session_id or None,
                    agent_backend=thread_backend,
                    finalize=True,
                    process_started=result.get("process_started"),
                    termination_confirmed_dead=result.get("termination_confirmed_dead"),
                )
                return provider_seen

            if job_kind == JOB_KIND_RESOLUTION_REWRITE:
                await state.update_job_state(
                    job_id,
                    progress=48,
                    message="Rewriting document from proposal",
                    context_patch={
                        "proposal_id": run_state["proposal_id"],
                        "thread_workspace": thread_cwd,
                        "rewrite_scope": run_state["rewrite_scope"],
                        "selection_mode": run_state["selection_mode"],
                        "anchor_text": run_state["anchor_text"],
                        "block_text": run_state["block_text"],
                        "context_version_id": run_state["context_version_id"],
                        "effective_anchor": run_state["effective_anchor"],
                    },
                )
                result = await provider_turn.run_cli_single_turn(
                    prompt,
                    thread_cwd,
                    session_id=resume_session_id,
                    should_cancel=lambda: runtime.is_cancel_requested(job_id),
                    backend_name=thread_backend,
                    fork_session=fork_first_turn,
                )
                provider_seen = provider_seen or bool(str(result.get("text") or "").strip())
                if fork_first_turn:
                    await task_cli_state_service.record_thread_session_id_async(
                        base["thread_id"], str(result.get("session_id") or "")
                    )
                rewrite_payload = parse_rewrite_payload(str(result.get("text") or ""))
                rewrite_scope = run_state["rewrite_scope"] or str(rewrite_payload.get("scope") or "anchor").strip().lower()
                rewritten_text = str(rewrite_payload.get("anchor_text") or "").strip()
                rewritten_markdown = str(rewrite_payload.get("document_markdown") or "").strip()
                final_session_id = str(result.get("session_id") or "").strip()
                if rewrite_scope == "document" and not rewritten_markdown:
                    raise ValueError("Rewritten document markdown is empty")
                if rewrite_scope != "document" and not rewritten_text:
                    raise ValueError("Rewritten block text is empty")

                persisted = await run_db_txn(
                    lambda db: _persist_asset_rewrite_sync(
                        db,
                        base=run_state,
                        proposal_text=run_state["proposal_text"],
                        rewritten_text=rewritten_text,
                        rewrite_scope=rewrite_scope,
                        rewritten_markdown=rewritten_markdown,
                        selection_mode=run_state["selection_mode"],
                        run_token=run_token,
                    )
                )
                await asset_discussion_ws_manager.broadcast(
                    base["asset_id"],
                    {
                        "type": "proposal_created",
                        "asset_id": base["asset_id"],
                        "thread_id": base["thread_id"],
                        "proposal": persisted["proposal"],
                    },
                )
                await state.update_job_state(
                    job_id,
                    status=AiJobStatus.SUCCESS,
                    progress=100,
                    message="Resolution proposal rewrite completed",
                    result_patch={
                        "proposal_id": persisted["proposal_id"],
                        "rewrite_excerpt": (rewritten_text or rewritten_markdown)[:1200],
                    },
                    session_id=final_session_id or None,
                    agent_backend=thread_backend,
                    finalize=True,
                    process_started=result.get("process_started"),
                    termination_confirmed_dead=result.get("termination_confirmed_dead"),
                )
                return provider_seen

            await state.update_job_state(job_id, progress=24, message="Preparing AI prompt")

            await state.update_job_state(
                job_id,
                progress=46,
                message="Calling AI engine",
                context_patch={
                    "selected_text": run_state["selected_text"] or "",
                    "anchor_block_text": run_state["anchor_block_text"],
                    "neighbor_text": run_state["neighbor_text"],
                    "history_lines": run_state["history_lines"][-10:],
                    "project_path": run_state["project_path"],
                    "thread_workspace": thread_cwd,
                },
            )

            result = await provider_turn.run_cli_single_turn(
                prompt,
                thread_cwd,
                session_id=resume_session_id,
                should_cancel=lambda: runtime.is_cancel_requested(job_id),
                backend_name=thread_backend,
                fork_session=fork_first_turn,
            )
            provider_seen = provider_seen or bool(str(result.get("text") or "").strip())
            if fork_first_turn:
                await task_cli_state_service.record_thread_session_id_async(
                    base["thread_id"], str(result.get("session_id") or "")
                )
            reply = str(result.get("text") or "").strip()
            final_session_id = str(result.get("session_id") or "").strip()

            persisted = await run_db_txn(
                lambda db: _persist_asset_reply_sync(
                    db,
                    base=run_state,
                    reply=reply,
                    thread_backend=thread_backend,
                    job_id=job_id,
                    run_token=run_token,
                )
            )
            await asset_discussion_ws_manager.broadcast(
                base["asset_id"],
                {
                    "type": "message_created",
                    "asset_id": base["asset_id"],
                    "thread_id": base["thread_id"],
                    "message": persisted["message"],
                },
            )
            await state.update_job_state(
                job_id,
                status=AiJobStatus.SUCCESS,
                progress=100,
                message="AI reply completed",
                result_patch={"message_id": persisted["message_id"]},
                session_id=final_session_id or None,
                agent_backend=thread_backend,
                finalize=True,
                process_started=result.get("process_started"),
                termination_confirmed_dead=result.get("termination_confirmed_dead"),
            )
            return provider_seen
    except AgentAttemptFencedError:
        logger.info("Discarded fenced asset attempt: job={}", job_id)
        return None
    except Exception as exc:
        status_after_error = await get_job_status(job_id)
        if runtime.is_cancel_requested(job_id) or status_after_error == AiJobStatus.CANCELLED:
            runtime.clear_cancel(job_id)
            return None
        logger.exception(f"Asset AI job failed: {exc}")
        failed_message = "Resolution proposal failed" if job_kind == JOB_KIND_RESOLUTION_PROPOSAL else "AI reply failed"
        # 失败也必须携带 attempt 级终止证据：已证明死亡的作业直接 FAILED 并
        # 清 ownership；未证明的转 ORPHANED。typed 异常作为无身份 fallback
        # 交给唯一 resolver（runtime 为权威）。
        await state.update_job_state(
            job_id,
            status=AiJobStatus.FAILED,
            progress=100,
            message=failed_message,
            error_message=str(exc),
            finalize=True,
            run_token=run_token,
            typed_error=exc,
        )
        if job_kind in {JOB_KIND_RESOLUTION_PROPOSAL, JOB_KIND_RESOLUTION_REWRITE}:
            return None
        try:
            failure_state = await run_db_txn(
                lambda db: _persist_asset_failure_message_sync(
                    db,
                    job_id=job_id,
                    error_text=str(exc),
                    run_token=run_token,
                )
            )
            if failure_state:
                await asset_discussion_ws_manager.broadcast(
                    failure_state["asset_id"],
                    {
                        "type": "message_created",
                        "asset_id": failure_state["asset_id"],
                        "thread_id": failure_state["thread_id"],
                        "message": failure_state["message"],
                    },
                )
        except Exception as msg_exc:
            logger.warning(f"Failed to append asset AI failure message: {msg_exc}")
        return None
