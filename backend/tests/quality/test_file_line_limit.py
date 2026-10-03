"""Keep the Python file size gate in the regular backend test suite."""

from check_file_lines import check_file_lines


def test_python_files_do_not_exceed_1500_lines():
    assert check_file_lines() == 0, "单文件行数门禁未通过：需要重构超限的 Python 文件。"
