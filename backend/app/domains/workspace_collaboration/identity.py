"""Line-ending independent file identity and checkout-form helpers.

Collaboration compares code that lives on machines with different line-ending
conventions: an Agent workspace on Linux keeps LF, a developer checkout on
Windows keeps CRLF for the same committed blob. Raw bytes therefore cannot be
the identity of a file. Every manifest entry publishes a content digest that
ignores line endings next to its raw ``sha256``; raw bytes stay the transfer,
storage and filesystem form.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from app.core.subprocess_runner import GIT_REPOSITORY_ENV_VARS, run_git

# Git's own heuristic: a NUL byte in the leading block makes a file binary.
BINARY_PROBE = 8000
TEXT_ATTRIBUTES = {"set", "auto"}


def is_binary(raw: bytes) -> bool:
    return b"\0" in raw[:BINARY_PROBE]


def lf_text(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def content_digest(raw: bytes) -> str:
    """Identity of the content: binary bytes as-is, text normalized to LF."""
    return hashlib.sha256(raw if is_binary(raw) else lf_text(raw)).hexdigest()


def same_file(left: dict | None, right: dict | None) -> bool:
    """A file is unchanged when its content and mode are unchanged."""
    if left is None or right is None:
        return left is None and right is None
    return left.get("mode") == right.get("mode") and left.get("content_sha256") == right.get("content_sha256")


def same_files(left: dict[str, dict], right: dict[str, dict]) -> bool:
    return left.keys() == right.keys() and all(same_file(file, right[path]) for path, file in left.items())


def same_repositories(left: list[dict], right: list[dict]) -> bool:
    """Compare inventories without depending on either host's checkout form."""
    if len(left) != len(right):
        return False
    theirs = {repo.get("task_repository_id"): repo for repo in right}
    if len(theirs) != len(right):
        return False
    for mine in left:
        other = theirs.get(mine.get("task_repository_id"))
        if other is None:
            return False
        if any(mine.get(key) != other.get(key) for key in mine if key != "files"):
            return False
        if not same_files(
            {file["path"]: file for file in mine["files"]}, {file["path"]: file for file in other["files"]}
        ):
            return False
    return True


def repositories_digest(repositories: list[dict]) -> str:
    """Opaque fence for an inventory, stable across checkout forms."""
    value = [
        [
            repo.get("task_repository_id"),
            [
                [file["path"], file["mode"], file["content_sha256"]]
                for file in sorted(repo["files"], key=lambda item: item["path"])
            ],
        ]
        for repo in sorted(repositories, key=lambda item: item["task_repository_id"])
    ]
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def checkout_bytes(raw: bytes, form: str | None) -> bytes:
    """Bytes a checkout of this repository would place in the working tree."""
    if form is None or is_binary(raw):
        return raw
    text = lf_text(raw)
    return text.replace(b"\n", b"\r\n") if form == "crlf" else text


def _config(root: Path, key: str) -> str:
    result = run_git(["config", "--get", key], cwd=str(root), unset_env=GIT_REPOSITORY_ENV_VARS)
    return result.stdout.strip().lower() if result.returncode == 0 else ""


def _attributes(root: Path, names: list[str]) -> dict[str, tuple[str, str]]:
    result = run_git(
        ["check-attr", "-z", "--stdin", "text", "eol"],
        cwd=str(root),
        input_data="\0".join(names).encode() + b"\0",
        decode_text=False,
        unset_env=GIT_REPOSITORY_ENV_VARS,
    )
    if result.returncode:
        raise ValueError("Unable to read collaboration checkout attributes")
    values = result.stdout.rstrip(b"\0").split(b"\0")
    grouped: dict[str, dict[str, str]] = {}
    for name, attribute, value in zip(values[0::3], values[1::3], values[2::3], strict=True):
        grouped.setdefault(name.decode(), {})[attribute.decode()] = value.decode()
    return {
        name: (value.get("text", "unspecified"), value.get("eol", "unspecified")) for name, value in grouped.items()
    }


def checkout_forms(root: Path, names: Iterable[str]) -> dict[str, str]:
    """Checkout form of every text-converted path in this repository.

    Only explicit conversions are honored: an ``eol`` attribute, or text files in
    a repository configured with ``core.autocrlf``. Anything else keeps
    repository bytes, so a Windows host without that configuration never
    rewrites LF files behind the Agent's back.
    """
    scoped = sorted({name for name in names if name})
    if not scoped:
        return {}
    attributes = _attributes(root, scoped)
    autocrlf = _config(root, "core.autocrlf")
    default_text = autocrlf in {"true", "input"}
    forms = {}
    for name in scoped:
        text, eol = attributes.get(name, ("unspecified", "unspecified"))
        if text == "unset":
            continue
        if not (text in TEXT_ATTRIBUTES or (text == "unspecified" and default_text)):
            continue
        crlf = eol == "crlf" or (eol not in {"lf", "crlf"} and autocrlf == "true")
        forms[name] = "crlf" if crlf else "lf"
    return forms
