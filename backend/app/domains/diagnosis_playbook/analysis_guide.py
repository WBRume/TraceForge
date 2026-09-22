"""Reusable case knowledge for ordinary task conversations, without a Runner."""
from copy import deepcopy
import json
import re

from .contracts import PlaybookError, digest
from .models import CasePlaybookLink, PlaybookSpec


def source_snapshot(case):
    return {key: deepcopy(getattr(case, key)) for key in (
        "title", "problem_description", "analysis_process", "root_cause", "solution",
        "code_context", "diagnosis_detail_json",
    )}


def keywords(text):
    """Identifiers/error codes and Chinese bigrams; no fabricated semantic scores."""
    words = re.findall(r"[a-z_][a-z0-9_.:/-]{2,}|\b\d{3,}\b", text.lower())
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        words.extend(phrase[i:i + 2] for i in range(len(phrase) - 1))
    return set(words)


def promote_case(db, case):
    from .service import register_spec, serialize_spec
    source = source_snapshot(case)
    source_digest = digest(source)
    # A distinct version namespace keeps historical physical extraction drafts intact.
    version = "analysis-" + source_digest.split(":")[1][:20]
    detail = source["diagnosis_detail_json"] or {}
    chain = detail.get("call_chain", []) if isinstance(detail, dict) else []
    if not isinstance(chain, list):
        chain = []
    context = {"source_case_id": case.id, "source_digest": source_digest,
               "problem": case.problem_description or "", "analysis": case.analysis_process or "",
               "root_cause": case.root_cause or "", "solution": case.solution or "",
               "call_chain": chain, "code_context": source["code_context"] or "",
               "related_code": detail.get("code_context", []) if isinstance(detail, dict) else [],
               "fix_code": detail.get("fix_code", "") if isinstance(detail, dict) else "",
               "evidence_chain": detail.get("evidence_chain", "") if isinstance(detail, dict) else ""}
    steps = [
        {"id": "symptoms", "objective": "对照历史症状，梳理当前日志、堆栈、时间线和缺失信息。"},
        {"id": "call_chain", "objective": "沿历史调用链逐节点核对当前代码、入参、返回值和异常传播，标明链路差异。"},
        {"id": "hypotheses", "objective": "从调用链、依赖和运行条件提出多个根因假说，列出支持证据、反证和验证方法。"},
        {"id": "conclusion", "objective": "给出根因判断、置信度、修复建议和待验证项；总结可复用经验。"},
    ]
    chain_steps = []
    for index, node in enumerate(chain[:28]):
        if not isinstance(node, dict):
            continue
        label = ".".join(str(node.get(key) or "") for key in ("module", "function")).strip(".")
        location = str(node.get("file_path") or node.get("file") or "")
        chain_steps.append({"id": f"chain_{index + 1}", "objective":
            f"核对调用链节点 {index + 1}：{label or location or '待确认节点'} {location}。"
            f"历史线索：{node.get('description') or '待补充'}。"
            "检查当前入参、返回值、异常传播和上下游证据，说明与历史场景的差异。"})
    if chain_steps:
        steps[2:2] = chain_steps
    spec = {"apiVersion": "traceforge.dev/troubleshooting/v1", "kind": "TroubleshootingPlaybook",
        "metadata": {"id": "case-" + case.id, "version": version, "title": case.title,
                     "taskType": "DIAGNOSIS", "sourceCaseRefs": [case.id]},
        "match": {"symptoms": sorted(keywords(case.title + " " + (case.problem_description or "")))[:80]},
        "execution": {"mode": "ANALYSIS_GUIDE"}, "context": context, "stages": steps}
    row = register_spec(db, case.workspace_id, spec)
    link = db.query(CasePlaybookLink).filter_by(case_id=case.id, spec_id=row.id, source_run_id=None).first()
    if not link:
        link = CasePlaybookLink(case_id=case.id, spec_id=row.id, revision_json={
            "kind": "CASE_PROMOTION", "source": source, "source_digest": source_digest,
            "spec_candidate": spec, "validation_state": "SCHEMA_VALID", "unresolved_inputs": [],
        })
        db.add(link)
        db.flush()
    return {"spec": serialize_spec(row), "revision": {**link.revision_json, "linked_spec_id": row.id}}


def recommend(db, ws_id, text, *, keyword=""):
    from .service import serialize_spec
    query = keywords(text)
    rows = db.query(PlaybookSpec).filter_by(workspace_id=ws_id).order_by(PlaybookSpec.created_at.desc(), PlaybookSpec.id).all()
    items, seen = [], set()
    for row in rows:
        if row.spec_key in seen:
            continue
        seen.add(row.spec_key)
        spec = row.spec_json["spec"]
        searchable = " ".join((spec["metadata"]["title"], row.spec_key,
                               json.dumps(spec.get("context", {}), ensure_ascii=False),
                               json.dumps(spec.get("match", {}), ensure_ascii=False))).lower()
        if any(term not in searchable for term in keyword.lower().split()):
            continue
        terms = keywords(spec["metadata"]["title"] + " " + json.dumps(spec.get("context", {}), ensure_ascii=False))
        terms.update(str(s).lower() for s in spec.get("match", {}).get("symptoms", []))
        matches = sorted(query & terms, key=lambda value: (-len(value), value))
        items.append({**serialize_spec(row), "reasons": matches[:8], "score": len(matches),
                      "requires_environment_probe": False, "usage": "ANALYSIS_GUIDE"})
    return sorted(items, key=lambda item: -item["score"])


def task_binding(db, workspace_id, spec_id):
    row = db.query(PlaybookSpec).filter_by(id=spec_id, workspace_id=workspace_id).first()
    if row is None:
        raise PlaybookError("PLAYBOOK_NOT_FOUND", status=404)
    spec = row.spec_json["spec"]
    return {"spec_id": row.id, "spec_digest": row.spec_digest, "version": row.version,
            "title": spec["metadata"]["title"], "usage": "ANALYSIS_GUIDE",
            "context": {"summary": spec.get("context", {}).get("summary", "")},
            "steps": [{"id": step["id"], "objective": step["objective"]} for step in spec["stages"]]}


def methodology_binding(binding):
    value = {k: deepcopy(v) for k, v in binding.items() if k not in {'context', 'source_case_refs'}}
    value['context'] = {'summary': binding.get('context', {}).get('summary', '')}
    return value


def prompt_suffix(task):
    binding = (task.task_meta_json or {}).get("diagnosis_playbook_guide")
    if not binding:
        return ""
    methodology = methodology_binding(binding)
    return ("\n\n已选择诊断规程（可复用定位方法论）：\n" + json.dumps(methodology, ensure_ascii=False)
            + "\n将规程的方法应用于当前任务，从多个角度提出可证伪的根因假说。"
            "根据当前日志、代码和观察取证，区分已知证据、推断和待验证项。"
            "规程不是当前故障的既定答案；分析指引不会自动启动物理实验或采纳修复。")
