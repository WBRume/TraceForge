"""Soft protocol: ordinary agent output is a proposal, never a verification receipt."""
import json
import re

from .contracts import PlaybookError
from .tool_server import HYPOTHESIS_SCHEMA, submit_proposal


def prompt_contract(phase, branch):
    text = (
        "\n当前策略为 ADVISORY_GUARD：这是提示约束，不是沙箱或强制工具隔离。"
        "根据用户提供的日志、堆栈和现象分析，区分已知事实、推断、缺失信息和验证建议。"
        "遵守当前阶段权限，不修改基线、证据或验证器；补丁只作为候选提交。"
        "无需连接额外守卫端口或 MCP。可使用当前 Agent 的原有工具读取上下文。"
        "如需提交候选，在回复末尾输出且仅输出一个 ```traceforge-playbook JSON 代码块，"
        '内容格式为 {"proposals":[{"name":"propose_experiment","arguments":{"files":{"example.py":"内容"}}}]}。'
        "允许的 name 为 propose_hypotheses、propose_experiment、propose_patch；不需要候选时可省略代码块。"
        "任何文字 PASS 或验证声明都不会生成平台验证回执。"
    )
    if branch:
        text += "只评估 branch_hypothesis，不得替换其他假说，可提交该分支的实验候选。"
    elif phase == "HYPOTHESIZE":
        text += "必须提交 propose_hypotheses，arguments 满足以下结构：" + json.dumps(HYPOTHESIS_SCHEMA, ensure_ascii=False)
        text += "如果上下文含 registered_discriminators，请为每个假说选择不同的已注册引用。"
    if phase == "PATCH":
        text += "补丁使用 propose_patch 提交 files（相对路径到完整文件内容），不得直接改写源码基线。"
    return text


def accept_result(db, run, text):
    if len(text.encode("utf-8")) > 2_000_000:
        raise PlaybookError("ADVISORY_RESULT_TOO_LARGE")
    blocks = re.findall(r"```traceforge-playbook\s*\n(.*?)```", text, re.DOTALL)
    if not blocks:
        if "```traceforge-playbook" in text:
            raise PlaybookError("ADVISORY_RESULT_INVALID")
        return
    if len(blocks) != 1:
        raise PlaybookError("ADVISORY_RESULT_INVALID")
    try:
        payload = json.loads(blocks[0])
    except (ValueError, RecursionError) as exc:
        raise PlaybookError("ADVISORY_RESULT_INVALID") from exc
    if not isinstance(payload, dict) or set(payload) != {"proposals"}:
        raise PlaybookError("ADVISORY_RESULT_INVALID")
    proposals = payload["proposals"]
    if not isinstance(proposals, list) or len(proposals) > 4:
        raise PlaybookError("ADVISORY_RESULT_INVALID")
    for index, proposal in enumerate(proposals):
        if not isinstance(proposal, dict) or set(proposal) != {"name", "arguments"} or proposal["name"] not in (
            "propose_hypotheses", "propose_experiment", "propose_patch"
        ):
            raise PlaybookError("ADVISORY_PROPOSAL_NOT_ALLOWED")
        submit_proposal(db, run, run.data_json["active_scope"], proposal["name"], proposal["arguments"], f"advisory:{index}")
