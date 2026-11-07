"""
API MOCK Constants.
"""

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
IGNORED_DIR_NAMES = {
    ".git",
    ".idea",
    ".vscode",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".claude",
    ".agents",
    ".sdd",
}
IGNORED_FILE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
    ".tmp",
    ".swp",
}
SCAN_FILE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".java",
    ".go",
    ".php",
    ".rb",
    ".cs",
}
AUTO_MOCK_JOB_TYPE = "AUTO_GENERATE_MOCK_CASES"
