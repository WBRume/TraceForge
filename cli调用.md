# 真实 Claude CLI 桥接对接结果汇总

## 完成的工作内容

本次更新彻底将原本的 **Mock 及基于 Wexpect PTY** 的桥接方案替换为 **基于 asyncio subprocess 解析 NDJSON stream-json 事件流** 的真实 CLI 方案。在此过程中，所有与 Claude Code CLI 的直接交互逻辑和前后端数据展示机制被重新设计。

### 1. 后端重新设计

- **[claude_bridge.py](file:///g:/proj/SDD-native/backend/app/engine/claude_bridge.py)**:
  - 新增了 [SubprocessCliBridge](file:///g:/proj/SDD-native/backend/app/engine/claude_bridge.py#49-190) 引擎。
  - 使用了 `--output-format stream-json --verbose` 等参数启动真实的 `claude` CLI。
  - 异步处理 CLI 输出，逐行解析 [system](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#159-172)、[assistant](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#173-233) (包括 [thinking](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#106-111), `text`, [tool_use](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#112-118), `tool_result`) 以及 [result](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#133-140) 事件。
  - 支持了 `--resume <session_id>`，以同一进程实现多轮自然语言追问。
  
- **[workflow_engine.py](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py)**:
  - 移除了所有固定 sleep 模拟的伪造流程。
  - 将事件拦截到 [WorkflowEngine](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#38-319) 引擎中。通过 `_dispatch_event` 解析 CLI 输出事件并分别构建相应的 WebDriver Schema（`chat_message`, [thinking](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#106-111), [tool_use](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#112-118), [status](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#119-124), `hitl_request`）。
  - 实现基于 [session_id](file:///g:/proj/SDD-native/backend/app/engine/claude_bridge.py#187-190) 的状态持久化（引擎热部署），允许用户发送消息追加到同一个 session 会话。

- **[routers/task.py](file:///g:/proj/SDD-native/backend/app/routers/task.py) 与 [websocket.py](file:///g:/proj/SDD-native/backend/app/schemas/websocket.py)**:
  - 创建新的 CLI session 时不再是丢后台而是捕获 `prompt` 传入引擎直接启动 [WorkflowEngine](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#38-319)。
  - WebSocket 消息类型扩展了 [WSThinkingPayload](file:///g:/proj/SDD-native/backend/app/schemas/websocket.py#60-63)、[WSToolUsePayload](file:///g:/proj/SDD-native/backend/app/schemas/websocket.py#66-71)、[WSToolResultPayload](file:///g:/proj/SDD-native/backend/app/schemas/websocket.py#74-79)。
  
- **[config.py](file:///g:/proj/SDD-native/backend/app/config.py)**:
  - `SDD_CLI_MODE` 变量的默认值已改为 `"real"`。

### 2. 前端 ChatView 彻底改造

页面布局从大一统聊天气泡拆分为三块独立的展示逻辑：

1. **置顶富文本卡片区 (`pinned-cards-area`)**: 不随对话气泡滚动，置于顶部。主要展示：
   - 当前正在执行任务的状态（开始、失败、完成、耗时及金额 cost）。
   - Agent 发出的 `AskUserQuestion` (即 HITL 人工确认) 卡片（点击选项或输入后卡片消失但后端会响应）。
   - **Thinking 展开面板**（折叠状，用于查看 AI 的深思内容）。
   
2. **纯粹自然语言气泡区 (`chat-history`)**: 对话列表中仅展示：
   - 用户发送的文本（User prompt）。
   - Agent 输出的纯自然语言 `text`（Assistant message）。
   - 绝不包裹工具执行、失败异常等大块终端信息。
   
3. **独立终端日志折叠面板 (`terminal-sidebar`)**: 使用单独的 Sidebar 以深色终端排版模式展示一切底层机器执行的内容：
   - 所有的 [tool_use](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#112-118) (工具调用名及入参内容)。
   - 所有的 `tool_result` (bash / read / grep 等工具执行返回值)。
   - 所有的原始日志 ([log](file:///g:/proj/SDD-native/backend/app/engine/workflow_engine.py#61-77))。
   
## 如何测试

由于 `claude` (Claude Code) 和 `npm`/`python uvicorn` 的环境因素，无法代理启动完整的带参驻留后台服务，请执行以下命令验证能力：

```bash
# 1. 启动后端
cd backend
python -m uvicorn app.main:app --reload --port 8000

# 2. 启动前端
cd frontend
npm run dev
```

1. 在浏览器打开工作区，新建任务并输入 `prompt`。
2. 点击 **Start Engine**，观察顶部的 **初始化与执行状态卡片**、如果遇到 `AskUserQuestion` 工具的拦截请正常填入拒绝或接受。
3. 纯净对话框仅会看到正常的响应内容。
4. 点开右上角的 `Terminal` 图标右侧抽屉，观察终端工具的执行明细流水。
5. 等待任务完成后，可以继续在下方输入框发送额外指令测试多轮对话。
