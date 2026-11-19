"""Context builder for AI jobs."""

from __future__ import annotations


def build_asset_thread_prompt(
    *,
    task_name: str,
    document_name: str,
    document_version_label: str,
    block_id: str,
    thread_id: str,
    project_path: str,
    selected_text: str,
    anchor_block_text: str,
    neighbor_text: str,
    history_lines: list[str],
    manual_prompt: str | None,
    selection_location: str = "",
) -> str:
    manual = (manual_prompt or "").strip()
    filtered_history = [
        line for line in (history_lines or []) if not str(line or "").strip().lower().startswith("[ai]")
    ]
    history_text = "\n".join(filtered_history).strip() if filtered_history else "(暂无)"
    instructions = (
        "你正在参与需求文档的选区评审。以实际选区和所在表格行回答当前问题。\n"
        "如果多处出现相同文字，使用评审选区位置区分。同表的其他行只提供背景。\n"
        "用户要求只回答选中行时，答案和依据都只引用该行，省略其他行及对比说明。\n"
        "回答文档含义、阈值、条件和动作时，直接引用相应条款或实际选中行，无需搜索仓库。\n"
        "问题涉及实现时再核对代码证据，并把文档要求与实现事实分别说明。\n"
        if selection_location
        else (
            "你是 SDD 的资深技术方案助手，当前固定为 solution_mode（方案释疑模式）。\n"
            "目标是给出可执行、可落地的方案，代码事实优先，但不强依赖代码存在。\n"
            "当前会话已基于基座完成需求文档加载，禁止重复读取需求文档全文或描述读取过程。\n"
            "禁止输出“我将先查阅/让我先读取”等过程描述；禁止反问用户。\n"
            "禁止输出“无法确定/证据不足后不回答”的检索式结论。\n"
            "优先检索指定项目代码目录中的事实证据。\n"
            "若代码目录为空、无相关实现或检索不到直接证据：不要停在“无法确定”，改为基于文档锚点与讨论历史给出可执行方案。\n"
            "代码证据优先级高于文档描述；文档用于业务约束与方案兜底。\n"
            "当代码证据缺失时，必须在“风险与验证”中明确写出代码侧不确定点。\n"
        )
    )
    output_requirements = (
        "直接回答用户的问题，说明依据。只在问题需要时提供建议和验证步骤。"
        if selection_location
        else (
            "1) 先给“方案结论”：一句话直接回答用户要采纳的答案/技术方案/选型。\n"
            "2) 再给“依据”：优先引用项目代码路径与行号；若无代码证据，引用锚点文本与讨论要点。\n"
            "3) 再给“落地方案”：3-5 条可执行步骤，聚焦实现，不写检索过程。\n"
            "4) 最后给“关键风险与验证点”（最多 3 条），只写风险与验证，不写假设清单。"
        )
    )
    location_section = f"评审选区位置:\n{selection_location}\n\n" if selection_location else ""
    return (
        f"{instructions}\n"
        f"任务名称:\n{task_name or '(未命名任务)'}\n\n"
        f"文档基座上下文:\n- 文件名: {document_name or '(未知)'}\n"
        f"- 版本: {document_version_label or '(未知版本)'}\n"
        f"- 讨论线程: {thread_id or '(未知线程)'}\n"
        f"- 锚点块ID: {block_id or '(未知块)'}\n\n"
        f"指定项目代码目录:\n{project_path or '(未知)'}\n\n"
        f"锚点选中文本:\n{selected_text or '(无)'}\n\n"
        f"{location_section}"
        f"所在块全文（仅上下文）:\n{anchor_block_text or '(无)'}\n\n"
        f"附近上下文:\n{neighbor_text or '(无)'}\n\n"
        f"讨论历史:\n{history_text}\n\n"
        f"用户问题:\n{manual or '(无)'}\n\n"
        "输出要求（必须严格遵守）:\n"
        f"{output_requirements}\n\n"
        "风格要求:\n"
        "- 简体中文，精炼，禁止大段表格，禁止无关背景铺陈。\n"
        "- 不要向用户提问，不要让用户补充材料后再回答。"
    ).strip()


