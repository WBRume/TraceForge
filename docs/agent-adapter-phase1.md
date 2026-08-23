# Agent 适配层阶段 1：设计与技术盘点

> 状态：阶段 1 定稿（同步契约 v0.2.0）
> 目标：将 TraceForge 当前“Claude CLI Bridge”抽象为可扩展的 `AgentBackend` 适配层，支持 claude-code / opencode / dsh 等 Agent 套件。
> 范围：本阶段只做契约设计、现状盘点、候选协议调研，不实现代码。
> 契约文档：[agent-adapter-contract.md](./agent-adapter-contract.md)（v0.2.0，以该文档为准；后续变更走契约版本管理）

---

## 1. 背景与目标

当前 TraceForge 已经能用“任务 Chat 窗口 + FastAPI + Claude Code CLI”跑通完整链路：

```text
Vue ChatView
    │ WebSocket
    ▼
FastAPI /ws/task/{task_id}
    │ AI Job Queue
    ▼
WorkflowEngine
    │
    ▼
SubprocessCliBridge (claude CLI)
    │ NDJSON stream-json
    ▼
Claude Event Adapter → WebSocket 推送
```

但现有实现把下面几件事都绑死在了 Claude Code 上：

- `CliBridgeBase` 的接口其实是 Claude 会话模型
- `WorkflowEngine.handle_event()` 直接解析 Claude `system/assistant/result` 事件
- `claude_event_adapter.py` 既是“Claude 协议解析”又是“平台业务归一化”
- Skills 物化路径写死 `.claude/skills`
- 上下文文件约定写死 `CLAUDE.md`
- 环境变量注入写死 `CLAUDE_CLI_PATH` / `SDD_CLI_MODE`

阶段 1 的核心结论：

> 平台侧应只依赖“一次 Agent 回合执行”和“归一化 Agent 事件”，把 claude-code / opencode / dsh 的差异全部收敛到 adapter 层。

---

## 2. 现状盘点：TraceForge 现有耦合点

### 2.1 桥接入口

`backend/app/engine/claude_bridge.py` 定义了：

```python
class CliBridgeBase(ABC):
    async def start_session(prompt, project_path, event_callback, session_id, env_overrides) -> str: ...
    async def cancel() -> None: ...
    async def interrupt() -> None: ...
    def is_running() -> bool: ...

def create_cli_bridge(cli_path=None) -> CliBridgeBase: ...
```

已有两个实现：

- `SubprocessCliBridge`：真实 Claude CLI 子进程
- `MockCliBridge`：前端/测试降级模拟

### 2.2 直接调用 `create_cli_bridge()` 的业务点

| 调用方 | 用途 | 对 Claude 的隐式依赖 |
|---|---|---|
| `app/engine/workflow_engine.py` | 任务 Chat 主链路 | `handle_event()` 解析 Claude 事件；`--resume` |
| `app/domains/ai/services/ai_job_service.py` | 文档讨论等单轮运行 | 直接消费 `assistant/result` 事件 |
| `app/domains/api_mock/services/api_mock/cli_sync_service.py` | OpenAPI 导入分析 | 直接调用 `flatten_claude_event()` |
| `app/domains/skill/services/skill_analysis_service.py` | Skill 语义审查 | 访问 `bridge.process.returncode` |
| `app/domains/task/services/task_cli_state_service.py` | Task 基线引导 | 访问 `bridge.process`；监听 `system/init` |

### 2.3 配置耦合

```python
# backend/app/config.py
SDD_CLI_MODE: str = "real"      # "mock" or "real"
CLAUDE_CLI_PATH: str = "claude"
CLAUDE_CLI_TIMEOUT: int = 300
CLI_STATE_ROOT: str = "tmp/cli_state"
CLI_BOOTSTRAP_TIMEOUT: int = 1800
```

### 2.4 Skills / 上下文耦合

- `backend/app/domains/skill/services/skill_service.py`：物化到 `.claude/skills`
- `backend/app/domains/skill/services/task_skill_runtime_service.py`：读 `.claude/skills`
- `backend/app/domains/task/services/context_token_service.py`：读 `CLAUDE.md` / `.claude/CLAUDE.md`

