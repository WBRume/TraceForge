"""Business validators run before a terminal submission is accepted."""

import asyncio
import json
from pathlib import Path
from urllib.parse import unquote

from .runtime import DomainToolError


def validate_openapi(value):
    from openapi_spec_validator import validate
    from openapi_spec_validator.validation.exceptions import OpenAPIValidationError

    document = value.document
    if not str(document.get("openapi", "")).startswith(("3.0.", "3.1.")):
        raise DomainToolError("An OpenAPI 3.0 or 3.1 document is required")
    pending = [document]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            # A nested $id changes the base of otherwise-local references.
            # Require a self-contained document, without network resolution.
            if node.get("$id"):
                raise DomainToolError("Schema $id is not supported; use document-local references")
            for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
                if keyword in node:
                    _validate_local_reference(document, node[keyword])
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    try:
        validate(document)
    except OpenAPIValidationError as exc:
        raise DomainToolError(str(exc)[:4000]) from exc


def _validate_local_reference(document, ref):
    if not isinstance(ref, str) or (ref != "#" and not ref.startswith("#/")):
        raise DomainToolError("Only internal OpenAPI JSON pointer references are permitted")
    if ref == "#":
        return
    target = document
    try:
        for part in unquote(ref[2:]).split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            target = target[int(key)] if isinstance(target, list) and key.isdecimal() else target[key]
    except (KeyError, IndexError, TypeError, ValueError):
        raise DomainToolError(f"Unresolved reference: {ref}") from None


async def validate_mock_cases(value):
    templates = []
    for index, item in enumerate(value.cases):
        if item.mode != "MOCKJS":
            continue
        try:
            templates.append(json.loads(item.mockjs_template))
        except ValueError as exc:
            raise DomainToolError(f"cases.{index}.mockjs_template must be a JSON Mock.js template: {exc}") from exc
    if not templates:
        return
    root = Path(__file__).resolve().parents[4]
    cwd = root / "frontend" if (root / "frontend/node_modules/mockjs").is_dir() else root / "backend"
    script = (
        "const Mock=require('mockjs');let s='';process.stdin.on('data',x=>s+=x);"
        "process.stdin.on('end',()=>{try{for(const t of JSON.parse(s)){JSON.stringify(Mock.mock(t));}"
        "process.stdout.write(JSON.stringify({ok:true}));}catch(e){"
        "process.stdout.write(JSON.stringify({error:e.message}));}});"
    )
    process = await asyncio.create_subprocess_exec(
        "node",
        "-e",
        script,
        cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(json.dumps(templates).encode()), timeout=8)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError("Mock.js validation runtime is unavailable")
    output = json.loads(stdout)
    if output.get("error"):
        raise DomainToolError("Mock.js template: " + output["error"])


def skill_review_validator(package_root):
    root = Path(package_root).resolve()

    def validate(value):
        for item in value.risk_items:
            relative = Path(item.file_path)
            path = (root / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(root) or not path.is_file():
                raise DomainToolError(f"risk_items.file_path is not a file in this package: {item.file_path}")
            if item.line_start and item.line_end and item.line_end < item.line_start:
                raise DomainToolError(f"Invalid evidence line range: {item.file_path}")
            if item.line_start or item.line_end:
                if path.stat().st_size > 2_000_000:
                    raise DomainToolError(f"Evidence file exceeds the readable size limit: {item.file_path}")
                count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
                if max(item.line_start or 1, item.line_end or 1) > count:
                    raise DomainToolError(f"Evidence line exceeds file length: {item.file_path}")

    return validate
