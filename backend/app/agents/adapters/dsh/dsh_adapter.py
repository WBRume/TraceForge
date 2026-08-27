"""DSH 会话根目录解析（Web Host server 模式共用）。

TraceForge 的 dsh backend 固定使用 `dsh web` Web Host server 模式；
headless CLI 模式已移除。此模块仅保留 Web Host fork 所需的持久化根解析。
"""

from __future__ import annotations

import os


def dsh_sessions_root() -> str:
    """解析 DSH 会话持久化根目录。

    - Web Host profile: $DSH_HOME/sessions（DSH_HOME 缺省 ~/.dsh）
    - 显式 settings/env 优先，保证 fork 读取与 Web Host 写入的根一致。
    """
    from app.config import settings

    explicit = str(getattr(settings, "DSH_SESSION_ROOT", "") or "").strip()
    if explicit:
        return os.path.abspath(explicit)
    env_root = str(os.environ.get("DSH_SESSION_ROOT") or "").strip()
    if env_root:
        return os.path.abspath(env_root)
    dsh_home = str(os.environ.get("DSH_HOME") or "").strip()
    if dsh_home:
        return os.path.join(os.path.abspath(dsh_home), "sessions")
    return os.path.join(os.path.expanduser("~"), ".dsh", "sessions")