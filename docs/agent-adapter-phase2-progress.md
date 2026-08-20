# Agent 适配层阶段 2：实施进度

> 状态：进行中  
> 契约基线：docs/agent-adapter-contract.md（v0.2.0）  
> 关联阶段 1 文档：docs/agent-adapter-phase1.md

---

## 已完成

### 1. 契约骨架

新增 `backend/app/agents/`：

```text
backend/app/agents/
├── __init__.py
├── contract.py      # AgentBackend / AgentRunRequest / AgentRunResult / AgentCapabilities
├── events.py        # AgentEvent
├── errors.py        # AgentError 等
├── registry.py      # AGENT_BACKENDS / create_agent_backend / get_agent_backend
└── adapters/
    ├── __init__.py   # register_all()
    ├── mock/
    │   └── mock_adapter.py
    └── claude_code/
        ├── __init__.py
        ├── event_mapper.py
        └── claude_code_adapter.py
```

### 2. MockAdapter

实现统一 `AgentBackend`，支持：

- `run()` 输出统一事件：`session_started` / `thinking` / `text` / `tool_use` / `tool_result` / `result`
- `interrupt()` / `cancel()` / `is_running()` / `close()`
- 声明 `hitl_modes=["turn_based"]`

### 3. ClaudeCodeAdapter

- 内部复用现有 `SubprocessCliBridge` 的进程管理能力
- 通过 `event_mapper.py` 把 Claude NDJSON 流转换为统一 `AgentEvent`
- 实现 `AgentBackend.run()`，同时保留旧 `CliBridgeBase` 兼容方法：
  - `start_session()`
  - `wait()`
  - `session_id` / `process`
- `create_cli_bridge()` 在 real 模式下改为返回 `ClaudeCodeAdapter`，旧调用方不破坏

### 4. WorkflowEngine 统一事件接入

- `WorkflowEngine.run()` 增加 `AgentBackend` 分支：
  - 构造 `AgentRunRequest`
  - 调用 `cli.run(request, self.handle_agent_event)`
  - 从 `AgentRunResult.session_id` 回写会话 ID
- 新增 `handle_agent_event()` 统一事件分发：
  - `session_started` / `text` / `thinking` / `tool_use` / `tool_result`
  - `ask_user` / `usage` / `context_compacted` / `log`
  - `result` / `error`
- 保留旧 `handle_event()` 作为兼容路径，`MockCliBridge` 等旧桥接仍可工作

### 5. 测试与 golden fixtures

新增 `backend/tests/test_agents_adapter.py`，覆盖：

- MockAdapter 统一事件输出
- Claude 事件映射（system/assistant/result/error）
- registry 创建 backend
- 能力不变量（不支持流式文本时不发 `text_delta`）
- golden fixtures：`backend/tests/fixtures/agent_events/` 下 Claude 原始事件样本 → 统一事件断言

快速回归已通过：

```text
tests/test_agents_adapter.py
tests/test_claude_bridge.py
tests/test_logging_system.py
tests/test_websocket_managers.py
tests/test_skill_materialization_atomic_replace.py
```

### 6. 上下文 token 归因修复

- 修复 `tests/test_context_token_service.py` 单独运行时的 SQLAlchemy mapper 初始化问题（补充注册缺失模型：api_mock / asset / dashboard / test_result / workflow / workspace_asset）。
- 修复“上下文 token 归因界面全部 unavailable / 总量 0”：
  - 根因：最近一个被中断、尚未产生 provider usage 的回合会创建最新 snapshot（input/output/total 均为 0），前端再以该 active job 拉取上下文窗口，导致展示 0/unavailable。
  - `context_token_service.get_context_window()` 现在会识别“无可展示 provider token 数据”的快照，并回退到同一任务最近一条带真实 token 用量的历史快照。
  - 前端 `ContextWindowDrawer` 在 `provider_tokens.available=false` 时不再把 0 显示成真实用量，而是显示 unavailable。
- 新增回归测试 `test_context_window_falls_back_to_last_usable_snapshot`。

### 7. OpenCode Spike 与 Adapter 骨架

