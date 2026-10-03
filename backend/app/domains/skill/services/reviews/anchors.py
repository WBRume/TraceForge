"""Resolve review anchors against immutable text and character offsets."""

from __future__ import annotations
from typing import List, Optional, Tuple


def _build_line_start_offsets(text: str) -> List[int]:
    starts = [0]
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        if ch == "\r":
            if index + 1 < length and text[index + 1] == "\n":
                index += 1
            starts.append(index + 1)
        elif ch == "\n":
            starts.append(index + 1)
        index += 1
    return starts


def _line_content_end_offset(text: str, line_start_offset: int) -> int:
    index = line_start_offset
    length = len(text)
    while index < length and text[index] not in ("\r", "\n"):
        index += 1
    return index


def _offset_from_line_column(
    text: str,
    line_starts: List[int],
    line_no: int,
    column_no: int,
) -> int:
    if line_no < 1 or line_no > len(line_starts):
        raise ValueError("line out of range")
    line_start_offset = line_starts[line_no - 1]
    line_content_end = _line_content_end_offset(text, line_start_offset)
    max_column = (line_content_end - line_start_offset) + 1
    if column_no < 1 or column_no > max_column:
        raise ValueError("column out of range")
    return line_start_offset + column_no - 1


def _resolve_comment_char_range(
    *,
    file_text: str,
    line_start: int,
    line_end: int,
    column_start: int,
    column_end: int,
    char_start: Optional[int],
    char_end: Optional[int],
) -> Tuple[int, int]:
    content_len = len(file_text)

    if char_start is not None and char_end is not None:
        if char_start < 0 or char_end < char_start or char_end > content_len:
            raise ValueError("char range is out of bounds")
        return char_start, char_end

    line_starts = _build_line_start_offsets(file_text)
    computed_start = _offset_from_line_column(file_text, line_starts, line_start, column_start)
    computed_end = _offset_from_line_column(file_text, line_starts, line_end, column_end)
    if computed_end < computed_start:
        raise ValueError("computed char range is invalid")
    return computed_start, computed_end