def build_resolution_anchor_rewrite_prompt(
    *,
    task_name: str,
    document_name: str,
    document_version_label: str,
    block_id: str,
    thread_id: str,
    anchor_text: str,
    block_context_text: str,
    proposal_text: str,
    selection_mode: bool = False,
) -> str:
    insufficient_line = (
        "若证据不足无法改写：scope=anchor，anchor_text 直接返回锚点选中文本。"
        if selection_mode
        else "若证据不足无法改写：scope=anchor，anchor_text 直接返回锚点原文。"
    )
    return (
        "你是需求文档专家（BRD/PRD）与资深系统工程师（Senior SE）。\n"
        "你的任务是：基于提案文本，仅改写当前锚点对应内容，并严格贴合所在段落上下文语境，"
        "形成可落地、可执行且表述连贯的局部修订稿。\n"
        "当前会话已通过 --resume 继承文档上下文。\n\n"
        "硬性规则（必须遵守）:\n"
        "1) 仅修改锚点范围，不得扩散到无关段落。\n"
        "2) 只能根据锚点原文、所在块上下文、提案文本改写，不得新增未讨论需求，不得猜测。\n"
        "3) 必须根据上下文调整措辞与结构，保证前后语义连贯、术语一致、编号风格一致。\n"
        "4) 调用 submit_document_rewrite 工具交付改写内容与 change_summary。\n"
        "5) 必须输出 scope=anchor，并只填写 anchor_text，document_markdown 留空字符串。\n"
        "6) 禁止向用户提问。\n\n"
        f"{insufficient_line}\n\n"
        f"任务名称:\n{task_name or '(未命名任务)'}\n\n"
        f"文档:\n- 名称: {document_name or '(未知)'}\n- 版本: {document_version_label or '(未知)'}\n"
        f"- 线程: {thread_id or '(未知)'}\n- 锚点块: {block_id or '(未知)'}\n\n"
        f"锚点选中文本:\n{anchor_text or '(空)'}\n\n"
        f"所在块全文（仅上下文）:\n{block_context_text or '(无)'}\n\n"
        f"提案文本（以此为准执行改写）:\n{proposal_text or '(空)'}\n"
    ).strip()


def build_resolution_document_rewrite_prompt(
    *,
    task_name: str,
    document_name: str,
    document_version_label: str,
    block_id: str,
    thread_id: str,
    anchor_text: str,
    block_context_text: str,
    proposal_text: str,
) -> str:
    return (
        "你是需求文档专家（BRD/PRD）与资深系统工程师（Senior SE）。\n"
        "你的任务是：基于提案文本，对整篇需求文档进行专业化补充与完善，"
        "产出可直接落地执行的完整需求文档版本。\n"
        "当前会话已通过 --resume 继承文档上下文。\n\n"
        "硬性规则（必须遵守）:\n"
        "1) 全文改写不是只替换锚点：应将提案涉及的变更融合进整篇文档相关章节。\n"
        "2) 保留与提案不冲突的既有内容和结构；对提案涉及章节做补充完善（目标、范围、规则、验收等）。\n"
        "3) 只能根据文档现有内容与提案文本改写，不得编造外部事实。\n"
        "4) 调用 submit_document_rewrite 工具交付改写内容与 change_summary。\n"
        "5) 必须输出 scope=document，并只填写 document_markdown，anchor_text 留空字符串。\n"
        "6) 禁止向用户提问。\n\n"
        "若证据不足无法改写：scope=document，document_markdown 返回当前完整文档（保持不变）。\n\n"
        f"任务名称:\n{task_name or '(未命名任务)'}\n\n"
        f"文档:\n- 名称: {document_name or '(未知)'}\n- 版本: {document_version_label or '(未知)'}\n"
        f"- 线程: {thread_id or '(未知)'}\n- 锚点块: {block_id or '(未知)'}\n\n"
        f"锚点选中文本（仅用于理解变更起点）:\n{anchor_text or '(空)'}\n\n"
        f"所在块全文（仅上下文）:\n{block_context_text or '(无)'}\n\n"
        f"提案文本（以此为准执行改写）:\n{proposal_text or '(空)'}\n"
    ).strip()


def build_resolution_rewrite_prompt(
    *,
    task_name: str,
    document_name: str,
    document_version_label: str,
    block_id: str,
    thread_id: str,
    anchor_text: str,
    block_context_text: str,
    proposal_text: str,
    rewrite_scope: str | None = None,
    selection_mode: bool = False,
) -> str:
    scope = str(rewrite_scope or "").strip().lower()
    if scope == "document":
        return build_resolution_document_rewrite_prompt(
            task_name=task_name,
            document_name=document_name,
            document_version_label=document_version_label,
            block_id=block_id,
            thread_id=thread_id,
            anchor_text=anchor_text,
            block_context_text=block_context_text,
            proposal_text=proposal_text,
        )
    return build_resolution_anchor_rewrite_prompt(
        task_name=task_name,
        document_name=document_name,
        document_version_label=document_version_label,
        block_id=block_id,
        thread_id=thread_id,
        anchor_text=anchor_text,
        block_context_text=block_context_text,
        proposal_text=proposal_text,
        selection_mode=selection_mode,
    )
