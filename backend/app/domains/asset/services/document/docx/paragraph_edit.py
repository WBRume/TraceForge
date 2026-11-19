"""Edit review text ranges and append paragraphs in the original Word package."""

from __future__ import annotations

import io
import re
import zipfile
from bisect import bisect_right
from collections.abc import Iterator, Sequence
from copy import copy, deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher

from lxml import etree

from app.domains.asset.services.document.docx.paragraphs import PARAGRAPH_RUN_CONTAINERS
from app.domains.asset.services.document.docx.runs import run_child_text
from app.domains.asset.services.document.docx.xml_utils import DOCX_NS_MAP, local_name, xml_attr

DOCUMENT_PART = "word/document.xml"
STYLES_PART = "word/styles.xml"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


@dataclass(frozen=True)
class DocxRegion:
    id: str
    block_id: str
    paragraph: int
    block_start: int
    text: str
    in_table: bool


@dataclass(frozen=True)
class TextReplacement:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class DocxChapter:
    title: str
    level: int
    paragraphs: Sequence[str]


def docx_edit_regions(blocks: list[dict]) -> dict[str, DocxRegion]:
    regions = {}
    for block in blocks:
        spans = block.get("docx_spans") or []
        block_id, text = block["id"], block["text"]
        if block.get("type") == "table":
            for span in spans:
                ordinal, start, end = span["paragraph"], span["start"], span["end"]
                region_id = f"{block_id}:{ordinal}"
                regions[region_id] = DocxRegion(region_id, block_id, ordinal, start, text[start:end], True)
            for ordinal in block.get("docx_empty_paragraphs", []):
                region_id = f"{block_id}:{ordinal}"
                regions[region_id] = DocxRegion(region_id, block_id, ordinal, 0, "", True)
        elif len(spans) == 1:
            regions[block_id] = DocxRegion(block_id, block_id, spans[0]["paragraph"], 0, text, False)
    return regions


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


def diff_text_replacements(old_text: str, new_text: str, *, offset: int = 0) -> list[TextReplacement]:
    matcher = SequenceMatcher(a=old_text, b=new_text, autojunk=max(len(old_text), len(new_text)) > 2048)
    return [
        TextReplacement(offset + start, offset + end, new_text[new_start:new_end])
        for operation, start, end, new_start, new_end in matcher.get_opcodes()
        if operation != "equal"
    ]


def _patch_text(paragraph: etree._Element, old_text: str, edits: Sequence[TextReplacement]) -> None:
    nodes: list[etree._Element] = []
    texts: list[str] = []
    ends: list[int] = []
    for node in _text_nodes(paragraph):
        text = run_child_text(node)
        if text:
            nodes.append(node)
            texts.append(text)
            ends.append((ends[-1] if ends else 0) + len(text))
    if "".join(texts) != old_text:
        raise ValueError("The review paragraph no longer matches the source DOCX")
    if not nodes:
        if edits:
            _insert_text(paragraph, edits[0].text)
        return

    replacements: list[list[str | etree._Element]] = [[] for node in nodes]

    def keep(start: int, end: int) -> None:
        index = bisect_right(ends, start)
        while start < end:
            node_start = ends[index] - len(texts[index])
            stop = min(end, ends[index])
            part = texts[index][start - node_start : stop - node_start]
            replacements[index].append(part if nodes[index].tag == xml_attr("t") else nodes[index])
            index += 1
            start = stop

    cursor = 0
    for edit in edits:
        if not cursor <= edit.start <= edit.end <= len(old_text):
            raise ValueError("The requested DOCX text ranges overlap or are out of bounds")
        keep(cursor, edit.start)
        if edit.text:
            # Replacement inherits the first affected run. Appended text keeps the last run.
            index = min(bisect_right(ends, edit.start), len(nodes) - 1)
            replacements[index].append(edit.text)
        cursor = edit.end
    keep(cursor, len(old_text))

    for node, parts in zip(nodes, replacements, strict=True):
        _replace_node_text(node, parts)


def _insert_text(paragraph: etree._Element, text: str) -> None:
    empty_text = paragraph.find("w:r/w:t", DOCX_NS_MAP)
    if empty_text is None:
        run = next(
            (
                run
                for run in paragraph.findall("w:r", DOCX_NS_MAP)
                if all(child.tag == xml_attr("rPr") for child in run)
            ),
            None,
        )
        if run is None:
            run = etree.SubElement(paragraph, xml_attr("r"))
            mark_properties = paragraph.find("w:pPr/w:rPr", DOCX_NS_MAP)
            if mark_properties is not None:
                run_properties = etree.SubElement(run, xml_attr("rPr"))
                revision_tags = {xml_attr(tag) for tag in ("ins", "del", "moveFrom", "moveTo", "rPrChange")}
                run_properties.extend(deepcopy(prop) for prop in mark_properties if prop.tag not in revision_tags)
        empty_text = etree.SubElement(run, xml_attr("t"))
    _replace_node_text(empty_text, [text])


