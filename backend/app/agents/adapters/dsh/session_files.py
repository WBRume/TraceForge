"""DSH 会话持久化文件操作（fork 用）。

复刻 deepseek-harness `packages/session/session-persistence-jsonl/src/format.ts` 的
路径编码规则，实现「复制会话日志 + 重写头部 id/cwd」的文件级 fork：

    <root>/--<projectKey(cwd)>--/<encodeSegment(sessionId)>/session.jsonl[.zstd]

加载端（resume/findLog）会校验：请求 id == 头部 id，且
logPath(root, header.cwd, header.id) == 实际文件路径。
因此 fork 到新 id/新目录必须同时重写头部第一行并放到正确的 project key 下。
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional, Tuple

from app.agents.errors import SessionForkError

_SAFE_UNIT = re.compile(r"[A-Za-z0-9._-]")


def encode_segment(raw: str) -> str:
    """单段路径编码（injective）：安全字符保留，其余转 ~XXXX 大写十六进制。"""
    if not raw:
        raise ValueError("cannot encode an empty path segment")
    if raw == ".":
        return "~002E"
    if raw == "..":
        return "~002E~002E"
    out = []
    for ch in raw:
        if ch != "~" and _SAFE_UNIT.match(ch):
            out.append(ch)
        else:
            out.append("~%04X" % ord(ch))
    return "".join(out)


def project_key(cwd: str) -> str:
    """project 目录 key：/ \\ : 变 -（折叠连续），其余不安全字符转 ~XXXX。"""
    if not cwd:
        raise ValueError("cannot encode an empty project path")
    readable: list[str] = []
    separator_run = False
    for ch in cwd:
        if ch in ("/", "\\", ":"):
            if not separator_run:
                readable.append("-")
            separator_run = True
        elif ch != "~" and _SAFE_UNIT.match(ch):
            readable.append(ch)
            separator_run = False
        else:
            readable.append("~%04X" % ord(ch))
            separator_run = False
    slug = "".join(readable).lstrip("-") or "root"
    return f"--{slug[:251]}--"


def project_dir(root: str, cwd: Optional[str]) -> str:
    if cwd is None:
        return os.path.join(root, "_no-cwd")
    return os.path.join(root, project_key(cwd))


def session_log_path(root: str, cwd: Optional[str], session_id: str, suffix: str) -> str:
    return os.path.join(project_dir(root, cwd), encode_segment(session_id), f"session{suffix}")


def locate_session_log(root: str, session_id: str) -> Tuple[str, str]:
    """在 root 下扫描会话日志（id 在不同 project 目录下只应出现一次）。

    返回 (log_path, suffix)，suffix 为 '.jsonl' / '.jsonl.zstd'。
    """
    segment = encode_segment(session_id)
    if not os.path.isdir(root):
        raise SessionForkError(f"DSH sessions root not found: {root}")
    matches: list[Tuple[str, str]] = []
    for entry in os.listdir(root):
        proj_path = os.path.join(root, entry)
        if not os.path.isdir(proj_path):
            continue
        for suffix in (".jsonl", ".jsonl.zstd"):
            candidate = os.path.join(proj_path, segment, f"session{suffix}")
            if os.path.isfile(candidate):
                matches.append((candidate, suffix))
    if not matches:
        raise SessionForkError(
            f"DSH session log not found for fork: id={session_id}, root={root}"
        )
    if len(matches) > 1:
        raise SessionForkError(
            f"DSH session id {session_id} appears in multiple project dirs under {root}"
        )
    return matches[0]


def discover_latest_session(root: str, cwd: str) -> Optional[Tuple[str, str]]:
    """找 project 目录下最新写入的会话（CLI 不打印 session id，用此兜底发现）。

    返回 (session_id, log_path)；无会话返回 None。
    """
    proj_path = project_dir(root, cwd)
    if not os.path.isdir(proj_path):
        return None
    best: Optional[Tuple[float, str, str]] = None
    for entry in os.listdir(proj_path):
        sess_dir = os.path.join(proj_path, entry)
        if not os.path.isdir(sess_dir):
            continue
        for suffix in (".jsonl", ".jsonl.zstd"):
            log_file = os.path.join(sess_dir, f"session{suffix}")
            if os.path.isfile(log_file):
                mtime = os.path.getmtime(log_file)
                if best is None or mtime > best[0]:
                    best = (mtime, entry, log_file)
                break
    if best is None:
        return None
    _mtime, encoded_id, log_file = best
    return (encoded_id, log_file)


def _read_log_text(log_path: str, suffix: str) -> str:
    if suffix == ".jsonl":
        with open(log_path, "r", encoding="utf-8") as f:
            return f.read()
    try:
        import zstandard  # type: ignore
    except ImportError as exc:  # pragma: no cover - 环境缺依赖时给出明确指引
        raise SessionForkError(
            "DSH session logs use zstd; install 'zstandard' to enable session fork"
        ) from exc
    decompressor = zstandard.ZstdDecompressor()
    with open(log_path, "rb") as f:
        return decompressor.stream_reader(f).read().decode("utf-8")


def _write_log_text(log_path: str, suffix: str, text: str) -> None:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    if suffix == ".jsonl":
        with open(log_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return
    import zstandard  # type: ignore

    # DSH 加载端要求第一个 zstd 帧恰好解码为头部一行（assertZstdHeaderFrame），
    # 因此头部行单独压缩成帧，其余事件作为一个后续帧追加。
    lines = text.splitlines(keepends=True)
    header_line = lines[0] if lines else ""
    rest = "".join(lines[1:])
    compressor = zstandard.ZstdCompressor()
    with open(log_path, "wb") as f:
        f.write(compressor.compress(header_line.encode("utf-8")))
        if rest:
            f.write(compressor.compress(rest.encode("utf-8")))


def fork_session_log(
    root: str,
    session_id: str,
    *,
    new_session_id: str,
    target_cwd: str,
) -> str:
    """把 root 下的既有会话 fork 成 target_cwd 下的新 id 会话，返回新日志路径。

    复制全部事件并重写头部第一行的 id/cwd；整文件重写为单个 zstd 帧
    （加载端按帧流式解码，单帧同样合法），原会话保持只读。
    """
    source_path, suffix = locate_session_log(root, session_id)
    text = _read_log_text(source_path, suffix)
    lines = text.splitlines(keepends=True)
    if not lines:
        raise SessionForkError(f"DSH session log is empty: {source_path}")
    try:
        header = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise SessionForkError(f"DSH session log header corrupt: {source_path}") from exc
    if str(header.get("type") or "") != "session":
        raise SessionForkError(f"DSH session log header missing 'session' type: {source_path}")

    abs_cwd = os.path.abspath(target_cwd)
    header["id"] = new_session_id
    header["cwd"] = abs_cwd
    lines[0] = json.dumps(header, ensure_ascii=False) + "\n"

    target_path = session_log_path(root, abs_cwd, new_session_id, suffix)
    if os.path.exists(target_path):
        raise SessionForkError(f"DSH fork target already exists: {target_path}")
    _write_log_text(target_path, suffix, "".join(lines))
    return target_path
