"""The original MD and TXT text used by the editor and selection anchors."""

from __future__ import annotations

from codecs import BOM_UTF8, BOM_UTF16_BE, BOM_UTF16_LE, BOM_UTF32_BE, BOM_UTF32_LE
from pathlib import Path

from app.domains.asset.models.asset import SddAssetVersion

TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
SOURCE_BLOCK_ID = "source-text"


def decode_source(raw: bytes) -> tuple[str, str, bytes]:
    for bom, encoding in (
        (BOM_UTF32_LE, "utf-32-le"),
        (BOM_UTF32_BE, "utf-32-be"),
        (BOM_UTF16_LE, "utf-16-le"),
        (BOM_UTF16_BE, "utf-16-be"),
        (BOM_UTF8, "utf-8"),
    ):
        if raw.startswith(bom):
            return raw[len(bom) :].decode(encoding, errors="replace"), encoding, bom
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding), encoding, b""
        except UnicodeDecodeError:
            continue
    raise ValueError("The original text could not be decoded")


def read_original(version: SddAssetVersion) -> bytes:
    if not version.original_path:
        raise FileNotFoundError("The original document is unavailable")
    return Path(version.original_path).read_bytes()


def review_source(version: SddAssetVersion) -> str | None:
    if (version.original_ext or "").lower() not in TEXT_EXTENSIONS:
        return None
    if "_review_source" not in version.__dict__:
        try:
            version._review_source = decode_source(read_original(version))[0]
        except OSError:
            version._review_source = version.normalized_markdown or ""
    return version._review_source
