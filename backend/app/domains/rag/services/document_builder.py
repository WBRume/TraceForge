"""
RAG 标准文档构建器。

当前只构建已入库案例（`SddCase`）的终态知识文档。

审批通过后如果用户修改了定位结果，可传入最新 `SddDiagnosisResult`，
用最新结论覆盖构建内容，但仍复用同一 `doc_key=case:{case_id}`。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.domains.case_center.models.case import CaseCategory, SddCase
from app.domains.rag.schemas import RagChunk, RagDocument, RagVisibility


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text or ""


def _json_text(value: Any, *, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


def _call_chain_text(call_chain: Any) -> str:
    if not call_chain:
        return ""
    if isinstance(call_chain, str):
        return call_chain.strip()
    try:
        rows = list(call_chain or [])
    except TypeError:
        return str(call_chain)
    parts = []
    for idx, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            parts.append(f"{idx}. {item}")
            continue
        module = _text(item.get("module"))
        function = _text(item.get("function"))
        description = _text(item.get("description"))
        prefix = f"{idx}. "
        if module and function:
            prefix += f"{module}.{function}"
        elif module:
            prefix += module
        elif function:
            prefix += function
        if description:
            prefix += f" - {description}"
        parts.append(prefix)
    return "\n".join(parts)


def _code_context_items_text(code_context: Any) -> str:
    if not code_context:
        return ""
    if isinstance(code_context, str):
        return code_context.strip()
    try:
        rows = list(code_context or [])
    except TypeError:
        return str(code_context)
    parts = []
    for idx, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            parts.append(f"{idx}. {item}")
            continue
        file_path = _text(item.get("file_path"))
        start_line = item.get("start_line")
        end_line = item.get("end_line")
        snippet = _text(item.get("snippet"))
        note = _text(item.get("note"))
        location = file_path
        if start_line is not None:
            location += f":{start_line}"
            if end_line is not None:
                location += f"-{end_line}"
        head = f"{idx}. {location}" if location else f"{idx}."
        if note:
            head += f" ({note})"
        parts.append(head)
        if snippet:
            parts.append(snippet)
    return "\n".join(parts)


def _diagnosis_analysis_text(diagnosis_result: Any) -> str:
    if diagnosis_result is None:
        return ""
    parts: List[str] = []
    evidence = _text(getattr(diagnosis_result, "evidence_chain", None))
    if evidence:
        parts.append(evidence)
    chain = _call_chain_text(getattr(diagnosis_result, "call_chain_json", None))
    if chain:
        parts.append(chain)
    confidence = getattr(diagnosis_result, "confidence", None)
    if confidence is not None:
        parts.append(f"置信度: {confidence}%")
    return "\n\n".join(parts)


def _diagnosis_solution_text(diagnosis_result: Any) -> str:
    if diagnosis_result is None:
        return ""
    parts: List[str] = []
    suggestion = _text(getattr(diagnosis_result, "fix_suggestion", None))
    if suggestion:
        parts.append(suggestion)
    fix_code = _text(getattr(diagnosis_result, "fix_code", None))
    if fix_code:
        parts.append("修复代码:\n" + fix_code)
    return "\n\n".join(parts)


def _diagnosis_detail(diagnosis_result: Any, case: SddCase) -> Any:
    if diagnosis_result is None:
        return case.diagnosis_detail_json
    return {
        "similar_cases": getattr(diagnosis_result, "similar_cases_json", None) or [],
        "call_chain": getattr(diagnosis_result, "call_chain_json", None) or [],
        "code_context": getattr(diagnosis_result, "code_context_json", None) or [],
        "fix_code": getattr(diagnosis_result, "fix_code", None),
    }


def _review_summary(case: SddCase) -> str:
    records = list(case.review_records or [])
    if not records:
        return ""
    parts = []
    for record in records:
        action = _text(record.action)
        comment = _text(record.comment)
        if comment:
            parts.append(f"- {action}: {comment}")
    return "\n".join(parts)


def _build_content(case: SddCase, diagnosis_result: Any = None) -> str:
    analysis = _text(case.analysis_process)
    if diagnosis_result is not None:
        analysis = _diagnosis_analysis_text(diagnosis_result) or analysis
    root_cause = _text(getattr(diagnosis_result, "root_cause", None) or case.root_cause)
    solution = _text(case.solution)
    if diagnosis_result is not None:
        solution = _diagnosis_solution_text(diagnosis_result) or solution
    code_context = _text(case.code_context)
    if diagnosis_result is not None:
        ctx = _code_context_items_text(getattr(diagnosis_result, "code_context_json", None))
        if ctx:
            code_context = "\n\n".join(part for part in [code_context, ctx] if part)
    detail = _diagnosis_detail(diagnosis_result, case)

    sections: List[tuple[str, str]] = [
        ("问题描述", _text(case.problem_description)),
        ("产品/版本/局点", " / ".join(
            part for part in [
                _text(case.product_name),
                _text(case.product_version),
                _text(case.site_name),
            ] if part
        )),
        ("分析过程", analysis),
        ("根因", root_cause),
        ("解决方案", solution),
        ("代码上下文", code_context),
        ("诊断明细", _json_text(detail)),
        ("对话快照摘要", _json_text(
            case.conversation_snapshot_json,
            fallback=_text(case.conversation_snapshot_json),
        )),
        ("评审意见", _review_summary(case)),
    ]
    parts = []
    for heading, body in sections:
        if body:
            parts.append(f"## {heading}\n\n{body}")
    return "\n\n".join(parts)


def _build_chunks(case: SddCase, diagnosis_result: Any = None) -> List[RagChunk]:
    chunks: List[RagChunk] = []
    root_cause = _text(getattr(diagnosis_result, "root_cause", None) or case.root_cause)
    sections: List[tuple[str, str]] = [
        ("问题描述", _text(case.problem_description)),
        ("分析过程", _text(case.analysis_process) if diagnosis_result is None else _diagnosis_analysis_text(diagnosis_result)),
        ("根因", root_cause),
        ("解决方案", _text(case.solution) if diagnosis_result is None else _diagnosis_solution_text(diagnosis_result)),
        ("代码上下文", _text(case.code_context)),
        ("诊断明细", _json_text(_diagnosis_detail(diagnosis_result, case))),
    ]
    for heading, body in sections:
        if body:
            chunks.append(
                RagChunk(
                    id=f"{case.id}:{heading.lower().replace('/', '-')}",
                    text=body,
                    heading=heading,
                )
            )
    return chunks


def build_case_document(
    case: SddCase,
    *,
    version: int = 1,
    diagnosis_result: Any = None,
) -> RagDocument:
    visibility = (
        RagVisibility.PUBLIC.value
        if case.category == CaseCategory.PUBLIC.value
        else RagVisibility.WORKSPACE.value
    )
    metadata: Dict[str, Any] = {
        "case_id": case.id,
        "source_task_id": case.source_task_id,
        "product_name": case.product_name,
        "product_version": case.product_version,
        "site_name": case.site_name,
        "category": case.category,
        "priority": case.priority,
        "approved_at": case.reviewed_at.isoformat() if case.reviewed_at else None,
        "reviewer_id": None,
        "review_round": case.review_round,
    }
    # 取最近一条 APPROVE 记录的 reviewer_id；若无则留空。
    for record in reversed(list(case.review_records or [])):
        if str(record.action or "").upper() == "APPROVE":
            metadata["reviewer_id"] = record.reviewer_id
            break

    return RagDocument(
        doc_id=f"rag:case:{case.id}",
        source_type="case",
        source_id=case.id,
        workspace_id=case.workspace_id,
        namespace="knowledge",
        visibility=visibility,
        status="published",
        version=version,
        title=_text(case.title),
        content=_build_content(case, diagnosis_result),
        metadata=metadata,
        chunks=_build_chunks(case, diagnosis_result),
    )