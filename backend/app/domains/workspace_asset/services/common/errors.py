"""Workspace Asset 领域统一业务异常。

Requirement 写入、Task 过程资产写入共享同一个异常形状：message +
``status_code``，由路由层统一翻译为 ``HTTPException``。
"""

from __future__ import annotations


class WorkspaceAssetError(Exception):
    """带 HTTP 状态码的领域业务错误。"""

    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
