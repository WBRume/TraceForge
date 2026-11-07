"""Requirement AI preview 的 prompt 构建与 AI 输出解析。

prompt 固化拆分边界（不为拆而拆、不创建 Task/Coverage/Evidence）；
AI 返回文本统一在此解析为标准 preview item 结构。
"""

from __future__ import annotations

from typing import Any

from app.domains.workspace_asset.services.common.primitives import (
    clean_optional,
)
from app.domains.workspace_asset.services.requirements.segmentation import (
    direct_import_title,
    extract_acceptance_criteria,
    looks_like_single_requirement,
)


def build_requirement_preview_prompt(
    *,
    mode: str,
    markdown: str,
    source_kind: str | None,
    source_ref: str | None,
    source_uri: str | None,
    file_name: str | None,
) -> str:
    return (
        "你是 SDD-Native Workspace Assets 的 Requirements 拆分助手。\n"
        "目标：把输入需求整理成可追踪 Requirement 预览项，并为后续创建 Task 生成提示词。\n\n"
        "硬性边界：\n"
        "1. 调用 submit_requirements 工具提交需求草案。\n"
        "2. 只做 Requirement 拆分，不创建 Task，不创建 Coverage，不创建 Evidence，不标记 Verified。\n"
        "3. 不修改原文业务含义，不减少文档内容。\n"
        "4. 不要为了拆分而拆分：如果输入已经是一条清晰、短小、可独立追踪的需求，必须只返回 1 个 item。\n"
        "5. 只有当原文明确包含多个可独立实现、独立验收、独立追踪的需求时，才拆成多条。\n"
        "6. 如果拆成多条，每条都必须保留理解该需求所需的背景；允许复制公共背景到多个条目。\n"
        "7. task_prompt 仅供后续创建 Task 使用，不能暗示平台会自动提交代码。\n\n"
        f"Preview mode: {mode}\n"
        f"Source kind: {source_kind or 'document'}\n"
        f"Source file: {file_name or ''}\n"
        f"Source ref: {source_ref or ''}\n"
        f"Source uri: {source_uri or ''}\n\n"
        "输入需求正文如下：\n"
        "----- BEGIN REQUIREMENT DOCUMENT -----\n"
        f"{markdown}\n"
        "----- END REQUIREMENT DOCUMENT -----\n"
    )


def coalesce_simple_import_preview_items(
    *,
    markdown: str,
    file_name: str | None,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """import preview 防过度拆分：AI 给出多条但原文明显是单条需求时收敛为 1 条。"""
    if len(items) <= 1 or not looks_like_single_requirement(markdown):
        return items
    first_item = items[0]
    source_metadata = first_item.get("source_metadata") if isinstance(first_item.get("source_metadata"), dict) else {}
    task_prompt = (
        clean_optional(source_metadata.get("task_prompt"))
        or clean_optional(first_item.get("task_prompt"))
        or f"Implement Requirement: {direct_import_title(file_name or 'Requirement', markdown)}"
    )
    return [
        {
            "title": direct_import_title(file_name or "Requirement", markdown),
            "body": markdown,
            "acceptance_criteria": extract_acceptance_criteria(str(markdown or "").splitlines()),
            "priority": clean_optional(first_item.get("priority"), limit=40),
            "source_ref": first_item.get("source_ref") or "ai:1",
            "source_metadata": {
                **source_metadata,
                "ai_preview": True,
                "ai_split": False,
                "original_ai_item_count": len(items),
                "split_decision": "kept_single_simple_requirement",
                "task_prompt": task_prompt,
            },
            "order_index": 0,
        }
    ]


def normalize_ai_preview_items(payload) -> list[dict[str, Any]]:
    """Map the validated artifact to persistence fields without coercion or omission."""
    from app.agents.domain_tools.contracts import RequirementSubmission

    artifact = (
        payload
        if isinstance(payload, RequirementSubmission)
        else RequirementSubmission.model_validate(payload, strict=True)
    )
    return [
        {
            "title": item.title,
            "body": item.body,
            "acceptance_criteria": item.acceptance_criteria,
            "priority": item.priority,
            "source_ref": item.source_ref or f"ai:{index + 1}",
            "source_metadata": {
                **item.source_metadata.model_dump(),
                "task_prompt": item.task_prompt,
                "ai_split": True,
                "ai_segment_index": index,
            },
            "order_index": index,
        }
        for index, item in enumerate(artifact.items)
    ]
