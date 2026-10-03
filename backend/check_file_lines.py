"""Enforce the 1500 physical line limit for Python source files."""

import subprocess
import sys
from pathlib import Path

MAX_FILE_LINES = 1500
PROJECT_ROOT = Path(__file__).resolve().parent


def count_lines(content: bytes) -> int:
    """Count physical lines, including comments and blanks, for LF/CRLF/CR."""
    breaks = content.count(b"\n") + content.count(b"\r") - content.count(b"\r\n")
    return breaks + int(bool(content) and not content.endswith((b"\n", b"\r")))


def source_files(project_root: Path) -> list[Path]:
    """Include tracked and new Python files while honoring Git ignore rules."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    names = sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})
    return [
        project_root / name
        for name in names
        if Path(name).suffix.lower() == ".py" and (project_root / name).is_file()
    ]


def check_file_lines(project_root: Path = PROJECT_ROOT) -> int:
    """Report every oversized file and return a nonzero exit code on failure."""
    try:
        files = source_files(project_root)
        violations = []
        for path in files:
            lines = count_lines(path.read_bytes())
            if lines > MAX_FILE_LINES:
                violations.append((path, lines))
    except (OSError, UnicodeError, subprocess.CalledProcessError) as error:
        print(f"[单文件行数门禁] Python 项目无法完成检查：{error}", file=sys.stderr)
        return 1

    if violations:
        print(f"[单文件行数门禁] Python 项目检查失败，上限 {MAX_FILE_LINES} 行。", file=sys.stderr)
        for path, lines in violations:
            name = f"{project_root.name}/{path.relative_to(project_root).as_posix()}"
            print(f"  {name}: {lines} 行，超过 {MAX_FILE_LINES} 行，需要重构。", file=sys.stderr)
        print("请按职责拆分模块，重构到 1500 行以内后重新运行检查。", file=sys.stderr)
        return 1

    print(f"[单文件行数门禁] Python 项目通过：检查 {len(files)} 个源文件，上限 {MAX_FILE_LINES} 行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(check_file_lines())
