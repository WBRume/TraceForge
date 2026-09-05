"""
统一的同步子进程执行内核（硬超时 + 进程组回收）。

设计目标：任何 subprocess 都不允许无超时地占用 offload 线程。

- 每个子进程以独立进程组启动（Windows CREATE_NEW_PROCESS_GROUP /
  POSIX start_new_session），超时时整组回收：Windows ``taskkill /F /T``、
  POSIX ``os.killpg(SIGKILL)``，避免 credential helper 等孙进程残留；
- 超时后二次 ``communicate(5s)`` 收尸，随后抛 ``ProcessTimeoutError``；
- ``run_git`` 额外注入 GIT_TERMINAL_PROMPT=0 等防挂环境变量
  （参照 skill/github_import_service 的既有实现），杜绝凭据弹窗挂死。

本模块只负责进程执行与回收；各业务方在其上保留各自的异常语义
（check=False 返回 CompletedProcess，由调用方按需 raise）。
"""

from __future__ import annotations

import os
import signal
import subprocess
from typing import List, Mapping, Optional

from app.config import settings


class ProcessRunnerError(RuntimeError):
    """子进程执行失败（非零退出）。"""

    def __init__(self, message: str, *, returncode: int, stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class ProcessTimeoutError(RuntimeError):
    """子进程超时；进程树已被回收。

    注意：不要把命令列表存到 ``args`` 属性（会覆盖 BaseException.args，
    破坏 str(exc)），此处命名为 ``command``。
    """

    def __init__(self, message: str, *, timeout_seconds: float, command: List[str]) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.command = command


def _process_group_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process_tree(process: subprocess.Popen) -> None:
    """终止整个进程组（Windows 树杀 / POSIX 进程组 SIGKILL）。"""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass


def _git_safe_env(extra: Optional[Mapping[str, str]] = None) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_ASKPASS": "echo",
            "SSH_ASKPASS": "echo",
        }
    )
    if extra:
        env.update({str(k): str(v) for k, v in extra.items() if v is not None})
    return env


def _reap_after_kill(process: subprocess.Popen) -> None:
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
    except Exception:
        pass


def run_process(
    args: List[str],
    *,
    cwd: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    env: Optional[Mapping[str, str]] = None,
    decode_text: bool = True,
) -> subprocess.CompletedProcess:
    """执行子进程（独立进程组 + 硬超时 + 超时整组回收）。

    timeout_seconds 缺省取 settings.GIT_COMMAND_TIMEOUT_SECONDS；
    传 None 之外的正值覆盖。超时抛 ProcessTimeoutError，进程树已回收。
    """
    timeout = timeout_seconds
    if timeout is None:
        timeout = float(getattr(settings, "GIT_COMMAND_TIMEOUT_SECONDS", 180) or 180)
    timeout = max(1.0, float(timeout))

    popen_kwargs: dict = dict(
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if decode_text:
        popen_kwargs.update(text=True, encoding="utf-8", errors="replace")
    if env is not None:
        popen_kwargs["env"] = dict(env)
    popen_kwargs.update(_process_group_kwargs())

    process = subprocess.Popen(list(args), **popen_kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        terminate_process_tree(process)
        _reap_after_kill(process)
        raise ProcessTimeoutError(
            f"Process timed out after {timeout:g}s: {' '.join(str(a) for a in args[:4])}",
            timeout_seconds=timeout,
            command=[str(a) for a in args],
        ) from exc

    return subprocess.CompletedProcess(
        args=list(args),
        returncode=process.returncode,
        stdout=stdout if decode_text else (stdout or b""),
        stderr=stderr if decode_text else (stderr or b""),
    )


def run_git(
    args: List[str],
    *,
    cwd: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    env_extra: Optional[Mapping[str, str]] = None,
    decode_text: bool = True,
) -> subprocess.CompletedProcess:
    """执行 git 命令：防挂 env + 独立进程组 + 硬超时（详见 run_process）。"""
    command = ["git", *args]
    return run_process(
        command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        env=_git_safe_env(env_extra),
        decode_text=decode_text,
    )


def check_completed(
    result: subprocess.CompletedProcess,
    *,
    error: type[Exception],
    message_prefix: str,
    code: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """check=True 语义的统一收口：非零退出时抛调用方领域异常。"""
    if result.returncode == 0:
        return result
    stdout = result.stdout if isinstance(result.stdout, str) else (result.stdout or b"").decode("utf-8", "replace")
    stderr = result.stderr if isinstance(result.stderr, str) else (result.stderr or b"").decode("utf-8", "replace")
    detail = (stderr or stdout or "git command failed").strip()[-500:]
    if code is not None:
        raise error(f"{message_prefix}: {detail}", code=code)
    raise error(f"{message_prefix}: {detail}")
