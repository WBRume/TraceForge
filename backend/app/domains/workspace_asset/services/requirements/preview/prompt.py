"""Requirement AI preview 的 prompt 构建与 AI 输出解析。

prompt 固化拆分边界（不为拆而拆、不创建 Task/Coverage/Evidence）；
AI 返回文本统一在此解析为标准 preview item 结构。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.domains.workspace_asset.services.common.primitives import (
    clean_optional,
    normalize_list,
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
    source_kind: Optional[str],
    source_ref: Optional[str],
    source_uri: Optional[str],
    file_name: Optional[str],
) -> str:
    return (
        "你是 SDD-Native Workspace Assets 的 Requirements 拆分助手。\n"
        "目标：把输入需求整理成可追踪 Requirement 预览项，并为后续创建 Task 生成提示词。\n\n"
        "硬性边界：\n"
        "1. 只输出 JSON，不要输出 Markdown 解释。\n"
        "2. 只做 Requirement 拆分，不创建 Task，不创建 Coverage，不创建 Evidence，不标记 Verified。\n"
        "3. 不修改原文业务含义，不减少文档内容。\n"
        "4. 不要为了拆分而拆分：如果输入已经是一条清晰、短小、可独立追踪的需求，必须只返回 1 个 item。\n"
        "5. 只有当原文明确包含多个可独立实现、独立验收、独立追踪的需求时，才拆成多条。\n"
        "6. 如果拆成多条，每条都必须保留理解该需求所需的背景；允许复制公共背景到多个条目。\n"
        "7. task_prompt 仅供后续创建 Task 使用，不能暗示平台会自动提交代码。\n\n"
        "输出 JSON 格式：\n"
        "{\n"
        '  "items": [\n'
        "    {\n"
        '      "title": "需求标题",\n'
        '      "body": "完整需求正文，保留必要背景",\n'
        '      "acceptance_criteria": ["验收标准，可为空数组"],\n'
        '      "priority": null,\n'
        '      "source_ref": "来源段落或编号",\n'
        '      "source_metadata": {"split_reason": "拆分理由"},\n'
        '      "task_prompt": "后续创建 Task 时可使用的实现提示词"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
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


def extract_json_object(text: str) -> Dict[str, Any]:
    candidate = str(text or "").strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"\s*```$", "", candidate).strip()
    if not (candidate.startswith("{") and candidate.endswith("}")):
        match = re.search(r"\{[\s\S]*\}", candidate)
        if match:
            candidate = match.group(0).strip()
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("AI preview response must be a JSON object")
    return parsed


def normalize_ai_preview_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("AI preview response must include an items array")

    items: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            continue
        title = clean_optional(raw.get("title"), limit=300)
        body = clean_optional(raw.get("body"))
        if not title:
            title = clean_optional(str(body or "").splitlines()[0] if body else None, limit=300)
        if not title:
            continue
        source_metadata = raw.get("source_metadata") if isinstance(raw.get("source_metadata"), dict) else {}
        task_prompt = clean_optional(raw.get("task_prompt") or raw.get("taskPrompt"))
        if task_prompt:
            source_metadata = {**source_metadata, "task_prompt": task_prompt}
        source_metadata = {
            **source_metadata,
            "ai_split": True,
            "ai_segment_index": index,
        }
        items.append(
            {
                "title": title,
                "body": body,
                "acceptance_criteria": normalize_list(raw.get("acceptance_criteria") or raw.get("acceptanceCriteria")),
                "priority": clean_optional(raw.get("priority"), limit=40),
                "source_ref": clean_optional(raw.get("source_ref") or raw.get("sourceRef"), limit=300) or f"ai:{index + 1}",
                "source_metadata": source_metadata,
                "order_index": index,
            }
        )
    if not items:
        raise ValueError("AI preview did not produce valid Requirement preview items")
    return items


def coalesce_simple_import_preview_items(
    *,
    markdown: str,
    file_name: Optional[str],
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """import preview 防过度拆分：AI 给出多条但原文明显是单条需求时收敛为 1 条。"""
    if len(items) <= 1 or not looks_like_single_requirement(markdown):
        return items
    first_item = items[0]
    source_metadata = first_item.get("source_metadata") if isinstance(first_item.get("source_metadata"), dict) else {}
    task_prompt = clean_optional(source_metadata.get("task_prompt")) or clean_optional(
        first_item.get("task_prompt")
    ) or f"Implement Requirement: {direct_import_title(file_name or 'Requirement', markdown)}"
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
