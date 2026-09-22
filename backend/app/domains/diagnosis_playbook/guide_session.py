"""Human-reviewed SOP state for advisory task sessions; never a physical receipt."""
from copy import deepcopy
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from app.domains.task.models.task import SddTask
from .contracts import PlaybookError, digest

PHASES = ("PROBE", "HYPOTHESIZE", "REPRODUCE", "PATCH")
TITLES = ("探针采证", "假说与实验", "症状复现", "补丁与回归")


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(min_length=1, max_length=1000)
    observation: str = Field(min_length=1, max_length=10000)


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    claim: str = Field(min_length=1, max_length=2000)
    prediction: str = Field(min_length=1, max_length=4000)
    falsifier: str = Field(min_length=1, max_length=4000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)
    verdict: Literal["UNTESTED", "SUPPORTED", "REFUTED", "INCONCLUSIVE"] = "UNTESTED"
    verdict_reason: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def require_verdict_evidence(self):
        if self.verdict != "UNTESTED" and (not self.evidence or not self.verdict_reason.strip()):
            raise ValueError("Hypothesis verdict requires current evidence and a reason")
        return self


def supported(hypothesis):
    return (hypothesis.get("verdict") == "SUPPORTED" and bool(hypothesis.get("evidence"))
            and bool(str(hypothesis.get("verdict_reason") or "").strip()))


class StageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phase: Literal["PROBE", "HYPOTHESIZE", "REPRODUCE", "PATCH"]
    findings: str = Field(min_length=1, max_length=20000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=40)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=8)
    code: str = Field(default="", max_length=100000)
    language: str = Field(default="text", max_length=30)
    outcome: Literal["NOT_RUN", "OBSERVED", "FAILED"] = "NOT_RUN"
    ready_for_review: bool = False
    root_cause_hypothesis_id: str | None = Field(default=None, max_length=40)


def snapshot(task):
    meta = task.task_meta_json or {}
    guide = meta.get("diagnosis_playbook_guide")
    if not guide:
        raise PlaybookError("GUIDE_NOT_BOUND", status=404)
    state = deepcopy(meta.get("diagnosis_sop") or {})
    if state.get("session_generation") != task.session_generation:
        state = {"version": state.get("version", 0) + 1, "session_generation": task.session_generation,
                 "active_phase": "PROBE", "completed": False, "reports": {}, "hypotheses": [],
                 "confirmations": {}, "commands": {}, "error": None}
    # 主开关（新建任务/启动引擎时设置）：新会话以任务级偏好初始化自动执行
    state.setdefault("auto_run", bool(meta.get("sop_auto_run")))
    state.setdefault("auto_run_by", None)
    state.setdefault("auto_pause_reason", None)
    for hypothesis in state["hypotheses"]:
        hypothesis.setdefault("verdict", "UNTESTED")
        hypothesis.setdefault("verdict_reason", "")
    from .analysis_guide import methodology_binding
    return {"task_id": task.id, "guide": methodology_binding(guide), **state}


def public(task):
    return {key: value for key, value in snapshot(task).items() if key != "commands"}


def save(task, state):
    state = {key: value for key, value in state.items() if key not in {"task_id", "guide"}}
    state["version"] += 1
    task.task_meta_json = {**(task.task_meta_json or {}), "diagnosis_sop": state}
    return public(task)