def edit_docx_paragraph(original_path: str, paragraph_index: int, old_text: str, new_text: str) -> bytes:
    return edit_docx_paragraphs(original_path, [(paragraph_index, old_text, new_text)])


def edit_docx_paragraphs(original_path: str, edits: Sequence[tuple[int, str, str]]) -> bytes:
    """Patch the requested source paragraphs and retain the rest of the package."""
    return edit_docx_ranges(
        original_path, [(ordinal, old, diff_text_replacements(old, new)) for ordinal, old, new in edits], ()
    )[0]


def _heading_styles(source: zipfile.ZipFile, parser: etree.XMLParser, body: etree._Element) -> dict[int, str]:
    try:
        styles = etree.fromstring(source.read(STYLES_PART), parser=parser)
    except KeyError:
        return {}
    used = {style.get(xml_attr("val")) for style in body.iter(xml_attr("pStyle"))}
    result: dict[int, str] = {}
    for style in styles.findall("w:style", DOCX_NS_MAP):
        style_id = style.get(xml_attr("styleId"))
        if style.get(xml_attr("type")) != "paragraph" or not style_id:
            continue
        outline = style.find("w:pPr/w:outlineLvl", DOCX_NS_MAP)
        name = style.find("w:name", DOCX_NS_MAP)
        level = outline.get(xml_attr("val"), "") if outline is not None else ""
        if len(level) == 1 and level in "012345678":
            heading_level = int(level) + 1
        else:
            normalized = name.get(xml_attr("val"), "") if name is not None else style_id
            match = re.fullmatch(r"heading\s*([1-9])", normalized, re.IGNORECASE)
            if not match:
                continue
            heading_level = int(match[1])
        if heading_level not in result or (style_id in used and result[heading_level] not in used):
            result[heading_level] = style_id
    return result


def _append_chapters(
    body: etree._Element,
    chapters: Sequence[DocxChapter],
    styles: dict[int, str],
    first_ordinal: int,
) -> list[int]:
    ending = body.find("w:sectPr", DOCX_NS_MAP)
    position = body.index(ending) if ending is not None else len(body)
    headings = []
    for chapter in chapters:
        headings.append(first_ordinal)
        for index, text in enumerate((chapter.title, *chapter.paragraphs)):
            paragraph = body.makeelement(xml_attr("p"))
            if index == 0:
                properties = etree.SubElement(paragraph, xml_attr("pPr"))
                if style := styles.get(chapter.level):
                    heading = etree.SubElement(properties, xml_attr("pStyle"))
                    heading.set(xml_attr("val"), style)
                else:
                    outline = etree.SubElement(properties, xml_attr("outlineLvl"))
                    outline.set(xml_attr("val"), str(chapter.level - 1))
                    run = etree.SubElement(paragraph, xml_attr("r"))
                    etree.SubElement(etree.SubElement(run, xml_attr("rPr")), xml_attr("b"))
            _insert_text(paragraph, text)
            body.insert(position, paragraph)
            position += 1
            first_ordinal += 1
    return headings


def edit_docx_ranges(
    original_path: str,
    edits: Sequence[tuple[int, str, Sequence[TextReplacement]]],
    chapters: Sequence[DocxChapter],
) -> tuple[bytes, list[int]]:
    output = io.BytesIO()
    try:
        with zipfile.ZipFile(original_path) as source:
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            root = etree.fromstring(source.read(DOCUMENT_PART), parser=parser)
            body = root.find("w:body", DOCX_NS_MAP)
            if body is None:
                raise ValueError("The source DOCX does not have a document body")
            paragraphs = list(body.iter(xml_attr("p")))
            for paragraph_index, old_text, replacements in edits:
                if not 0 <= paragraph_index < len(paragraphs):
                    raise ValueError("The review paragraph was not found in the source DOCX")
                _patch_text(paragraphs[paragraph_index], old_text, replacements)
            headings = (
                _append_chapters(body, chapters, _heading_styles(source, parser, body), len(paragraphs))
                if chapters
                else []
            )
            document_xml = etree.tostring(root.getroottree(), encoding="UTF-8", xml_declaration=True)
            with zipfile.ZipFile(output, mode="w") as updated:
                updated.comment = source.comment
                for entry in source.infolist():
                    data = document_xml if entry.filename == DOCUMENT_PART else source.read(entry)
                    updated.writestr(copy(entry), data)
    except (OSError, KeyError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
        raise ValueError("The source DOCX could not be read") from exc
    return output.getvalue(), headings