结论：如果直接加 OpenCode/DSH，必须把这些“Claude 专有知识”上升为“Agent 可声明能力”。

---

## 3. 技术盘点：Claude Code

现状已具备：

- 非交互执行：`claude -p --output-format stream-json --permission-mode bypassPermissions --verbose <prompt>`
- NDJSON 事件流：`system / assistant / result`
- 会话恢复：`--resume <session_id>`
- 会话创建：`--session-id <id>`
- 权限/HITL：`AskUserQuestion` 工具事件
- Token/Cost：`result` 事件携带 `total_cost_usd`、usage
- Skills：`.claude/skills`
- 上下文：`CLAUDE.md`

这是当前 TraceForge 已跑通的基线，阶段 1 不改动它的行为。

---

## 4. 技术盘点：OpenCode

> 资料来源：`https://opencode.ai/docs/` 公开文档，未在本机安装 opencode CLI。

### 4.1 能力矩阵

| 能力 | 支持情况 | 说明 |
|---|---|---|
| CLI 非交互运行 | ✅ | `opencode run "message"` |
| 结构化输出 | ✅ | `opencode run --format json`，输出 raw JSON events |
| 会话继续 | ✅ | `opencode run --session <id>` / `--continue` |
| 独立服务 | ✅ | `opencode serve` 启动 HTTP server |
| HTTP API | ✅ | 有 OpenAPI，含 session/message/prompt_async/permission 等 |
| SSE 事件 | ✅ | `GET /global/event` 全局事件流 |
| ACP 支持 | ✅ | `opencode acp` 作为 ACP JSON-RPC stdio 子进程 |
| 思考块显示 | ✅ | `opencode run --thinking` |
| 权限自动同意 | ✅ | `opencode run --auto` |
| Skills/Agents | ✅ | 有 Agents/Skills 配置体系 |
| 会话查询 | ✅ | `opencode session list --format json` |

### 4.2 可选集成模式

1. **进程模式（类似当前 Claude Bridge）**
   - `opencode run --format json --session <id> "prompt"`
   - 适合快速接入，事件流以 JSON 行为主
2. **Server 模式**
   - `opencode serve --port 4096`
   - REST + SSE，适合长驻服务和多任务复用
   - 有 `POST /session/:id/message`、`prompt_async`、permission API
3. **ACP 模式**
   - `opencode acp`：JSON-RPC stdio
   - 但 ACP 更偏“编辑器/父 agent 集成”，对 TraceForge 的可观测事件覆盖有限

### 4.3 待确认事项（需要 Spike）

- `opencode run --format json` 的具体事件 schema：文本、思考、工具调用、工具结果、最终结果的字段名
- `--thinking` 是否把思考放进 JSON events
- 会话恢复后是否保留历史事件流
- HITL / permission 请求在 `opencode run --format json` 下如何表达，还是必须走 serve 的 permission API
- Skills 的写入位置与格式（`.opencode` / `opencode.json` / 全局 config）

---

## 5. 技术盘点：DSH（DeepSeek Harness）

> 本地环境：`dsh` 是 DeepSeek Harness CLI，DSH_HOME 为 `~/.dsh`，源码位于 `D:\work\tool\deepseek-harness`。

### 5.1 DSH 对外接口

| 接口 | 形态 | 适用性 |
|---|---|---|
| `dsh --profile headless "task"` | 一次性 CLI | 只打印最终文本，无流式事件；适合最简接入 |
| `dsh --profile web / tui` | 交互产品 | 不适合后端自动调度 |
| Python SDK | PyPI `deepseek-harness-sdk`，JSON-RPC stdio 子进程 | ✅ 最适合 TraceForge 后端接入 |
| TypeScript SDK | `@deepseek-ai/dsh-sdk-client` + JSON-RPC | 若后端迁 Node 才考虑 |
| ACP server | `@deepseek-ai/dsh-acp` 提供 JSON-RPC stdio | 适合父 agent 场景，事件粒度有限 |
| Session Query / Log Export | `dsh-session-query` 可查 JSONL 会话 | 适合事后审计 |