def command(db, task, request, user_id):
    db.refresh(task, with_for_update=True)
    state = snapshot(task)
    fingerprint = digest({key: value for key, value in request.items() if key != "idempotency_key"})
    key = request["idempotency_key"]
    if key in state["commands"]:
        if state["commands"][key] != fingerprint:
            raise PlaybookError("IDEMPOTENCY_PAYLOAD_CONFLICT", status=409)
        return public(task)
    if request["expected_version"] != state["version"]:
        raise PlaybookError("STATE_VERSION_CONFLICT", status=409)
    from app.domains.ai.models.ai_job import SddAiJob, AiJobStatus, AiJobChannel
    active_job = db.query(SddAiJob.id).filter(SddAiJob.task_id == task.id, SddAiJob.channel == AiJobChannel.TASK_CHAT,
        SddAiJob.status.in_([AiJobStatus.PENDING, AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL,
                           AiJobStatus.TERMINATING, AiJobStatus.ORPHANED])).first()
    if active_job and request["action"] not in {"enable_auto", "disable_auto"}:
        raise PlaybookError("AGENT_TURN_ACTIVE", status=409)
    if state["completed"]:
        raise PlaybookError("SOP_COMPLETED", status=409)
    action, phase = request["action"], state["active_phase"]
    if action in {"enable_auto", "disable_auto"}:
        state.update(auto_run=action == "enable_auto", auto_run_by=user_id, auto_pause_reason=None)
    elif action in {"approve_hypothesis", "exclude_hypothesis", "restore_hypothesis"}:
        if phase != "HYPOTHESIZE":
            raise PlaybookError("HYPOTHESIS_STAGE_REQUIRED", status=409)
        item = next((h for h in state["hypotheses"] if h["id"] == request.get("hypothesis_id")), None)
        if not item:
            raise PlaybookError("HYPOTHESIS_NOT_FOUND", status=404)
        if action == "approve_hypothesis":
            if not item["evidence"]:
                raise PlaybookError("HYPOTHESIS_EVIDENCE_REQUIRED")
            if not supported(item) or item["state"] == "EXCLUDED":
                raise PlaybookError("HYPOTHESIS_NOT_SUPPORTED", status=409)
            for hypothesis in state["hypotheses"]:
                if hypothesis["state"] == "APPROVED":
                    hypothesis["state"] = "PROPOSED"
        item.update(state={"approve_hypothesis": "APPROVED", "exclude_hypothesis": "EXCLUDED",
                           "restore_hypothesis": "PROPOSED"}[action], decided_by=user_id)
    elif action == "advance":
        report = state["reports"].get(phase)
        if state["error"] or not report or not report["ready_for_review"] or not report["evidence"] or report["outcome"] == "FAILED":
            raise PlaybookError("STAGE_EVIDENCE_REQUIRED")
        if phase == "HYPOTHESIZE" and not any(h["state"] == "APPROVED" and supported(h) for h in state["hypotheses"]):
            raise PlaybookError("ROOT_CAUSE_CONFIRMATION_REQUIRED")
        if phase in {"REPRODUCE", "PATCH"} and report["outcome"] != "OBSERVED":
            raise PlaybookError("EXECUTION_OBSERVATION_REQUIRED")
        state["confirmations"][phase] = {"user_id": user_id, "report_digest": digest(report)}
        if phase == "PATCH":
            state["completed"] = True
        else:
            state["active_phase"] = PHASES[PHASES.index(phase) + 1]
    else:
        raise PlaybookError("UNKNOWN_COMMAND")
    state["commands"][key] = fingerprint
    return save(task, state)


def turn_context(task):
    if not (task.task_meta_json or {}).get("diagnosis_playbook_guide"):
        return None
    state = snapshot(task)
    # Control-only changes (e.g. disabling auto-run) must not discard an active report.
    return {"session_generation": task.session_generation,
            "session_revision": task.session_revision, "active_phase": state["active_phase"]}


def prompt(task):
    from .analysis_guide import prompt_suffix
    state = public(task)
    schema = StageReport.model_json_schema()
    return (prompt_suffix(task) + "\n本次 SOP 状态：\n" + json.dumps({k: v for k, v in state.items() if k != "guide"}, ensure_ascii=False)
        + "\n只处理当前 active_phase，不自动跳阶段。按已确认的假说进行后续复现与修复。"
          "回复末尾输出一个 ```traceforge-sop JSON 代码块，符合以下结构：\n" + json.dumps(schema, ensure_ascii=False)
        + "\nevidence 必须引用本次实际读到的文件、日志或执行输出；不得把历史案例作为本次验证证据。"
          "未执行实验时 outcome=NOT_RUN；只有实际观察到目标现象/回归结果才使用 OBSERVED。"
          "hypotheses 在假说阶段提交多个可证伪假说。ready_for_review 只表示材料完整，不代表阶段通过。"
          "每个假说必须填写 verdict 和 verdict_reason：UNTESTED=尚未验证，SUPPORTED=本次证据支持，"
          "REFUTED=本次证据已证伪，INCONCLUSIVE=执行后仍无法判定。除UNTESTED外必须附本次证据和判定理由。"
          "falsifier 是证伪条件，不是已执行结果；实际判定必须写入verdict，不能只写在自然语言结论里。"
          "不要用人工排除代替已证伪；root_cause_hypothesis_id只能指向SUPPORTED假说。"
          "auto_run=true 时由服务端在回合成功结束后检查条件并衔接下一阶段，不依赖用户在线；"
          "假说阶段用 root_cause_hypothesis_id 明确推荐一个有本次证据支持的根因，不能确定则留空。"
          "不要把历史案例中等待人工确认的描述当作自动模式必须停下的指令。"
          "每轮仍只处理 active_phase；缺少证据或执行失败必须如实报告，不得自行跳阶段。")


