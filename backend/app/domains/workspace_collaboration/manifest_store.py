"""Store immutable inventories once; snapshot headers retain each historical event."""

import hashlib
import json

import zstandard
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CollaborationManifest, CollaborationSnapshot


def store_repositories(db: Session, task_id: str, repositories: list[dict]) -> str:
    # Collaboration mutations already hold the task row lock. Insert the content
    # before its referencing snapshot, in the same caller-owned transaction.
    raw = json.dumps(repositories, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    table = CollaborationManifest.__table__
    existing = db.execute(
        select(table.c.content_digest).where(table.c.task_id == task_id, table.c.content_digest == digest)
    ).first()
    if existing is None:
        db.execute(
            table.insert().values(
                task_id=task_id,
                content_digest=digest,
                repositories_zstd=zstandard.ZstdCompressor(level=3).compress(raw),
            )
        )
    return digest


def read_manifest(db: Session, snapshot: CollaborationSnapshot) -> dict:
    header = snapshot.manifest_json
    # Legacy headers remain readable during migration rehearsals and imports.
    if "repositories" in header:
        return header
    row = db.get(CollaborationManifest, (snapshot.task_id, snapshot.content_digest))
    if row is None:
        raise ValueError("Collaboration snapshot inventory is missing")
    raw = zstandard.ZstdDecompressor().decompress(row.repositories_zstd)
    if hashlib.sha256(raw).hexdigest() != snapshot.content_digest:
        raise ValueError("Collaboration snapshot inventory digest differs")
    return {**header, "repositories": json.loads(raw)}
