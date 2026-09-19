# backend/app/domains/asset/services/document/docx/inplace.py
"""DOCX 整篇原位编辑:final blocks AST → 原文件段落级 patch(python-docx)。

对齐规则与 XML 解析器一致:base blocks 顺序 ↔ body 非空 w:p/w:tbl 顺序。
只改文本发生变化的段落;未变段落零损伤(样式/编号/批注全保留)。
任何不匹配(结构漂移/表格变更/解析失败)返回 None,由调用方降级重建。
"""

import copy
import io
import os
from typing import Any, Dict, List, Optional

try:
    from docx import Document as DocxDocument  # type: ignore
except Exception:
    DocxDocument = None

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _element_text(p_el) -> str:
    parts = [node.text or "" for node in p_el.iter(f"{W_NS}t")]
    return "".join(parts)


def _is_empty_paragraph(p_el) -> bool:
    return not _element_text(p_el).strip()


def _rewrite_paragraph_text(p_el, new_text: str) -> None:
    """清空段落 runs 并重写为单 run 文本;保留 pPr 与首个 run 的 rPr。"""
    first_rpr = None
    for r in list(p_el.iter(f"{W_NS}r")):
        if first_rpr is None:
            rpr = r.find(f"{W_NS}rPr")
            if rpr is not None:
                first_rpr = copy.deepcopy(rpr)
        r.getparent().remove(r)
    # 段落内残留的空 hyperlink/smartTag 外壳一并移除(只留 pPr 与新 run)
    for tag in ("hyperlink", "smartTag", "sdt"):
        for node in list(p_el.findall(f".//{W_NS}{tag}")):
            node.getparent().remove(node)
    run = p_el.makeelement(f"{W_NS}r", {})
    if first_rpr is not None:
        run.append(first_rpr)
    t = p_el.makeelement(f"{W_NS}t", {})
    t.set(XML_SPACE, "preserve")
    t.text = new_text
    run.append(t)
    p_el.append(run)


def _style_name_for(block: Dict[str, Any]) -> Optional[str]:
    btype = str(block.get("type") or "paragraph")
    meta = block.get("meta") if isinstance(block.get("meta"), dict) else {}
    if btype == "heading":
        level = min(max(int(meta.get("level") or 1), 1), 6)
        return f"Heading {level}"
    if btype == "list_item":
        marker = str(meta.get("marker") or "-")
        return "List Number" if marker[:1].isdigit() else "List Bullet"
    return None


def _new_paragraph_element(doc, block: Dict[str, Any]):
    """新建段落元素(含样式),返回其 XML 元素;失败返回纯段落。"""
    text = str(block.get("text") or "")
    style_name = _style_name_for(block)
    para = None
    if style_name:
        try:
            para = doc.add_paragraph(text, style=style_name)
        except Exception:
            para = None
    if para is None:
        para = doc.add_paragraph(text)
    el = para._p
    el.getparent().remove(el)
    return el


def apply_blocks_to_docx_inplace(
    original_path: str,
    base_blocks: List[Dict[str, Any]],
    final_blocks: List[Dict[str, Any]],
) -> Optional[bytes]:
    """在原 docx 上按 final_blocks 做原位编辑;成功返回新字节,失败返回 None。"""
    if DocxDocument is None:
        return None
    if not original_path or not os.path.isfile(original_path):
        return None
    base_list = [b for b in (base_blocks or []) if isinstance(b, dict)]
    final_list = [b for b in (final_blocks or []) if isinstance(b, dict)]
    if not base_list or not final_list:
        return None
    try:
        doc = DocxDocument(original_path)
    except Exception:
        return None

    body = doc.element.body
    non_empty = [
        child
        for child in list(body)
        if child.tag == f"{W_NS}tbl" or (child.tag == f"{W_NS}p" and not _is_empty_paragraph(child))
    ]
    if len(non_empty) != len(base_list):
        return None

    final_by_id: Dict[str, Dict[str, Any]] = {
        str(b.get("id")): b for b in final_list if str(b.get("id") or "").strip()
    }

    el_by_base_id: Dict[str, Any] = {}
    deleted_ids: set = set()
    changed_any = False
    cursor = 0
    for base in base_list:
        bid = str(base.get("id") or "")
        el = non_empty[cursor]
        cursor += 1
        el_by_base_id[bid] = el
        if bid not in final_by_id:
            deleted_ids.add(bid)
            el.getparent().remove(el)
            changed_any = True
            continue
        final = final_by_id[bid]
        if _norm(str(final.get("text") or "")) == _norm(str(base.get("text") or "")):
            continue
        if str(base.get("type") or "") == "table" or str(final.get("type") or "") == "table":
            return None
        _rewrite_paragraph_text(el, str(final.get("text") or ""))
        changed_any = True

    # 插入 blk-new-*:放到后继仍存活的 base 元素之前;无后继则追加到 body 末尾(sectPr 之前)
    for idx, final in enumerate(final_list):
        fid = str(final.get("id") or "")
        if not fid.startswith("blk-new-"):
            continue
        anchor_el = None
        for later in final_list[idx + 1:]:
            lid = str(later.get("id") or "")
            if lid in el_by_base_id and lid not in deleted_ids:
                anchor_el = el_by_base_id[lid]
                break
        new_el = _new_paragraph_element(doc, final)
        if anchor_el is not None:
            anchor_el.addprevious(new_el)
        else:
            sect = body.find(f"{W_NS}sectPr")
            if sect is not None:
                sect.addprevious(new_el)
            else:
                body.append(new_el)
        changed_any = True

    if not changed_any:
        return None
    buffer = io.BytesIO()
    try:
        doc.save(buffer)
    except Exception:
        return None
    return buffer.getvalue()
