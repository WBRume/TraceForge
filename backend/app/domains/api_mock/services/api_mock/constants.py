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
JOB_LOG_MAX_LINES = 240
JOB_LOG_MAX_LINE_LEN = 1200
JOB_EVENT_MAX_ITEMS = 360
JOB_EVENT_TEXT_MAX_LEN = 4000
AUTO_MOCK_JOB_TYPE = "AUTO_GENERATE_MOCK_CASES"
SYNC_MAX_FIX_ATTEMPTS = 5
