from app.domains.skill.services.skill_service import _resolve_comment_char_range


def test_resolve_comment_char_range_uses_client_offsets_when_valid():
    start, end = _resolve_comment_char_range(
        file_text="alpha\nbeta",
        line_start=1,
        line_end=1,
        column_start=1,
        column_end=2,
        char_start=2,
        char_end=5,
    )
    assert start == 2
    assert end == 5


def test_resolve_comment_char_range_computes_offsets_from_line_columns():
    text = "hello\nworld\n!"
    start, end = _resolve_comment_char_range(
        file_text=text,
        line_start=1,
        line_end=2,
        column_start=2,
        column_end=4,
        char_start=None,
        char_end=None,
    )
    # "ello\nwor"
    assert text[start:end] == "ello\nwor"


def test_resolve_comment_char_range_rejects_out_of_bound_client_offsets():
    try:
        _resolve_comment_char_range(
            file_text="abc",
            line_start=1,
            line_end=1,
            column_start=1,
            column_end=2,
            char_start=1,
            char_end=99,
        )
    except ValueError as exc:
        assert "char range is out of bounds" in str(exc)
    else:
        raise AssertionError("expected ValueError")
