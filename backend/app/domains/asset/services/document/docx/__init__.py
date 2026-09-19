"""DOCX 解析/构建子系统的对内门面。

仅暴露三个稳定入口，内部模块（parser/builder/runs/…）对
document 子包私有。
"""

from app.domains.asset.services.document.docx.builder import DOCX_MIME, build_docx_bytes
from app.domains.asset.services.document.docx.inplace import apply_blocks_to_docx_inplace
from app.domains.asset.services.document.docx.parser import (
    looks_like_docx_bytes,
    parse_docx_payload,
)

__all__ = [
    "DOCX_MIME",
    "apply_blocks_to_docx_inplace",
    "build_docx_bytes",
    "looks_like_docx_bytes",
    "parse_docx_payload",
]
