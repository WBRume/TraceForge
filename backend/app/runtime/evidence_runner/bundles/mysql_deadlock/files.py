"""Immutable tree copies and explicit source-only patch materialization."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from app.domains.diagnosis_playbook.compiler import require, safe_relative
from app.domains.diagnosis_playbook.contracts import digest


def tree_manifest(root):
    root = Path(root).resolve(strict=True)
    result = {}
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.relative_to(root).parts:
            continue
        reparse = bool(getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
        require(not path.is_symlink() and not reparse, "SOURCE_LINK_NOT_SUPPORTED")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            require(not any(p.startswith(".env") or p in {".git", ".ssh", ".aws", "credentials"} for p in path.relative_to(root).parts), "SOURCE_CONTAINS_PRIVATE_FILES")
            require(path.stat().st_size <= 10_000_000, "SOURCE_FILE_TOO_LARGE")
            with path.open("rb") as stream:
                result[relative] = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
            require(len(result) <= 20_000, "SOURCE_TREE_TOO_LARGE")
    return result


def freeze_tree(source, target, expected_digest, changes=None):
    source, target = Path(source), Path(target)
    original = tree_manifest(source)
    require(digest(original) == expected_digest, "SOURCE_SNAPSHOT_CHANGED")
    changes = changes or {}
    for name, content in changes.items():
        require(safe_relative(name) and isinstance(content, str), "INVALID_PATCH_FILE")
        # Dependencies, tests, configuration and the trusted harness are frozen.
        require(name in original and name.endswith(".py") and not any(
            p.startswith("test") or p in {"tests", "oracle", "fixture", "conftest.py", "sitecustomize.py", "usercustomize.py"}
            for p in Path(name).parts), "PROTECTED_ARTIFACT_CHANGED")
    expected = {**original, **{k: "sha256:" + hashlib.sha256(v.encode()).hexdigest() for k, v in changes.items()}}
    if target.exists():
        require(tree_manifest(target) == expected, "FROZEN_TREE_CHANGED")
        return digest(expected)
    temporary = target.with_name(target.name + ".building-" + os.urandom(8).hex())
    temporary.mkdir(parents=True)
    for name in original:
        destination = temporary / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if name in changes:
            destination.write_bytes(changes[name].encode())
        else:
            shutil.copyfile(source / name, destination)
    require(tree_manifest(temporary) == expected, "SOURCE_CHANGED_DURING_COPY")
    try:
        temporary.rename(target)
    except FileExistsError:
        require(tree_manifest(target) == expected, "FROZEN_TREE_CHANGED")
        # Only remove this invocation's verified private staging directory.
        require(temporary.resolve().parent == target.resolve().parent, "STAGING_PATH_ESCAPE")
        shutil.rmtree(temporary)
    return digest(expected)


def immutable_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        require(path.read_text(encoding="utf-8") == encoded, "IMMUTABLE_MANIFEST_CHANGED")