### 5.2 DSH Python SDK 行为（已阅读源码确认）

- 启动一个 `dsh-jsonrpc-agent` 运行时子进程，通过 stdio JSON-RPC 通信
- `DeepSeekHarness.start()` → `initialize(cwd, provider, model, max_tokens)`
- `Session.run(input, session_id=...)`：**session_id 可复用**，服务端按 session id 获取或创建 agent
- 事件流：
  - `session.event`：完整 session 日志事件
  - `session.status`：`running` / `idle`
  - 事件类型包括：`agent/inbox/spliced`、`turn/start`、`user/message`、`assistant/chunk`、`assistant/message`、`tool/call`、`tool/result`、`turn/end` 等
- 返回 `RunResult(session_id, final_response, finish_reason, events, notifications, session_root)`
- 已知限制：
  - 无 wire 级 prompt cancel
  - 无 per-session close
  - Python SDK 是同步 API，FastAPI 中需要 `asyncio.to_thread()` 或单独 executor
  - SDK 当前未安装在 TraceForge 后端环境，需要新增依赖

### 5.3 DSH 适配推荐

阶段 1 建议 DSH 采用 **Python SDK（JSON-RPC）适配器**：

- 支持流式 `assistant/message` / `tool/call` / `tool/result`
- 支持 session_id 续跑
- 天然是完整 Harness 运行时，能力和平台当前 Claude 链路最接近

备选：如果只需要“最终答案”，可以直接 `dsh --profile headless`，但会丢失工具调用/思考等可观测事件。

### 5.4 DSH 事件到平台事件的映射（初版）

| DSH 事件 | 平台统一事件 |
|---|---|
| `assistant/message` 的 `content[type=text]` | `text` |
| `assistant/chunk` 的 `text-delta` | 可选流式 `text_delta` |
| `assistant/message` 的 `content[type=thinking]` | `thinking` |
| `tool/call` | `tool_use` |
| `tool/result` | `tool_result` |
| `turn/end` | `result`（`finish_reason` 取 turn 的 reason kind） |
| `user/ask` / approval 相关 | `ask_user`（待 Spike 确认） |

---

## 6. 统一契约设计（定稿 v0.2.0）

> 完整契约见：[agent-adapter-contract.md](./agent-adapter-contract.md)
> 本节仅作概要同步；后续以契约文档为准。

### 6.1 目录结构

```text
backend/app/agents/
├── __init__.py
├── contract.py          # AgentBackend / AgentRunRequest / AgentRunResult / EventSink
├── events.py            # AgentEvent 统一模型
├── errors.py            # AgentError / Timeout / Cancelled / Configuration / Protocol
├── registry.py          # name -> factory，按 AGENT_BACKEND 路由
├── config.py            # AgentSettings，按 backend 分段配置
├── runtime.py           # 通用子进程/生命周期工具
└── adapters/
    ├── claude_code/     # 从 claude_bridge.py 迁移
    ├── opencode/        # 新实现
    ├── dsh/             # 新实现，基于 deepseek-harness-sdk
    └── mock/            # 现有 MockCliBridge 迁移
```

### 6.2 统一接口

```python
# backend/app/agents/contract.py (定稿 v0.2.0，完整以 contract 为准)

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

AgentEventSink = Callable[["AgentEvent"], Awaitable[None]]

@dataclass
class SkillRef:
    name: str
    source_dir: str
    materialize_to: str | None = None   # hint，非强制目标路径

@dataclass
class AgentRunRequest:
    run_id: str | None = None
    prompt: str
    project_path: str
    session_id: str | None = None       # None=新会话
    model: str | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    skills: list[SkillRef] = field(default_factory=list)
    timeout_seconds: float = 300.0
    permission_mode: str = "default"    # adapter 自行映射
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

@dataclass
class AgentRunResult:
    run_id: str | None = None
    session_id: str
    success: bool
    result_text: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    return_code: int | None = None
    raw_trace: str | None = None

class AgentBackend(ABC):
    name: str
    capabilities: AgentCapabilities

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        """执行一个回合：新会话或恢复会话，事件通过 on_event 吐给平台。"""
        ...

    async def interrupt(self, run_id: str | None = None) -> None: ...
    async def cancel(self, run_id: str | None = None) -> None: ...
    def is_running(self, run_id: str | None = None) -> bool: ...
    async def close(self) -> None: ...

    async def respond_to_ask_user(self, ask_user_id: str, response: str) -> None:
        """可选：长连接 HITL 模式下向等待中的 Agent 回传用户回复。"""
        raise AgentError("HITL response not supported")
```

