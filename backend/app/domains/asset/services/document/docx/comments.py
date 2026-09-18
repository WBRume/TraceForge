"""DOCX 批注（comments.xml）解析。"""

from __future__ import annotations

from typing import Any, Dict, Optional

import xml.etree.ElementTree as ET

from app.domains.asset.services.document.docx.xml_utils import (
    DOCX_NS_MAP,
    decode_symbol,
    local_name,
    xml_attr,
)


def extract_comment_text(node: ET.Element) -> str:
    """提取批注正文的纯文本。"""
    lines = []
    for paragraph in node.findall("./w:p", DOCX_NS_MAP):
        parts = []
        for item in paragraph.iter():
            lname = local_name(item.tag)
            if lname == "t" and item.text:
                parts.append(item.text)
            elif lname in {"tab", "ptab"}:
                parts.append("\t")
            elif lname in {"br", "cr"}:
                parts.append("\n")
            elif lname == "sym":
                parts.append(decode_symbol(item.attrib.get(xml_attr("char"), "")))
        line = "".join(parts).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def parse_comments(comments_root: Optional[ET.Element]) -> Dict[str, Dict[str, Any]]:
    """解析 comments.xml → {comment_id: 元数据+正文}。"""
    comments: Dict[str, Dict[str, Any]] = {}
    if comments_root is None:
        return comments

    for comment in comments_root.findall(".//w:comment", DOCX_NS_MAP):
        comment_id = str(comment.attrib.get(xml_attr("id"), "") or "").strip()
        if not comment_id:
            continue
        comments[comment_id] = {
            "comment_id": comment_id,
            "author": str(comment.attrib.get(xml_attr("author"), "") or "").strip(),
            "initials": str(comment.attrib.get(xml_attr("initials"), "") or "").strip(),
            "date": str(comment.attrib.get(xml_attr("date"), "") or "").strip(),
            "content": extract_comment_text(comment),
        }
    return comments