- 安装 `opencode-ai` `v1.18.19`。
- `opencode run --format json` 在当前 Windows shell 环境失败，`opencode serve` 可用且暴露完整 SSE/HTTP API，因此采用 **Server 模式**。
- 新增 `backend/app/agents/adapters/opencode/`：
  - `event_mapper.py`：`session.next.text/reasoning/tool/step/permission/question` → `AgentEvent`
  - `opencode_adapter.py`：`AgentBackend` 骨架（Server 模式）
  - 注册 `opencode` backend。
- golden fixture：`backend/tests/fixtures/agent_events/opencode_server_events.json`

### 8. DSH Spike 与 Adapter

- PyPI 当前 `deepseek-harness-sdk` 装到 placeholder（`0.0.0.dev0`）；真实 SDK 在 DSH 源码 `python/sdk`，事件 schema 已从官方快照确认。
- **Windows 无法把 DSH SDK 直接放进 requirements**：真实 `deepseek-harness-sdk` 依赖 `deepseek-harness-runtime-bin`，而后者只发布 `manylinux_2_28_x86_64/aarch64` 与 `macosx_14_0_arm64` wheel，没有 Windows wheel。
- 为避免 TraceForge 依赖 DSH 源码仓库，`DSHAdapter` 默认改为 **CLI subprocess 模式**：
  - `dsh --profile headless` 已在源码目录真实调用成功（`好的`）
  - 只要求 PATH 中有 `dsh`，不要求 `deepseek-harness-sdk` 或本地仓库路径
- 新增 `backend/app/agents/adapters/dsh/`：
  - `event_mapper.py`：`assistant/chunk`、`assistant/message`、`tool/call`、`tool/result`、`turn/end` → `AgentEvent`（SDK 模式备用）
  - `dsh_adapter.py`：实现基础 CLI `run()`，capabilities 为 subprocess
  - 注册 `dsh` backend。
- golden fixture：`backend/tests/fixtures/agent_events/dsh_session_sample.jsonl`

### 9. 旧调用点迁移准备

- 新增 `docs/agent-adapter-migration-prep.md`，覆盖 `api_mock / skill_analysis / task_cli_state` 的旧事件 → 统一事件映射与迁移步骤。

---

## 待办

Spike 准备文档：

- [x] OpenCode Spike 准备：`docs/agent-adapter-opencode-spike.md`
- [x] DSH Spike 准备：`docs/agent-adapter-dsh-spike.md`

Spike 执行：

- [x] 执行 OpenCode Spike：
  - 安装/确认 `opencode` CLI
  - 采集 SSE/HTTP 事件样本（`opencode run --format json` 在 Windows 环境失败，改用 Server 模式）
  - 确认 session / thinking / permission / HITL 行为（Server API 完整）
  - 实现 `OpenCodeAdapter` + golden fixtures
- [x] 执行 DSH Spike：
  - 确认 PyPI placeholder 问题与真实 SDK 源码位置
  - 采集官方 `session.event` 样本
  - 确认 `assistant/chunk` / `message` / `tool/call` / `tool/result` / `turn/end`
  - 实现 `DSHAdapter` + golden fixtures
- [ ] OpenCode `run()` HTTP 驱动接线（当前为骨架）
- [x] DSH CLI subprocess `run()` 基础接线（真实 CLI 验证通过）
- [ ] DSH SDK 模式（仅 Linux/macOS 或拿到 Windows runtime wheel 后再启用）
- [ ] 契约测试/CI 化（含 OpenCode/DSH 事件映射已入现有测试）
- [x] 旧调用点迁移技术准备（`docs/agent-adapter-migration-prep.md`）
- [ ] 将 `api_mock` / `skill_analysis` / `task_cli_state` 等旧调用点实际迁移到统一 `AgentBackend`
- [ ] 前端 WS 协议保持不变，必要时增加 `agent` 字段

---

## 风险

- `create_cli_bridge()` real 模式切换为 `ClaudeCodeAdapter` 后，所有旧调用方都会走统一事件路径；真实 CLI 回归需要一次端到端验证。
- `ClaudeCodeAdapter.run()` 尚未实现 HITL 长连接模式，当前仅 `turn_based`。
- OpenCode / DSH 事件 schema 已通过 Spike 确认；OpenCode `run()` 仍需接线到真实 HTTP，DSH 的 SDK 模式在 Windows 上不可用（runtime-bin 无 win wheel）。