### 6.3 统一事件模型

```python
# backend/app/agents/events.py (定稿 v0.2.0)

@dataclass
class AgentEvent:
    type: Literal[
        "session_started",
        "text",
        "text_delta",
        "thinking",
        "tool_use",
        "tool_result",
        "ask_user",
        "result",
        "error",
        "usage",
        "context_compacted",
        "log",
    ]
    payload: dict[str, Any]
    provider: str
    raw: dict[str, Any] | None = None
    seq: int | None = None
    time: str | None = None
```

事件语义：

| type | payload 关键字段 | 映射到现有 WebSocket |
|---|---|---|
| `session_started` | `model`, `provider_session_id` | `status INIT` |
| `text` | `text` | `chat_message` assistant |
| `text_delta` | `delta` | 可选流式文本 |
| `thinking` | `text` | `thinking` |
| `tool_use` | `tool_name`, `tool_input`, `tool_use_id` | `tool_use` |
| `tool_result` | `tool_use_id`, `output`, `is_error` | `tool_result` |
| `ask_user` | `question`, `options`, `context` | `hitl_request` |
| `result` | `success`, `result`, `duration_ms`, `cost_usd` | `result` |
| `error` | `message` | `FAILED` |
| `usage` | `TokenUsage` 扁平字段 | Token 归因 |
| `context_compacted` | `summary` | 上下文压缩记录 |
| `log` | `level`, `message` | 执行日志，不进入对话气泡 |

> 结果侧还需要统一 `finish_reason` 受控词表：`completed` / `max-tokens` / `error` / `aborted` / `timeout` / `awaiting_user`。平台 Job 状态判断必须结合 `finish_reason`。

### 6.4 适配器能力声明

```python
@dataclass
class AgentCapabilities:
    supports_resume: bool = True
    supports_streaming_text: bool = False
    supports_tool_events: bool = True
    hitl_modes: list[Literal["turn_based", "long_connection"]] = field(default_factory=list)
    supports_usage: bool = True
    skill_layouts: list[str] = field(default_factory=list)  # ["claude-skills", "opencode", "dsh-skills"]
    preferred_mode: Literal["subprocess", "server", "sdk", "acp"] = "subprocess"
```

WorkflowEngine 可根据 capabilities 决定：

- 是否显示“继续会话”
- 是否接收 `tool_use` 事件
- 如何物化 Skills
- 是否启用 HITL

---

## 7. 与现有代码的兼容迁移策略

### 7.1 保留兼容入口

不直接删除 `create_cli_bridge()`，第一阶段先让它返回**同时实现旧 `CliBridgeBase` 与统一 `AgentBackend` 的封装**：

```python
# 兼容层：app/engine/claude_bridge.py
def create_cli_bridge(cli_path=None) -> CliBridgeBase:
    # 返回 ClaudeCodeAdapter，但必须先兼容旧四件套：
    # start_session / cancel / interrupt / is_running
    ...
```

这样 `api_mock`、`skill_analysis`、`task_cli_state` 等旧调用点不会被一次性破坏。

注意：`AgentBackend.run()` 是回合级接口，旧的 `start_session()+wait()` 是进程级两段接口；兼容层不能简单视为等价。

### 7.2 WorkflowEngine 分两步改造

1. 先把 `handle_event` 改为接收统一 `AgentEvent`
2. 让 `ClaudeCodeAdapter` 内部把 Claude NDJSON 转成统一事件
3. 前端 WS 协议**保持不变**，避免前端大改

### 7.3 配置改造

新增环境变量（向后兼容默认值）：