def parse_report(text):
    if len(text) > 200000:
        raise ValueError("报告超过长度限制")
    blocks = re.findall(r"```traceforge-sop\s*\n(.*?)```", text, re.DOTALL)
    if len(blocks) != 1:
        raise ValueError("缺少完整的阶段报告，或出现多个阶段报告")
    return StageReport.model_validate_json(blocks[0]).model_dump()


def accept_result(db, task_id, fence, text, job_id, streamed_text=""):
    task = db.query(SddTask).filter_by(id=task_id).with_for_update().one()
    if not fence or turn_context(task) != fence:
        return None
    state = snapshot(task)
    if state["completed"]:
        return None
    try:
        try:
            report = parse_report(text)
        except (ValueError, ValidationError):
            if not streamed_text:
                raise
            # Some providers return a shortened result while the assistant text is complete.
            report = parse_report(streamed_text)
        if report["phase"] != state["active_phase"]:
            raise ValueError("wrong phase")
        if report["phase"] == "HYPOTHESIZE":
            ids = [h["id"] for h in report["hypotheses"]]
            if len(ids) < 2 or len(set(ids)) != len(ids):
                raise ValueError("hypotheses required")
            previous = {h["id"]: h for h in state["hypotheses"]}
            if any(h.get("decided_by") and h["id"] not in ids for h in previous.values()):
                raise ValueError("human decision removed")
            state["hypotheses"] = [{**h, "state": "PROPOSED", **({"state": previous[h["id"]]["state"],
                "decided_by": previous[h["id"]]["decided_by"]} if h["id"] in previous and previous[h["id"]].get("decided_by") and
                all(previous[h["id"]].get(k) == h[k] for k in ("claim", "prediction", "falsifier", "evidence", "verdict", "verdict_reason")) else {})} for h in report["hypotheses"]]
        state["reports"][report["phase"]] = {**report, "job_id": job_id, "origin": "AGENT_OBSERVATION"}
        state.pop("next_submission", None)
        state["error"] = None
    except (ValueError, ValidationError, RecursionError):
        state.pop("next_submission", None)
        state["error"] = "阶段结果未更新，请重试本阶段排查。"
    return save(task, state)


async def publish(task_id, value):
    from app.domains.ai.schemas.websocket import WSMessage
    from app.domains.websocket.ws.manager import manager
    await manager.send_message_to_room(task_id, WSMessage(type="playbook.guide_updated", payload={"task_id": task_id, "snapshot": value}))


def invalidate_reverted_jobs(task, job_ids):
    if not (task.task_meta_json or {}).get("diagnosis_playbook_guide"):
        return
    state = snapshot(task)
    affected = [phase for phase in PHASES if state["reports"].get(phase, {}).get("job_id") in job_ids]
    if not affected:
        return
    first = PHASES.index(affected[0])
    for phase in PHASES[first:]:
        state["reports"].pop(phase, None)
        state["confirmations"].pop(phase, None)
    if first <= PHASES.index("HYPOTHESIZE"):
        state["hypotheses"] = []
    state.pop("next_submission", None)
    state.update(active_phase=PHASES[first], completed=False, commands={}, error=None,
                 auto_run=False, auto_pause_reason="历史结果已撤回，自动执行已暂停。")
    save(task, state)


def migrate_initial_generation(task):
    """The legacy 0 -> 1 normalization is not a new conversation."""
    meta = task.task_meta_json or {}
    state = deepcopy(meta.get("diagnosis_sop"))
    if state and int(state.get("session_generation") or 0) == 0:
        state["session_generation"] = 1
        state["version"] += 1
        task.task_meta_json = {**meta, "diagnosis_sop": state}
