"""Validate workspace-owned, project-relative document directories."""


def normalize_plan_doc_roots(values: list[str]) -> list[str]:
    if len(values) > 32:
        raise ValueError("At most 32 document directories are allowed")
    roots: list[str] = []
    for value in values:
        normalized = value.strip().replace("\\", "/").rstrip("/")
        if (
            not normalized
            or len(normalized) > 1024
            or value.strip().startswith(("/", "\\"))
            or any(char in normalized for char in (":", "\x00", "\n", "\r"))
            or (normalized != "." and any(part.lower() in ("", ".", "..", ".git") for part in normalized.split("/")))
        ):
            raise ValueError("Document directories must be relative to the task root, without '..' or absolute paths")
        if normalized not in roots:
            roots.append(normalized)
    return roots