```env
AGENT_BACKEND=claude-code
AGENT_TIMEOUT=300
AGENT_STATE_ROOT=tmp/agent_state
AGENT_HITL_MODE=turn_based
AGENT_CLAUDE_CODE_PATH=claude
AGENT_OPENCODE_PATH=opencode
AGENT_OPENCODE_SERVER_URL=http://127.0.0.1:4096
AGENT_DSH_PROVIDER=deepseek-official
AGENT_DSH_MODEL=deepseek-v4-flash
AGENT_DSH_RUNTIME_BIN=
AGENT_DSH_SESSION_ROOT=
```

旧配置映射见契约 §8.1.1：`CLAUDE_CLI_PATH`、`SDD_CLI_MODE`、`CLAUDE_CLI_TIMEOUT`、`CLI_STATE_ROOT`、`CLI_BOOTSTRAP_TIMEOUT` 均有等价新配置。

---

## 8. 阶段 1 验收标准

- [x] 产出本设计文档（当前文档）
- [x] 明确 TraceForge 侧 5 个 `create_cli_bridge()` 调用点清单
- [x] 明确 Claude Code 现有协议与事件映射
- [x] 明确 OpenCode 三种接入模式及待 Spike 项
- [x] 明确 DSH Python SDK / JSON-RPC 协议与事件映射
- [x] 定义统一 `AgentBackend` / `AgentEvent` 契约（见 `docs/agent-adapter-contract.md`，含 v0.2.0 两轮审阅修订）
- [x] 定义兼容迁移路径与前端零改动策略（文档完成，编码实施待阶段 2）

---

## 9. 下一步（阶段 2 候选）

1. 在 `backend/app/agents/` 建立契约骨架（仅类型/文档，不接业务）
2. 将现有 `SubprocessCliBridge` 迁移为 `ClaudeCodeAdapter`，保持 `create_cli_bridge()` 兼容
3. 为 `ClaudeCodeAdapter` 写第一组 golden event fixtures
4. 将 `WorkflowEngine.handle_event()` 改为消费统一事件
5. 启动 OpenCode Spike：安装 opencode，采集 `--format json` 的样本事件，确认 session/permission/thinking 行为
6. 启动 DSH Spike：安装 `deepseek-harness-sdk`，采集 `session.event` 样本，确认会话续跑与工具事件

---

## 10. 风险与待决策

| 风险/问题 | 建议 |
|---|---|
| OpenCode `--format json` 事件 schema 未确认 | 阶段 2 做 Spike，先采样本再定 adapter |
| DSH Python SDK 是同步 API | FastAPI 中用 `asyncio.to_thread()` 或独立 executor 包一层 |
| DSH SDK 无 wire cancel | 通过关闭子进程实现 interrupt/cancel，需设计生命周期 |
| 不同 Agent 的 HITL/权限模型差异大 | 统一收口为 `ask_user` 事件；支持回合制与长连接两种模式；不支持 HITL 的 adapter 声明 `hitl_modes=[]` |
| 会话 ID 不可跨 Agent 混用 | 平台统一会话表记录 `agent_kind + provider_session_id` |
| 前端是否需要显示 Agent 类型 | 建议阶段 2 仅在 WS payload 增加 `agent` 字段，前端后续兼容 |

---

## 附：现有文件索引

| 文件 | 说明 |
|---|---|
| `backend/app/engine/claude_bridge.py` | Claude CLI 桥接，待迁移 |
| `backend/app/engine/claude_event_adapter.py` | Claude 事件归一化，待重构为 adapter 内部逻辑 |
| `backend/app/engine/workflow_engine.py` | 主调度引擎，待改为消费统一事件 |
| `backend/app/domains/ai/services/ai_job_service.py` | AI Job 调度与单轮运行 |
| `backend/app/domains/api_mock/services/api_mock/cli_sync_service.py` | API Mock CLI 同步 |
| `backend/app/domains/skill/services/skill_analysis_service.py` | Skill 语义审查 |
| `backend/app/domains/task/services/task_cli_state_service.py` | Task 基线引导 |
| `frontend/src/composables/useChatViewModel.ts` | 前端 WebSocket Chat 逻辑（阶段 1 不改） |