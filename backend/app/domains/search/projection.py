"""Deterministic visible-text projection; no provider calls or metadata dumps."""
import hashlib
import json
import re
import unicodedata


def value(raw):
    return getattr(raw, "value", raw)


def plain_text(text):
    text = unicodedata.normalize("NFC", str(text or "").replace("\r\n", "\n").replace("\r", "\n"))
    # Preserve code fences' bodies, link labels and code punctuation.
    text = re.sub(r"(?m)^\s*```[^\n]*\n?", "", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^\n)]*\)", r"\1", text)
    text = re.sub(r"(?m)^ {0,3}#{1,6}\s+", "", text)
    return text.strip()


def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_search_projection(source, kind):
    if kind == "message":
        role, message_type = value(source.role), value(source.message_type)
        if role not in ("user", "assistant") or message_type not in ("text", "error", "diagnosis_result"):
            return None
        content = source.content
        if message_type == "diagnosis_result":
            meta = source.metadata_json or {}
            content = "\n".join(str(meta[k]) for k in ("summary", "root_cause", "solution", "recommendation", "impact", "verification") if isinstance(meta.get(k), str)) or content
        title = ""
        task_id = source.task_id
    else:
        role, message_type, task_id = None, None, source.id
        title, content = plain_text(source.name), source.description
    text = plain_text(content)
    if not text and not title:
        return None
    symbols = list(dict.fromkeys(s for s in re.findall(r"[A-Za-z_][A-Za-z0-9_./:\\\-]*", title + "\n" + text) if len(s.encode()) <= 256))
    doc = dict(entity_key=f"{kind}:{source.id}", kind=kind, workspace_id=source.workspace_id,
               task_id=task_id, creator_id=source.creator_id, title=title, content_text=text,
               symbols=symbols, deleted=False, schema_version=1,
               created_at=source.created_at.isoformat() if source.created_at else None)
    if kind == "message":
        doc.update(message_id=source.id, role=role, message_type=message_type, session_generation=source.session_generation)
    doc["projection_hash"] = digest(doc)
    return doc


def es_version(source_version, phase):
    if not 1 <= source_version <= (2**63 - 2) // 2 or phase not in (0, 1):
        raise ValueError("SEARCH_INVALID_VERSION")
    return 2 * source_version + phase


def build_embedding_chunks(text, size=1600, overlap=160):
    if not 32 <= size <= 2000 or not 0 <= overlap < size:
        raise ValueError("EMBEDDING_INVALID_CHUNK_CONFIG")
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(dict(chunk_no=len(chunks), start_char=start, end_char=end, text=text[start:end]))
        if end == len(text):
            break
        start = end - overlap
    if len(chunks) > 256:
        raise ValueError("EMBEDDING_INPUT_TOO_LONG")
    return chunks


def embedding_text(doc):
    return (doc.get("title", "") + "\n" + doc.get("content_text", "")).strip() if doc["kind"] == "task" else doc["content_text"]
