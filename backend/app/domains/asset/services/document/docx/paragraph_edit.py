"""Patch the text of a single review paragraph in the original Word package."""

from __future__ import annotations

import io
import re
import zipfile
from bisect import bisect_right
from collections.abc import Iterator
from copy import copy
from difflib import SequenceMatcher

from lxml import etree

from app.domains.asset.services.document.docx.paragraphs import PARAGRAPH_RUN_CONTAINERS
from app.domains.asset.services.document.docx.runs import run_child_text
from app.domains.asset.services.document.docx.xml_utils import DOCX_NS_MAP, local_name, xml_attr

DOCUMENT_PART = "word/document.xml"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _text_nodes(container: etree._Element) -> Iterator[etree._Element]:
    for child in container:
        if not isinstance(child.tag, str):
            continue
        name = local_name(child.tag)
        if name == "r":
            yield from child
        elif name in PARAGRAPH_RUN_CONTAINERS:
            yield from _text_nodes(child)


def _set_text(node: etree._Element, text: str) -> None:
    node.text = text
    if text != text.strip():
        node.set(XML_SPACE, "preserve")


def _replace_node_text(node: etree._Element, parts: list[str | etree._Element]) -> None:
    if node.tag == xml_attr("t"):
        text = "".join(parts)
        if "\n" not in text and "\t" not in text:
            if text != (node.text or ""):
                _set_text(node, text)
            return
    elif parts == [node]:
        return
    elif node.tag == xml_attr("br") and node.get(xml_attr("type")) in {"page", "column"} and node not in parts:
        raise ValueError("The paragraph's page or column break must be preserved")

    parent = node.getparent()
    position = parent.index(node)
    parent.remove(node)
    replacements: list[etree._Element] = []
    for part in parts:
        if isinstance(part, str):
            for piece in re.split(r"([\t\n])", part):
                if not piece:
                    continue
                tag = {"\t": "tab", "\n": "br"}.get(piece, "t")
                replacement = parent.makeelement(xml_attr(tag))
                if tag == "t":
                    _set_text(replacement, piece)
                replacements.append(replacement)
        else:
            replacements.append(part)
    parent[position:position] = replacements


def _patch_text(paragraph: etree._Element, old_text: str, new_text: str) -> None:
    nodes: list[etree._Element] = []
    texts: list[str] = []
    ends: list[int] = []
    for node in _text_nodes(paragraph):
        text = run_child_text(node)
        if text:
            nodes.append(node)
            texts.append(text)
            ends.append((ends[-1] if ends else 0) + len(text))
    if not nodes or "".join(texts) != old_text:
        raise ValueError("The review paragraph no longer matches the source DOCX")

    replacements: list[list[str | etree._Element]] = [[] for node in nodes]
    matcher = SequenceMatcher(a=old_text, b=new_text, autojunk=max(len(old_text), len(new_text)) > 2048)
    for operation, start, end, new_start, new_end in matcher.get_opcodes():
        index = bisect_right(ends, start)
        if operation == "equal":
            while start < end:
                node_start = ends[index] - len(texts[index])
                stop = min(end, ends[index])
                part = texts[index][start - node_start : stop - node_start]
                replacements[index].append(part if nodes[index].tag == xml_attr("t") else nodes[index])
                index += 1
                start = stop
        elif new_start < new_end:
            # Replacement inherits the first affected run. Appended text keeps the last run.
            replacements[min(index, len(nodes) - 1)].append(new_text[new_start:new_end])

    for node, parts in zip(nodes, replacements, strict=True):
        _replace_node_text(node, parts)


def edit_docx_paragraph(original_path: str, paragraph_index: int, old_text: str, new_text: str) -> bytes:
    """Return a DOCX whose other package parts are byte-for-byte identical."""
    output = io.BytesIO()
    try:
        with zipfile.ZipFile(original_path) as source:
            root = etree.fromstring(
                source.read(DOCUMENT_PART), parser=etree.XMLParser(resolve_entities=False, no_network=True)
            )
            body = root.find("w:body", DOCX_NS_MAP)
            paragraphs = list(body.iter(xml_attr("p"))) if body is not None else []
            if not 0 <= paragraph_index < len(paragraphs):
                raise ValueError("The review paragraph was not found in the source DOCX")

            _patch_text(paragraphs[paragraph_index], old_text, new_text)
            document_xml = etree.tostring(root.getroottree(), encoding="UTF-8", xml_declaration=True)
            with zipfile.ZipFile(output, mode="w") as updated:
                updated.comment = source.comment
                for entry in source.infolist():
                    data = document_xml if entry.filename == DOCUMENT_PART else source.read(entry)
                    updated.writestr(copy(entry), data)
    except (OSError, KeyError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
        raise ValueError("The source DOCX could not be read") from exc
    return output.getvalue()
