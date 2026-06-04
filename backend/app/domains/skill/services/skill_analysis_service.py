"""Static Skill package analysis service."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.engine.claude_bridge import create_cli_bridge
from app.domains.skill.models.skill import (
    SddSkill,
    SddSkillAnalysis,
    SddSkillVersion,
    SkillAnalysisRefKind,
    SkillAnalysisStatus,
    SkillRiskLevel,
)
from app.domains.auth.models.user import User
from app.domains.skill.services import skill_service
from app.domains.skill.services.skill import git_service, storage_service


LARGE_FILE_BYTES = 1024 * 1024
SEMANTIC_TIMEOUT_SECONDS = 240

MARKDOWN_EXTS = {".md", ".mdx"}
SCRIPT_EXTS = {".py", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".js", ".ts", ".mjs", ".cjs"}
CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env"}
CONFIG_NAMES = {"package.json", "requirements.txt", "pyproject.toml", "poetry.lock", "pnpm-lock.yaml", "yarn.lock"}

RISK_DETAIL_TEMPLATES: Dict[str, Dict[str, str]] = {
    "SHELL_COMMAND": {
        "label": "命令执行",
        "description": "该位置出现 shell、subprocess、exec 或 eval 类调用，可能在用户工作区执行本地命令。",
        "recommendation": "确认命令参数来源、路径边界和失败处理，避免未经确认执行任意命令或脚本。",
    },
    "FILE_DELETE": {
        "label": "文件删除",
        "description": "该位置出现删除、递归移除或 unlink 类操作，可能影响 Skill 包外文件或用户工作区内容。",
        "recommendation": "检查是否限制在预期目录内，避免 rm -rf、rmtree、Remove-Item 等操作越权删除。",
    },
    "DANGEROUS_GIT": {
        "label": "危险 Git 操作",
        "description": "该位置出现 git reset、push 或 checkout 等操作，可能改写工作区状态或向远端推送内容。",
        "recommendation": "确认该操作是否需要用户显式确认，并检查是否会覆盖未保存改动或推送敏感内容。",
    },
    "NETWORK_ACCESS": {
        "label": "网络访问",
        "description": "该位置出现 curl、wget、requests、fetch 或类似网络访问，可能下载或上传外部数据。",
        "recommendation": "确认目标地址、传输内容、认证信息处理和离线失败降级行为。",
    },
    "SECRET_ACCESS": {
        "label": "敏感信息访问",
        "description": "该位置出现 .env、token、secret、api key 或 password 等敏感信息访问线索。",
        "recommendation": "确认是否读取或暴露了凭据，避免将 token、secret、key 写入日志、提示词或外部请求。",
    },
    "PACKAGE_SCRIPT": {
        "label": "package.json 脚本",
        "description": "package.json 中定义了 scripts，安装或运行时可能触发额外命令。",
        "recommendation": "审阅 scripts 中的 install、postinstall、build、test 等命令，确认不会执行危险操作。",
    },
    "BINARY_FILE": {
        "label": "二进制文件",
        "description": "Skill 包内包含二进制文件，无法通过文本审阅直接确认其内容和行为。",
        "recommendation": "确认二进制来源、用途和大小，必要时要求替换为可审阅源码或明确校验信息。",
    },
    "LARGE_FILE": {
        "label": "大文件",
        "description": "Skill 包内包含大文件，可能隐藏大量内容或影响导入、审阅和运行性能。",
        "recommendation": "确认大文件是否必要，是否可拆分、压缩或迁移到外部受控资源。",
    },
    "SEMANTIC_RISK": {
        "label": "语义风险",
        "description": "Claude 语义审阅识别出需要人工确认的潜在风险。",
        "recommendation": "结合证据详情和文件上下文复核该行为是否符合 Skill 预期。",
    },
}


SEMANTIC_UNAVAILABLE_MESSAGE = (
    "静态包摘要已完成；Claude AI 语义风险审阅未返回可用结果，"
    "暂不展示需要语义确认的风险项。"
)

SEMANTIC_CONTRACT_FAILED_MESSAGE = "Claude AI 语义审阅输出不完整，未能生成可定位的具体风险项。"


class SemanticAnalysisContractError(ValueError):
    """Raised when Claude returns an internally inconsistent semantic result."""


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def is_semantic_degraded_analysis(analysis: SddSkillAnalysis) -> bool:
    status = _enum_value(analysis.status).upper()
    if status != SkillAnalysisStatus.FAILED.value:
        return False
    if not analysis.file_stats_json:
        return False
    message = str(analysis.message or "").lower()
    error = str(analysis.error_message or "").lower()
    return "semantic review" in message or "claude" in error


def serialize_analysis(analysis: SddSkillAnalysis) -> Dict[str, Any]:
    semantic_degraded = is_semantic_degraded_analysis(analysis)
    risk_level = _enum_value(analysis.risk_level) or None
    risk_items = _dedupe_risks(analysis.risk_items_json or [])
    semantic_contract_failed = (
        _enum_value(analysis.status).upper() == SkillAnalysisStatus.SUCCESS.value
        and _normalize_level(risk_level, "LOW") in {"MEDIUM", "HIGH"}
        and not risk_items
    )
    return {
        "id": analysis.id,
        "workspace_id": analysis.workspace_id,
        "skill_id": analysis.skill_id,
        "version_id": analysis.version_id,
        "commit_sha": analysis.commit_sha,
        "ref_kind": _enum_value(analysis.ref_kind),
        "status": (
            SkillAnalysisStatus.FAILED.value
            if semantic_contract_failed
            else SkillAnalysisStatus.SUCCESS.value if semantic_degraded else _enum_value(analysis.status)
        ),
        "progress": int(analysis.progress or 0),
        "message": (
            SEMANTIC_CONTRACT_FAILED_MESSAGE
            if semantic_contract_failed
            else SEMANTIC_UNAVAILABLE_MESSAGE if semantic_degraded else analysis.message
        ),
        "error_message": (
            f"Claude returned risk_level={risk_level} but no concrete risk_items; re-run Analysis."
            if semantic_contract_failed
            else None if semantic_degraded else analysis.error_message
        ),
        "risk_level": risk_level,
        "complexity": _enum_value(analysis.complexity) or None,
        "review_priority": _enum_value(analysis.review_priority) or None,
        "file_stats": analysis.file_stats_json or {},
        "file_type_distribution": analysis.file_type_distribution_json or {},
        "key_files": analysis.key_files_json or [],
        "risk_items": risk_items,
        "review_suggestions": analysis.review_suggestions_json or [],
        "created_by_id": analysis.created_by_id,
        "started_at": analysis.started_at,
        "finished_at": analysis.finished_at,
        "created_at": analysis.created_at,
        "updated_at": analysis.updated_at,
    }


def get_analysis(db: Session, *, workspace_id: str, skill_id: str, analysis_id: str) -> Optional[SddSkillAnalysis]:
    return (
        db.query(SddSkillAnalysis)
        .filter(
            SddSkillAnalysis.workspace_id == workspace_id,
            SddSkillAnalysis.skill_id == skill_id,
            SddSkillAnalysis.id == analysis_id,
        )
        .first()
    )


def get_latest_analysis(
    db: Session,
    *,
    workspace_id: str,
    skill_id: str,
    ref_kind: Optional[SkillAnalysisRefKind] = None,
    version_id: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> Optional[SddSkillAnalysis]:
    query = db.query(SddSkillAnalysis).filter(
        SddSkillAnalysis.workspace_id == workspace_id,
        SddSkillAnalysis.skill_id == skill_id,
    )

    if version_id:
        query = query.filter(SddSkillAnalysis.version_id == version_id)
        if commit_sha:
            query = query.filter(SddSkillAnalysis.commit_sha == commit_sha)
    elif ref_kind == SkillAnalysisRefKind.WORKTREE:
        query = query.filter(
            SddSkillAnalysis.ref_kind == SkillAnalysisRefKind.WORKTREE,
            SddSkillAnalysis.version_id.is_(None),
        )
    elif commit_sha:
        query = query.filter(SddSkillAnalysis.commit_sha == commit_sha)

    return query.order_by(SddSkillAnalysis.created_at.desc(), SddSkillAnalysis.id.desc()).first()


def get_latest_analysis_for_ref(
    db: Session,
    *,
    workspace_id: str,
    skill: SddSkill,
    ref_kind: str,
    version_id: Optional[str] = None,
) -> Optional[SddSkillAnalysis]:
    resolved_kind, version, commit_sha = _resolve_ref(db, skill, ref_kind=ref_kind, version_id=version_id)
    return get_latest_analysis(
        db,
        workspace_id=workspace_id,
        skill_id=skill.id,
        ref_kind=resolved_kind,
        version_id=version.id if version else None,
        commit_sha=commit_sha,
    )


def _resolve_ref(
    db: Session,
    skill: SddSkill,
    *,
    ref_kind: str,
    version_id: Optional[str],
) -> Tuple[SkillAnalysisRefKind, Optional[SddSkillVersion], Optional[str]]:
    normalized = str(ref_kind or SkillAnalysisRefKind.WORKTREE.value).strip().upper()
    if normalized not in {item.value for item in SkillAnalysisRefKind}:
        raise ValueError("Invalid analysis ref_kind")
    kind = SkillAnalysisRefKind(normalized)

    if kind == SkillAnalysisRefKind.VERSION:
        if not version_id:
            raise ValueError("version_id is required for VERSION analysis")
        version = skill_service.get_skill_version(db, skill.id, version_id)
        if not version:
            raise ValueError("Skill version not found")
        return kind, version, version.commit_sha

    if kind == SkillAnalysisRefKind.LATEST:
        version = skill_service.get_latest_skill_version(db, skill.id)
        if not version:
            return SkillAnalysisRefKind.WORKTREE, None, None
        return kind, version, version.commit_sha

    return SkillAnalysisRefKind.WORKTREE, None, None


def create_analysis_job(
    db: Session,
    *,
    user: User,
    skill: SddSkill,
    workspace_id: str,
    ref_kind: str,
    version_id: Optional[str] = None,
) -> SddSkillAnalysis:
    resolved_kind, version, commit_sha = _resolve_ref(db, skill, ref_kind=ref_kind, version_id=version_id)
    analysis = SddSkillAnalysis(
        workspace_id=workspace_id,
        skill_id=skill.id,
        version_id=version.id if version else None,
        commit_sha=commit_sha,
        ref_kind=resolved_kind,
        status=SkillAnalysisStatus.PENDING,
        progress=0,
        message="Skill analysis queued",
        created_by_id=user.id,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def retry_analysis_job(db: Session, *, source: SddSkillAnalysis, user_id: str) -> SddSkillAnalysis:
    analysis = SddSkillAnalysis(
        workspace_id=source.workspace_id,
        skill_id=source.skill_id,
        version_id=source.version_id,
        commit_sha=source.commit_sha,
        ref_kind=source.ref_kind,
        status=SkillAnalysisStatus.PENDING,
        progress=0,
        message="Skill analysis retry queued",
        created_by_id=user_id,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def schedule_analysis_job(analysis_id: str) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(asyncio.to_thread(run_analysis_job, analysis_id))
    except RuntimeError:
        thread = threading.Thread(target=run_analysis_job, args=(analysis_id,), daemon=True)
        thread.start()


def _set_analysis_state(
    db: Session,
    analysis: SddSkillAnalysis,
    *,
    status: Optional[SkillAnalysisStatus] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    error_message: Optional[str] = None,
    started: bool = False,
    finished: bool = False,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    if status is not None:
        analysis.status = status
    if progress is not None:
        analysis.progress = max(0, min(100, int(progress)))
    if message is not None:
        analysis.message = message
    if error_message is not None:
        analysis.error_message = error_message
    if started:
        analysis.started_at = datetime.utcnow()
    if finished:
        analysis.finished_at = datetime.utcnow()
    if payload is not None:
        analysis.risk_level = SkillRiskLevel(payload["risk_level"]) if payload.get("risk_level") else None
        analysis.complexity = SkillRiskLevel(payload["complexity"]) if payload.get("complexity") else None
        analysis.review_priority = SkillRiskLevel(payload["review_priority"]) if payload.get("review_priority") else None
        analysis.file_stats_json = payload.get("file_stats") or {}
        analysis.file_type_distribution_json = payload.get("file_type_distribution") or {}
        analysis.key_files_json = payload.get("key_files") or []
        analysis.risk_items_json = payload.get("risk_items") or []
        analysis.review_suggestions_json = payload.get("review_suggestions") or []
    db.commit()
    db.refresh(analysis)


def _safe_rel(path: str) -> str:
    return storage_service.normalize_path(path).strip("/")


def _is_internal_path(rel_path: str) -> bool:
    normalized = _safe_rel(rel_path)
    first = normalized.split("/", 1)[0]
    return first in {".git", ".sdd-internal"}


def _copy_worktree_snapshot(skill: SddSkill, target_root: str) -> None:
    source_root = storage_service.package_abs_path(skill)
    for walk_root, dir_names, file_names in os.walk(source_root):
        dir_names[:] = [name for name in dir_names if name not in {".git", ".sdd-internal"}]
        rel_walk = os.path.relpath(walk_root, source_root)
        rel_prefix = "" if rel_walk in {"", "."} else storage_service.normalize_path(rel_walk)
        for file_name in file_names:
            rel_path = _safe_rel(os.path.join(rel_prefix, file_name)) if rel_prefix else file_name
            if _is_internal_path(rel_path):
                continue
            src = os.path.join(walk_root, file_name)
            if os.path.islink(src):
                continue
            dst = os.path.abspath(os.path.join(target_root, rel_path))
            if os.path.commonpath([os.path.abspath(target_root), dst]) != os.path.abspath(target_root):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


def _copy_commit_snapshot(skill: SddSkill, commit_sha: str, target_root: str) -> None:
    repo_path = storage_service.package_abs_path(skill)
    for rel_path in git_service.list_files_at_ref(repo_path, commit_sha):
        if _is_internal_path(rel_path):
            continue
        payload = git_service.read_file_at_ref(repo_path, commit_sha, rel_path)
        dst = os.path.abspath(os.path.join(target_root, rel_path))
        if os.path.commonpath([os.path.abspath(target_root), dst]) != os.path.abspath(target_root):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as file:
            file.write(payload)


def _make_snapshot(skill: SddSkill, analysis: SddSkillAnalysis) -> str:
    tmp_root = tempfile.mkdtemp(prefix="sdd-skill-analysis-")
    package_root = os.path.join(tmp_root, "package")
    os.makedirs(package_root, exist_ok=True)
    if analysis.commit_sha:
        _copy_commit_snapshot(skill, analysis.commit_sha, package_root)
    else:
        _copy_worktree_snapshot(skill, package_root)
    return tmp_root


def _read_file_bytes(path: str) -> bytes:
    with open(path, "rb") as file:
        return file.read()


def _role_for_path(rel_path: str, is_binary: bool) -> Optional[str]:
    lower = rel_path.lower()
    name = os.path.basename(lower)
    if lower == "skill.md":
        return "ENTRY"
    if name == "readme.md":
        return "README"
    if lower == "workflow.md" or lower.startswith("workflows/"):
        return "WORKFLOW"
    if lower.startswith("scripts/"):
        return "SCRIPT"
    if lower.startswith("tools/"):
        return "TOOL"
    if lower.startswith("templates/"):
        return "TEMPLATE"
    if lower.startswith("rules/"):
        return "RULE"
    if name in CONFIG_NAMES:
        return "CONFIG"
    if os.path.splitext(lower)[1] in SCRIPT_EXTS:
        return "SCRIPT"
    if os.path.splitext(lower)[1] in CONFIG_EXTS:
        return "CONFIG"
    if is_binary:
        return "BINARY"
    return None


def _risk_for_key_file(role: str, rel_path: str, is_large: bool) -> str:
    if role in {"SCRIPT", "TOOL"}:
        return "MEDIUM"
    if role == "BINARY" or is_large:
        return "MEDIUM"
    if os.path.basename(rel_path).lower() == "package.json":
        return "MEDIUM"
    return "LOW"


def _truncate_text(value: Any, limit: int, *, collapse: bool = True) -> str:
    text = str(value or "").strip()
    if collapse:
        text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _risk_location(file_path: str, line_start: Optional[int] = None, line_end: Optional[int] = None) -> str:
    if line_start and line_end and line_end != line_start:
        return f"{file_path}:{line_start}-{line_end}"
    if line_start:
        return f"{file_path}:{line_start}"
    return file_path


def _risk_id(item: Dict[str, Any]) -> str:
    basis = "|".join(
        [
            str(item.get("risk_type") or ""),
            str(item.get("file_path") or ""),
            str(item.get("line_start") or ""),
            str(item.get("line_end") or ""),
            str(item.get("source") or ""),
            str(item.get("matched_text") or item.get("evidence") or item.get("evidence_summary") or ""),
        ]
    )
    return hashlib.sha1(basis.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _risk_template(risk_type: str) -> Dict[str, str]:
    return RISK_DETAIL_TEMPLATES.get(risk_type, RISK_DETAIL_TEMPLATES["SEMANTIC_RISK"])


def _build_risk_item(
    *,
    risk_type: str,
    risk_level: str,
    file_path: str,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
    evidence_summary: Optional[str] = None,
    matched_text: Optional[str] = None,
    evidence_detail: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    recommendation: Optional[str] = None,
    source: str = "static-rule",
    confidence: float = 0.78,
) -> Dict[str, Any]:
    normalized_type = str(risk_type or "SEMANTIC_RISK").strip().upper() or "SEMANTIC_RISK"
    normalized_path = _safe_rel(file_path)
    normalized_line_start = _safe_int(line_start)
    normalized_line_end = _safe_int(line_end)
    template = _risk_template(normalized_type)
    location = _risk_location(normalized_path, normalized_line_start, normalized_line_end)
    matched = _truncate_text(matched_text, 500)
    summary = _truncate_text(
        evidence_summary
        or (f"{location} 命中 {template['label']} 线索：{matched}" if matched else f"{location} 命中 {template['label']} 风险"),
        500,
    )
    item = {
        "risk_type": normalized_type,
        "risk_level": _normalize_level(risk_level, "MEDIUM"),
        "file_path": normalized_path,
        "line_start": normalized_line_start,
        "line_end": normalized_line_end,
        "title": _truncate_text(title or f"{location} 出现{template['label']}风险", 220),
        "description": _truncate_text(description or template["description"], 1000),
        "evidence_summary": summary,
        "evidence_detail": _truncate_text(
            evidence_detail
            or (f"位置：{location}\n命中内容：{matched}" if matched else f"位置：{location}\n{summary}"),
            2000,
            collapse=False,
        ),
        "matched_text": matched,
        "recommendation": _truncate_text(recommendation or template["recommendation"], 1000),
        "evidence": matched,
        "source": str(source or "static-rule"),
        "confidence": _safe_float(confidence, 0.78),
    }
    item["id"] = _risk_id(item)
    return item


def deterministic_scan(package_root: str, skill: SddSkill) -> Dict[str, Any]:
    file_type_counter: Counter[str] = Counter()
    key_files: List[Dict[str, Any]] = []
    risk_items: List[Dict[str, Any]] = []
    total_files = 0
    markdown_files = 0
    script_files = 0
    config_files = 0
    binary_files = 0
    large_files = 0
    dir_count = 0

    for walk_root, dir_names, file_names in os.walk(package_root):
        dir_names[:] = [name for name in dir_names if name not in {".git", ".sdd-internal"}]
        for dir_name in dir_names:
            rel_dir = _safe_rel(os.path.relpath(os.path.join(walk_root, dir_name), package_root))
            if rel_dir:
                dir_count += 1
        for file_name in file_names:
            abs_file = os.path.join(walk_root, file_name)
            if os.path.islink(abs_file):
                continue
            rel_path = _safe_rel(os.path.relpath(abs_file, package_root))
            if _is_internal_path(rel_path):
                continue
            total_files += 1
            ext = os.path.splitext(rel_path)[1].lower() or "(none)"
            file_type_counter[ext] += 1
            payload = _read_file_bytes(abs_file)
            size = len(payload)
            is_binary = storage_service.is_binary_bytes(payload)
            is_large = size >= LARGE_FILE_BYTES
            lower_name = os.path.basename(rel_path).lower()
            if ext in MARKDOWN_EXTS:
                markdown_files += 1
            if ext in SCRIPT_EXTS:
                script_files += 1
            if ext in CONFIG_EXTS or lower_name in CONFIG_NAMES:
                config_files += 1
            if is_binary:
                binary_files += 1
            if is_large:
                large_files += 1
            role = _role_for_path(rel_path, is_binary)
            if role:
                key_files.append(
                    {
                        "path": rel_path,
                        "role": role,
                        "risk_level": _risk_for_key_file(role, rel_path, is_large),
                        "size": size,
                        "is_binary": is_binary,
                    }
                )
            if is_binary:
                continue

    stats = {
        "skill_name": skill.name,
        "description": skill.description,
        "entry_file_path": skill.entry_file_path,
        "manifest_path": skill.manifest_path,
        "package_path": skill.package_path,
        "source_type": skill.source_type,
        "source_repo_url": skill.source_repo_url,
        "source_skill_name": skill.source_skill_name,
        "source_subdir": skill.source_subdir,
        "source_commit_sha": skill.source_commit_sha,
        "source_locked": bool(skill.source_locked),
        "latest_version_no": int(skill.latest_version_no or 0),
        "head_commit_sha": skill.head_commit_sha,
        "total_files": total_files,
        "markdown_files": markdown_files,
        "script_files": script_files,
        "config_files": config_files,
        "binary_files": binary_files,
        "large_files": large_files,
        "directories": dir_count,
    }
    suggestions = _build_review_suggestions(stats, risk_items, key_files)
    levels = _derive_levels(stats, risk_items)
    return {
        **levels,
        "file_stats": stats,
        "file_type_distribution": dict(sorted(file_type_counter.items(), key=lambda item: item[0])),
        "key_files": sorted(key_files, key=lambda item: str(item.get("path") or "").lower()),
        "risk_items": _dedupe_risks(risk_items),
        "review_suggestions": suggestions,
    }


def _normalize_risk_item(item: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        item = {}
    normalized = _build_risk_item(
        risk_type=str(item.get("risk_type") or "SEMANTIC_RISK"),
        risk_level=_normalize_level(item.get("risk_level"), "MEDIUM"),
        file_path=str(item.get("file_path") or ""),
        line_start=_safe_int(item.get("line_start")),
        line_end=_safe_int(item.get("line_end")),
        title=str(item.get("title") or "").strip() or None,
        description=str(item.get("description") or "").strip() or None,
        evidence_summary=str(item.get("evidence_summary") or "").strip() or None,
        evidence_detail=str(item.get("evidence_detail") or "").strip() or None,
        matched_text=str(item.get("matched_text") or item.get("evidence") or "").strip() or None,
        recommendation=str(item.get("recommendation") or "").strip() or None,
        source=str(item.get("source") or "static-rule"),
        confidence=_safe_float(item.get("confidence"), 0.78),
    )
    if str(item.get("id") or "").strip():
        normalized["id"] = str(item.get("id")).strip()
    return normalized


def _dedupe_risks(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[tuple[str, str, int, int, str]] = set()
    result: List[Dict[str, Any]] = []
    for item in items:
        normalized = _normalize_risk_item(item)
        key = (
            str(normalized.get("risk_type") or ""),
            str(normalized.get("file_path") or ""),
            int(normalized.get("line_start") or 0),
            int(normalized.get("line_end") or 0),
            str(normalized.get("source") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result[:300]


def _has_valid_semantic_risk_item(semantic: Dict[str, Any]) -> bool:
    for item in semantic.get("risk_items") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("file_path") or "").replace("\\", "/").strip("/"):
            return True
    return False


def _semantic_contract_error(semantic: Dict[str, Any]) -> Optional[str]:
    semantic_level = _normalize_level(semantic.get("risk_level"), "LOW")
    if semantic_level in {"MEDIUM", "HIGH"} and not _has_valid_semantic_risk_item(semantic):
        return (
            f"Claude returned risk_level={semantic_level} but did not return any valid file-level risk_items. "
            "A MEDIUM/HIGH semantic result must include at least one risk item with file_path and evidence_detail."
        )
    return None


def _derive_levels(stats: Dict[str, Any], risk_items: List[Dict[str, Any]]) -> Dict[str, str]:
    high_count = sum(1 for item in risk_items if str(item.get("risk_level")) == "HIGH")
    medium_count = sum(1 for item in risk_items if str(item.get("risk_level")) == "MEDIUM")
    script_count = int(stats.get("script_files") or 0)
    total_files = int(stats.get("total_files") or 0)
    if high_count > 0:
        risk_level = "HIGH"
    elif medium_count > 0:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    if total_files >= 80 or script_count >= 12:
        complexity = "HIGH"
    elif total_files >= 20 or script_count >= 3:
        complexity = "MEDIUM"
    else:
        complexity = "LOW"

    if risk_level == "HIGH" or complexity == "HIGH":
        review_priority = "HIGH"
    elif risk_level == "MEDIUM" or complexity == "MEDIUM":
        review_priority = "MEDIUM"
    else:
        review_priority = "LOW"
    return {"risk_level": risk_level, "complexity": complexity, "review_priority": review_priority}


def _build_review_suggestions(
    stats: Dict[str, Any],
    risk_items: List[Dict[str, Any]],
    key_files: List[Dict[str, Any]],
) -> List[str]:
    suggestions = [
        "检查 SKILL.md 的触发说明是否过宽",
        "确认 runtime skill 是否允许被临时修改",
    ]
    if int(stats.get("script_files") or 0) > 0:
        suggestions.append("优先审阅脚本文件和 tools/、scripts/ 目录")
    if any(str(item.get("risk_type") or "") == "SHELL_COMMAND" for item in risk_items):
        suggestions.append("优先审阅包含 shell 命令或 subprocess 调用的文件")
    if any(str(item.get("risk_type") or "") == "FILE_DELETE" for item in risk_items):
        suggestions.append("检查是否存在路径越权写入、删除或递归移除")
    if any(str(item.get("risk_type") or "") == "SECRET_ACCESS" for item in risk_items):
        suggestions.append("检查是否访问 .env、secret、token 或 key")
    if any(str(item.get("risk_type") or "") == "NETWORK_ACCESS" for item in risk_items):
        suggestions.append("检查是否存在网络请求及外部下载行为")
    if any(str(item.get("risk_type") or "") == "DANGEROUS_GIT" for item in risk_items):
        suggestions.append("检查是否包含 git reset、push、checkout 等危险 git 操作")
    if any(str(item.get("role") or "") == "CONFIG" and os.path.basename(str(item.get("path") or "")).lower() == "package.json" for item in key_files):
        suggestions.append("检查 package.json scripts 是否会执行危险命令")
    return list(dict.fromkeys(suggestions))


def _semantic_prompt() -> str:
    return (
        "You are auditing a Claude Skill package in the current directory. "
        "Inspect this directory recursively as the package root. Do not rely on any precomputed static scan summary, "
        "keyword hint list, dependency graph, or file excerpt bundle; make your own review from the files you open. "
        "You may list, glob, grep, and read files under the current directory. "
        "Do not execute scripts, do not run package manager commands, do not use shell commands, do not modify files, "
        "and do not infer hidden runtime behavior that is not evidenced by the package content. "
        "Do not report a risk solely because a keyword appears in comments, documentation, examples, quoted text, "
        "or non-executed instructions. Only output risk_items when the package behavior, scripts, config, or Skill "
        "instructions create an actionable reviewer concern. For binary or large files, decide from filename, role, "
        "size if visible, references, and surrounding package context whether they are worth review; omit them when "
        "they are ordinary assets. "
        "Return JSON only with this shape: "
        "{\"risk_level\":\"LOW|MEDIUM|HIGH\",\"complexity\":\"LOW|MEDIUM|HIGH\","
        "\"review_priority\":\"LOW|MEDIUM|HIGH\",\"risk_items\":[{\"risk_type\":\"string\","
        "\"risk_level\":\"LOW|MEDIUM|HIGH\",\"file_path\":\"relative/path\",\"line_start\":1,"
        "\"line_end\":1,\"title\":\"specific reviewer-facing title\","
        "\"description\":\"why this is risky in this Skill package\","
        "\"evidence_summary\":\"specific concise evidence summary\","
        "\"evidence_detail\":\"detailed evidence with relevant excerpt or context\","
        "\"matched_text\":\"exact relevant excerpt when available\","
        "\"recommendation\":\"specific review or mitigation action\","
        "\"source\":\"claude\",\"confidence\":0.0}],"
        "\"review_suggestions\":[\"short checklist item\"]}. "
        "Risk titles and evidence_summary must be concrete and must mention the observed behavior, not only the risk type. "
        "Never return MEDIUM or HIGH risk_level with an empty risk_items array; if the package deserves MEDIUM or HIGH, "
        "include at least one concrete risk item with file_path and evidence_detail. "
        "Focus on shell execution, Python subprocess/os.system/exec/eval, file writes/deletes, rm/rmtree/unlink/delete, "
        "git reset/push/checkout, curl/wget/requests/fetch network access, .env/token/secret/key access, "
        "large/binary/executable scripts, and package.json scripts, but only when the evidence is behaviorally relevant. "
        "Use relative paths only, never absolute paths. "
        "If no semantic risks are found, return an empty risk_items array and concise review suggestions."
    )


def _semantic_retry_prompt(previous_error: str) -> str:
    return (
        _semantic_prompt()
        + " Your previous structured result was rejected because: "
        + str(previous_error)
        + " Re-open the package files and repair the analysis. "
        "If you cannot point to concrete file-level evidence, set risk_level, complexity, and review_priority to LOW "
        "and return an empty risk_items array. If the package deserves MEDIUM or HIGH risk_level, you must include "
        "specific risk_items with file_path, line_start when available, evidence_summary, evidence_detail, and recommendation. "
        "Do not return a placeholder, uncertainty-only, or meta-analysis risk item."
    )


def _json_from_text(text: str) -> Dict[str, Any]:
    candidate = str(text or "").strip()
    if not candidate:
        raise ValueError("Claude returned empty analysis")
    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.S | re.I)
    if fenced_match:
        try:
            parsed = json.loads(fenced_match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    decoder = json.JSONDecoder()
    parsed_candidates: List[Dict[str, Any]] = []
    for match in re.finditer(r"\{", candidate):
        try:
            parsed, _ = decoder.raw_decode(candidate[match.start() :])
        except Exception:
            continue
        if isinstance(parsed, dict):
            parsed_candidates.append(parsed)
    if parsed_candidates:
        return parsed_candidates[-1]
    raise ValueError("Claude analysis was not valid JSON")


def _normalize_level(value: Any, fallback: str) -> str:
    text = str(value or "").strip().upper()
    return text if text in {"LOW", "MEDIUM", "HIGH"} else fallback


def _merge_semantic_result(base: Dict[str, Any], semantic: Dict[str, Any]) -> Dict[str, Any]:
    contract_error = _semantic_contract_error(semantic)
    if contract_error:
        raise SemanticAnalysisContractError(contract_error)
    merged = dict(base)
    semantic_risk_level = _normalize_level(semantic.get("risk_level"), "LOW")
    merged["risk_level"] = _max_level(base.get("risk_level"), semantic_risk_level)
    merged["complexity"] = _max_level(base.get("complexity"), semantic.get("complexity"))
    merged["review_priority"] = _max_level(base.get("review_priority"), semantic.get("review_priority"))
    semantic_risks: List[Dict[str, Any]] = []
    for item in semantic.get("risk_items") or []:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file_path") or "").replace("\\", "/").strip("/")
        if not file_path:
            continue
        semantic_risks.append(
            _build_risk_item(
                risk_type=str(item.get("risk_type") or "SEMANTIC_RISK").strip() or "SEMANTIC_RISK",
                risk_level=_normalize_level(item.get("risk_level"), "MEDIUM"),
                file_path=file_path,
                line_start=_safe_int(item.get("line_start")),
                line_end=_safe_int(item.get("line_end")),
                title=str(item.get("title") or "").strip() or None,
                description=str(item.get("description") or "").strip() or None,
                evidence_summary=str(item.get("evidence_summary") or "").strip() or None,
                evidence_detail=str(item.get("evidence_detail") or "").strip() or None,
                matched_text=str(item.get("matched_text") or "").strip() or None,
                recommendation=str(item.get("recommendation") or "").strip() or None,
                source="claude",
                confidence=_safe_float(item.get("confidence"), 0.7),
            )
        )
    merged["risk_items"] = _dedupe_risks(semantic_risks)
    suggestions = [str(item).strip() for item in (semantic.get("review_suggestions") or []) if str(item).strip()]
    merged["review_suggestions"] = list(dict.fromkeys([*(base.get("review_suggestions") or []), *suggestions]))
    return merged


def _safe_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except Exception:
        return None
    return number if number > 0 else None


def _safe_float(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except Exception:
        return fallback
    return max(0.0, min(1.0, number))


def _max_level(left: Any, right: Any) -> str:
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    left_text = _normalize_level(left, "LOW")
    right_text = _normalize_level(right, left_text)
    return left_text if order[left_text] >= order[right_text] else right_text


async def _run_claude_semantic_analysis(package_root: str, *, prompt: Optional[str] = None) -> Dict[str, Any]:
    bridge = create_cli_bridge(cli_path=settings.CLAUDE_CLI_PATH)
    texts: List[str] = []

    async def _event_callback(event: Dict[str, Any]) -> None:
        event_type = str(event.get("type") or "").lower()
        if event_type == "assistant":
            message = event.get("message")
            blocks = message.get("content", []) if isinstance(message, dict) else []
            for block in (blocks if isinstance(blocks, list) else []):
                if isinstance(block, dict) and str(block.get("type") or "").lower() == "text":
                    text = str(block.get("text") or "").strip()
                    if text:
                        texts.append(text)
        elif event_type == "result":
            result = str(event.get("result") or "").strip()
            if result:
                texts.append(result)

    await bridge.start_session(
        prompt=prompt or _semantic_prompt(),
        project_path=package_root,
        event_callback=_event_callback,
        session_id=None,
    )
    if hasattr(bridge, "wait"):
        await asyncio.wait_for(bridge.wait(), timeout=SEMANTIC_TIMEOUT_SECONDS)
    elif hasattr(bridge, "is_running"):
        deadline = asyncio.get_running_loop().time() + SEMANTIC_TIMEOUT_SECONDS
        while bridge.is_running():
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Claude semantic analysis timed out")
            await asyncio.sleep(0.1)
    raw_text = "\n".join(texts)
    try:
        return _json_from_text(raw_text)
    except ValueError as exc:
        process = getattr(bridge, "process", None)
        return_code = getattr(process, "returncode", None)
        if return_code not in {None, 0}:
            raise ValueError(f"Claude semantic review exited with code {return_code} and did not return valid JSON") from exc
        raise


def run_analysis_job(analysis_id: str) -> None:
    db = SessionLocal()
    tmp_root: Optional[str] = None
    try:
        analysis = db.query(SddSkillAnalysis).filter(SddSkillAnalysis.id == analysis_id).first()
        if not analysis:
            return
        skill = db.query(SddSkill).filter(SddSkill.id == analysis.skill_id).first()
        if not skill:
            _set_analysis_state(
                db,
                analysis,
                status=SkillAnalysisStatus.FAILED,
                progress=100,
                message="Skill analysis failed",
                error_message="Skill not found",
                finished=True,
            )
            return

        _set_analysis_state(
            db,
            analysis,
            status=SkillAnalysisStatus.RUNNING,
            progress=5,
            message="Preparing skill package snapshot",
            started=True,
        )
        tmp_root = _make_snapshot(skill, analysis)
        package_root = os.path.join(tmp_root, "package")
        _set_analysis_state(db, analysis, progress=25, message="Scanning package files")
        deterministic = deterministic_scan(package_root, skill)
        _set_analysis_state(db, analysis, progress=60, message="Running semantic risk review", payload=deterministic)

        try:
            semantic = asyncio.run(_run_claude_semantic_analysis(package_root))
            contract_error = _semantic_contract_error(semantic)
            if contract_error:
                _set_analysis_state(
                    db,
                    analysis,
                    progress=75,
                    message="Retrying semantic risk review with stricter output contract",
                )
                semantic = asyncio.run(
                    _run_claude_semantic_analysis(
                        package_root,
                        prompt=_semantic_retry_prompt(contract_error),
                    )
                )
                contract_error = _semantic_contract_error(semantic)
                if contract_error:
                    raise SemanticAnalysisContractError(contract_error)
            result = _merge_semantic_result(deterministic, semantic)
        except SemanticAnalysisContractError as exc:
            failed = dict(deterministic)
            file_stats = dict(failed.get("file_stats") or {})
            file_stats["semantic_review_status"] = "INVALID_OUTPUT"
            file_stats["semantic_review_error"] = str(exc)
            failed["file_stats"] = file_stats
            _set_analysis_state(
                db,
                analysis,
                status=SkillAnalysisStatus.FAILED,
                progress=100,
                message=SEMANTIC_CONTRACT_FAILED_MESSAGE,
                error_message=str(exc),
                finished=True,
                payload=failed,
            )
            return
        except Exception as exc:
            degraded = dict(deterministic)
            file_stats = dict(degraded.get("file_stats") or {})
            file_stats["semantic_review_status"] = "UNAVAILABLE"
            file_stats["semantic_review_error"] = str(exc)
            degraded["file_stats"] = file_stats
            _set_analysis_state(
                db,
                analysis,
                status=SkillAnalysisStatus.SUCCESS,
                progress=100,
                message=SEMANTIC_UNAVAILABLE_MESSAGE,
                error_message="",
                finished=True,
                payload=degraded,
            )
            return

        _set_analysis_state(
            db,
            analysis,
            status=SkillAnalysisStatus.SUCCESS,
            progress=100,
            message="Skill analysis completed",
            error_message="",
            finished=True,
            payload=result,
        )
    except Exception as exc:
        try:
            analysis = db.query(SddSkillAnalysis).filter(SddSkillAnalysis.id == analysis_id).first()
            if analysis:
                _set_analysis_state(
                    db,
                    analysis,
                    status=SkillAnalysisStatus.FAILED,
                    progress=100,
                    message="Skill analysis failed",
                    error_message=str(exc),
                    finished=True,
                )
        except Exception:
            db.rollback()
    finally:
        db.close()
        if tmp_root:
            shutil.rmtree(tmp_root, ignore_errors=True)
