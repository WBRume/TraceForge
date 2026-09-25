"""任务资产文件存储：.sdd/assets 版本目录、原文件落盘与 CLI 工作区副本。"""

from __future__ import annotations

import os
import re
from typing import Optional

from app.domains.asset.models.asset import SddAsset
from app.domains.task.models.task import SddTask


def normalize_filename(file_name: Optional[str], fallback_ext: str = ".md") -> str:
    base = os.path.basename(file_name or "").strip()
    if not base:
        base = f"document{fallback_ext}"
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return sanitized or f"document{fallback_ext}"


def task_assets_root(task: SddTask) -> str:
    from app.domains.local_resource.service import is_local
    if is_local(task):
        from app.config import _resolve_backend_path
        root = _resolve_backend_path("storage/local-resource-assets", fallback="storage/local-resource-assets")
        root = os.path.join(root, task.workspace_id, task.id)
        os.makedirs(root, exist_ok=True)
        return root
    raw_project_path = str(task.project_path or "").strip()
    if not raw_project_path:
        raise ValueError("Task project path is missing")
    root = os.path.abspath(os.path.join(raw_project_path, ".sdd", "assets"))
    os.makedirs(root, exist_ok=True)
    return root


def version_dir(task: SddTask, asset: SddAsset, version_no: int) -> str:
    path = os.path.join(
        task_assets_root(task),
        asset.id,
        f"v{version_no}",
    )
    os.makedirs(path, exist_ok=True)
    return path


def write_original_file(
    task: SddTask,
    asset: SddAsset,
    version_no: int,
    file_name: str,
    file_content: bytes,
) -> str:
    storage_dir = version_dir(task, asset, version_no)
    safe_name = normalize_filename(file_name)
    target_path = os.path.abspath(os.path.join(storage_dir, safe_name))
    with open(target_path, "wb") as f:
        f.write(file_content)
    return target_path


def write_cli_workspace_copy(task: SddTask, file_name: str, file_content: bytes) -> str:
    """将文件副本写入任务 CLI 工作区 .sdd/diagnosis/，供 AI 会话直接读取。"""
    from app.domains.local_resource.service import is_local, materialize_file
    if is_local(task):
        return materialize_file(task, ".sdd/diagnosis/" + normalize_filename(file_name), file_content)
    base_dir = str(getattr(task, "project_path", "") or "").strip() or os.getcwd()
    cli_dir = os.path.abspath(os.path.join(base_dir, ".sdd", "diagnosis"))
    os.makedirs(cli_dir, exist_ok=True)
    cli_path = os.path.join(cli_dir, file_name)
    with open(cli_path, "wb") as f:
        f.write(file_content)
    return cli_path
