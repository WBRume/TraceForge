# TraceForge Agent Adapter Contract

> 版本：v0.2.0  
> 状态：阶段 1 定稿，作为后续 Agent 工具接入的统一契约  
> 冻结说明：本文档视为阶段 1 定稿；后续如需变更，必须走“契约版本管理”流程，不直接修改。  
> 适用范围：TraceForge 后端适配层，支持 claude-code、opencode、dsh 等 Agent 套件  
> 配套文档：[agent-adapter-phase1.md](./agent-adapter-phase1.md)（技术盘点与现状分析）

---

## 1. 目标

本文档定义 TraceForge 与“外部 Agent 工具”之间的统一适配契约。任何 Agent 工具只要实现该契约，就能被 TraceForge 的任务 Chat、API Mock、Skill 分析、Task 基线等能力复用。

核心原则：

1. **平台侧不感知具体 Agent**。
2. **Agent 与平台之间只通过统一事件流通信**。
3. **会话续跑由 provider session_id 驱动**。
4. **能力差异通过 `AgentCapabilities` 声明**，而不是平台写死分支。
5. **所有 provider 原始数据必须保留在 `raw` 字段**，便于审计和调试。

---

## 2. 术语

| 术语 | 含义 |
|---|---|
| AgentBackend | 一个 Agent 工具的适配器实现 |
| AgentRunRequest | 一次“新会话或恢复会话”的回合输入 |
| AgentRunResult | 一次回合的最终结果 |
| AgentEvent | 回合过程中产生的归一化事件 |
| EventSink | 平台侧接收 `AgentEvent` 的异步回调 |
| provider_session_id | Agent 自己识别的会话 ID，用于恢复 |
| adapter | 与 `AgentBackend` 同义 |

---

## 3. 统一接口

### 3.1 AgentBackend

```python
# backend/app/agents/contract.py
# 契约 v0.2.0

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

AgentEventSink = Callable[["AgentEvent"], Awaitable[None]]

class AgentBackend(ABC):
    name: str
    capabilities: "AgentCapabilities"

    @abstractmethod
    async def run(
        self,
        request: "AgentRunRequest",
        on_event: AgentEventSink,
    ) -> "AgentRunResult":
        """
        执行一个 Agent 回合。

        - request.session_id is None      → 创建新会话
        - request.session_id is not None  → 使用 provider_session_id 恢复会话
        - request.run_id 用于中断/取消时关联具体回合
        - 回合过程中的所有结构化输出必须通过 on_event 推送
        - 回合结束后返回 AgentRunResult
        """
        ...

    @abstractmethod
    async def interrupt(self, run_id: str | None = None) -> None:
        """
        中断当前回合，尽量保留会话上下文以便后续续跑。
        如果 adapter 不支持保留会话，capabilities.supports_resume 必须为 False。
        run_id 存在时只中断对应回合；缺省时中断当前唯一活动回合。
        """
        ...

    @abstractmethod
    async def cancel(self, run_id: str | None = None) -> None:
        """
        取消当前回合，不承诺保留会话。
        调用后应停止子进程/请求，并等待资源回收。
        """
        ...

    @abstractmethod
    def is_running(self, run_id: str | None = None) -> bool:
        """
        当前是否有未结束的回合。run_id 存在时只判断指定回合。
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        释放长驻资源（DSH runtime、OpenCode server client、子进程等）。
        必须幂等；平台在任务结束或 adapter 不再使用时调用。
        """
        ...

    async def respond_to_ask_user(self, ask_user_id: str, response: str) -> None:
        """
        可选方法：向仍处于等待状态的 Agent 发送 HITL 回复。

        默认实现抛 AgentError("HITL response not supported")。

        两种 HITL 模式：
        1. 回合制模式（推荐，默认）：adapter 发出 ask_user 后结束本回合，
           平台保存 session_id，之后用 run(prompt=用户回复, session_id=session_id) 恢复。
           此时不需要实现本方法。
        2. 长连接模式：adapter 发 ask_user 后仍在等待；平台调用本方法
           把用户回复送回 provider，然后继续等待后续事件。
           采用此模式的 adapter 必须实现本方法，并在 capabilities.hitl_modes
           中声明 long_connection。
        """
        ...
```

### 3.2 AgentCapabilities

```python
@dataclass
class AgentCapabilities:
    supports_resume: bool = True
    supports_streaming_text: bool = False
    supports_tool_events: bool = True
    hitl_modes: list[Literal["turn_based", "long_connection"]] = field(default_factory=list)
    supports_usage: bool = True
    skill_layouts: list[str] = field(default_factory=list)
    preferred_mode: Literal["subprocess", "server", "sdk", "acp"] = "subprocess"
```

说明：

| 字段 | 含义 |
|---|---|
| `supports_resume` | 是否支持通过 provider_session_id 恢复多轮会话 |
| `supports_streaming_text` | 是否支持 `text_delta` 增量文本事件 |
| `supports_tool_events` | 是否会上报 `tool_use` / `tool_result` |
| `hitl_modes` | 支持的 HITL 模式：`turn_based`（回合制）、`long_connection`（长连接） |
| `supports_usage` | 是否上报 token/cost |
| `skill_layouts` | 支持的技能布局，如 `claude-skills`、`opencode`、`dsh-skills` |
| `preferred_mode` | 对接形态，仅用于配置提示，不由平台强依赖 |

### 3.3 能力不变量（必须遵守）

| 能力声明 | 合法行为 |
|---|---|
| `supports_streaming_text=false` | 不得推送 `text_delta` 事件 |
| `supports_tool_events=false` | 不得推送 `tool_use` / `tool_result` 事件 |
| `supports_resume=false` | `AgentRunRequest.session_id` 必须为 None，否则 adapter 应抛 `AgentConfigurationError` |
| `hitl_modes` 为空 | 不得推送 `ask_user` 事件 |
| `hitl_modes` 含 `long_connection` | 必须实现 `respond_to_ask_user(ask_user_id, response)` |
| `hitl_modes` 含 `turn_based` | 必须满足 `supports_resume=true`，并在 `ask_user` 后以 `finish_reason="awaiting_user"` 结束回合 |

这些不变量应纳入 contract tests。

---

## 4. 请求模型

### 4.1 AgentRunRequest

```python
@dataclass
class SkillRef:
    name: str
    source_dir: str
    materialize_to: str | None = None   # hint，不是强制目标路径

@dataclass
class AgentRunRequest:
    run_id: str | None = None
    prompt: str
    project_path: str
    session_id: str | None = None
    model: str | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    skills: list[SkillRef] = field(default_factory=list)
    timeout_seconds: float = 300.0
    permission_mode: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
```

字段语义：

| 字段 | 必填 | 说明 |
|---|---|---|
| `run_id` | 否 | 本次回合唯一 ID，用于 interrupt/cancel 关联；平台应生成 UUID |
| `prompt` | 是 | 用户/任务输入的自然语言或指令 |
| `project_path` | 是 | Agent 的工作目录 |
| `session_id` | 否 | provider_session_id；None 表示新会话 |
| `model` | 否 | 可选模型覆盖 |
| `provider_options` | 否 | provider 专有选项，如服务地址、provider 路由等 |
| `env` | 否 | 需要传递给 Agent 的环境变量或上下文参数 |
| `skills` | 否 | 平台 Skills，adapter 负责物化到自己的布局 |
| `timeout_seconds` | 否 | 单回合超时上限；优先于全局 `AGENT_TIMEOUT` |
| `permission_mode` | 否 | 权限策略提示，如 `default` / `bypass-permissions` / `workspace-write` |
| `metadata` | 否 | 平台透传数据：`task_id`、`workspace_id`、`user_id`、`ai_job_id` 等 |

`permission_mode` 建议受控值：

| 值 | 语义 |
|---|---|
| `default` | 使用 Agent 自带的默认权限策略 |
| `bypass-permissions` | 跳过权限确认（当前 Claude 链路使用） |
| `workspace-write` | 只允许写工作区，跨目录需申请 |
| `danger-full-access` | 全权限模式，仅测试/可信环境使用 |

adapter 应把该值映射到自己的权限参数；不支持的取值应显式拒绝或降级为 `default`。

---

## 5. 结果模型

### 5.1 TokenUsage

```python
@dataclass
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)
```

### 5.2 AgentRunResult

```python
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
```

字段语义：

| 字段 | 说明 |
|---|---|
| `run_id` | 与 `AgentRunRequest.run_id` 对应，用于关联中断/取消 |
| `session_id` | 本次实际使用的 provider_session_id，平台必须持久化 |
| `success` | 回合是否正常返回/传输完成；**不等于业务成功** |
| `result_text` | 最终可展示文本 |
| `finish_reason` | 结束原因，见 5.3 受控词表 |
| `usage` | Token 使用量 |
| `cost_usd` | 估算成本 |
| `duration_ms` | 耗时 |
| `return_code` | 子进程退出码（如果有）；非零需映射到 `finish_reason` 或异常 |
| `raw_trace` | 原始会话轨迹内容或日志路径（必须脱敏后持久化） |

### 5.3 finish_reason 受控词表

`finish_reason` 建议使用以下值；adapter 可扩展新值，但必须先在契约中登记：

| 值 | 含义 |
|---|---|
| `completed` | 正常完成 |
| `max-tokens` | 达到输出 token 上限 |
| `error` | provider 执行错误 |
| `aborted` | 被取消/中断且未恢复 |
| `timeout` | 超时终止 |
| `awaiting_user` | 回合在 HITL 处暂停，等待用户输入后通过同一 session 恢复 |

#### 5.3.1 状态映射矩阵（规范性）

| finish_reason | success | 平台 Job 状态 | 说明 |
|---|---|---|---|
| `completed` | `true` | SUCCESS | 正常完成 |
| `max-tokens` | `true` | SUCCESS（可附 max-tokens 标记） | 回合正常返回，但达到输出上限 |
| `awaiting_user` | `true` | WAITING_HITL | 回合在 HITL 处暂停，等待用户输入 |
| `timeout` | `false` | FAILED / TIMEOUT | 超时终止 |
| `aborted` | `false` | CANCELLED | 被取消 |
| `error` | `false` | FAILED | provider 执行或协议错误 |

> 平台判断 Job 状态时，**必须以 `finish_reason` 为准**；`success` 只表示“本次回合是否正常传输完成”，不表示业务成功。
> 若 adapter 返回的词表外值，平台应视为 `error` 并记录警告。

---

## 6. 统一事件模型

### 6.1 AgentEvent

```python
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
    seq: int | None = None      # 可选：事件序号，便于排序/排查
    time: str | None = None     # 可选：ISO 时间戳
```

> `raw` 必须保留 provider 原始事件，用于排障与审计。平台不允许因缺少 `raw` 报错。
> `seq` / `time` 是可选观测字段；adapter 应尽量提供，但平台不得依赖它们保证业务正确性。

### 6.2 事件语义

#### session_started

```json
{
  "type": "session_started",
  "payload": {
    "provider_session_id": "session-xxx",
    "model": "claude-xxx"
  }
}
```

表示 Agent 会话已初始化，平台应记录 provider_session_id 和模型名。

#### text

```json
{
  "type": "text",
  "payload": {
    "text": "Assistant reply text"
  }
}
```

表示一条完整/阶段性文本，平台推送到对话气泡。

#### text_delta

```json
{
  "type": "text_delta",
  "payload": {
    "delta": "incremental text"
  }
}
```

表示增量文本，`supports_streaming_text=true` 时可选使用。

#### thinking

```json
{
  "type": "thinking",
  "payload": {
    "text": "reasoning content"
  }
}
```

表示思考过程，平台展示到折叠面板。

#### tool_use

```json
{
  "type": "tool_use",
  "payload": {
    "tool_use_id": "toolu_xxx",
    "tool_name": "Bash",
    "tool_input": {}
  }
}
```

表示 Agent 发起工具调用。

#### tool_result

```json
{
  "type": "tool_result",
  "payload": {
    "tool_use_id": "toolu_xxx",
    "output": "command output",
    "is_error": false
  }
}
```

表示工具执行结果。

#### ask_user

```json
{
  "type": "ask_user",
  "payload": {
    "ask_user_id": "ask-xxx",
    "question": "请确认是否执行？",
    "options": ["确认", "取消"],
    "context": {}
  }
}
```

表示需要人工参与，平台推送 HITL。`ask_user_id` 必须唯一，用于长连接模式下回传回复时关联。

#### result

```json
{
  "type": "result",
  "payload": {
    "success": true,
    "result": "final answer",
    "finish_reason": "completed",
    "session_id": "session-xxx",
    "duration_ms": 1234,
    "cost_usd": 0.0012,
    "usage": {}
  }
}
```

表示回合正常结束。`result` 事件必须与最终 `AgentRunResult` 对齐：`success`、`finish_reason`、`session_id` 语义一致。

#### error

```json
{
  "type": "error",
  "payload": {
    "message": "error description",
    "finish_reason": "error",
    "error_code": "PROVIDER_ERROR"
  }
}
```

表示回合异常结束。若 adapter 通过 `error` 事件表达失败，则 `run()` 必须返回 `success=false`、`finish_reason="error"` 的结果，且不再抛异常。

#### usage

```json
{
  "type": "usage",
  "payload": {
    "input_tokens": 100,
    "output_tokens": 200,
    "total_tokens": 300,
    "cost_usd": 0.001
  }
}
```

表示 token/cost 更新。

#### context_compacted

```json
{
  "type": "context_compacted",
  "payload": {
    "summary": "optional summary",
    "source": "provider event"
  }
}
```

表示上下文压缩/清理信号。

#### log

```json
{
  "type": "log",
  "payload": {
    "level": "info",
    "message": "raw provider log line or formatted event log"
  }
}
```

表示 provider 的原始日志/可展示日志行。平台可将其写入执行日志，但不进入对话气泡。

> 这是为了兼容现有 `format_claude_event_log_line()` 的日志展示习惯；新增 adapter 如有 stderr、系统事件、非结构化输出，统一通过 `log` 事件上抛。

---

## 7. 生命周期约定

### 7.1 run()

```text
run(request, on_event)
    ├── 创建/恢复 provider 会话
    ├── 推送 session_started（可选）
    ├── 循环推送 text / thinking / tool_use / tool_result / ask_user / usage ...
    ├── 推送 result 或 error
    └── 返回 AgentRunResult
```

**并发约束与实例策略**：

- 默认策略：每个任务/会话持有自己的 `AgentBackend` 实例，同一实例同一时间只允许一个活动回合。
- adapter 在检测到已有活动回合时，应抛 `AgentError("already running")`。
- 如果 adapter 要支持共享实例/并发（例如一个 `opencode serve` 客户端服务多个任务），则：
  - `AgentRunRequest.run_id` 必须参与路由；
  - `interrupt(run_id=...)` / `cancel(run_id=...)` 必须能定位到对应回合；
  - 平台调度器必须在任务结束或不再使用时调用 `close()`。
- OpenCode Server 的“多任务复用”不等于“一个 AgentBackend 实例并发跑多个回合”；更推荐每任务一个 adapter 实例，共享的是底层 server 连接。

要求：

- 即使 provider 事件是普通文本，adapter 也必须至少推送 `text` 或 `result` 中的一种。
- `result` 事件和 `AgentRunResult` 的语义必须一致。
- `on_event` 抛出的异常不应被 adapter 吞掉；应终止回合并转为 `error`/异常。
- `run()` 应在进程结束、请求完成、超时或取消后返回。
- `run()` 返回后，adapter 不得再调用 `on_event`；平台侧可将该约束写入 contract test。

### 7.2 interrupt()

- 用于“暂停当前回合，保留会话以便后续续跑”。
- 支持恢复的 adapter 应尽量保留 provider_session_id。
- 如果不支持，`capabilities.supports_resume=False`，平台不应尝试续跑。
- 传入 `run_id` 时只中断对应回合；不传时中断当前唯一活动回合。
- `interrupt()` 被调用后，正在执行的 `run()` 应尽快以 `finish_reason="aborted"` 或等待用户恢复的 `awaiting_user` 返回。

### 7.3 cancel()

- 用于“终止当前回合，不承诺保留会话”。
- 必须清理子进程、HTTP 连接、SDK runtime 等资源。
- 调用 `cancel()` 后 `is_running()` 应尽快变为 `False`。
- 传入 `run_id` 时只取消对应回合；不传时取消当前唯一活动回合。
- 正在执行的 `run()` 应返回 `finish_reason="aborted"` / `AgentCancelledError`，不得静默悬挂。

### 7.4 HITL（人工确认）

平台统一通过 `ask_user` 事件感知 HITL。HITL 有两种模式：

**模式 A：回合制 HITL（推荐，默认）**

```text
adapter 发出 ask_user（含 ask_user_id）
    → adapter 结束本回合
    → AgentRunResult.finish_reason = "awaiting_user"
    → 平台保存 provider_session_id + ask_user_id，等待用户输入
    → 用户回复后平台调用 run(prompt=回复, session_id=原session_id, metadata={"ask_user_id": ...})
```

- adapter 无需实现 `respond_to_ask_user()`
- 支持前提：`capabilities.hitl_modes` 含 `turn_based`，且 `supports_resume=true`

**模式 B：长连接 HITL**

```text
adapter 发出 ask_user（含 ask_user_id）
    → adapter 不结束回合，仍保持等待
    → 平台调用 respond_to_ask_user(ask_user_id=ask_user_id, response=用户回复)
    → adapter 继续推送事件，直到 result/error
```

- adapter 必须实现 `respond_to_ask_user(ask_user_id, response)`
- 支持前提：`capabilities.hitl_modes` 含 `long_connection`
- 适用于 `opencode serve` 等长连接/服务型接入

**模式选择矩阵**

| 条件 | 使用模式 |
|---|---|
| `hitl_modes` 含 `turn_based` 且 `supports_resume=true` | 优先 A |
| `hitl_modes` 含 `long_connection` | 可使用 B |
| `hitl_modes` 为空 | 不支持 HITL，不得推送 `ask_user` |
| 同时支持两者 | 平台按 `AGENT_HITL_MODE` 或任务配置选择，默认 A |

HITL 等待期间的取消/超时/断线：
- 模式 A：用户未回复时平台可取消任务；后续恢复仍以 `run(session_id=...)` 重新进入。
- 模式 B：用户断线或超时，平台应调用 `cancel(run_id=...)` 或 `close()` 结束等待；adapter 不得永久挂起。

### 7.5 超时

- adapter 内部对 provider 的调用必须设置超时。
- 超时后应终止底层调用，并：
  - 推送 `error` 事件，或
  - 抛 `AgentTimeoutError`，由平台统一补发 error
  - 两者只选其一，避免重复 error
- 超时对应 `AgentRunResult.finish_reason="timeout"`。
- 平台侧也可用外层 `asyncio.wait_for()` 兜底，但 adapter 不能依赖外部兜底。

### 7.6 close()

- 用于释放 adapter 持有的长驻资源：DSH SDK runtime、OpenCode server client、长连接、临时目录等。
- 必须幂等；平台应在任务终态、adapter 替换或应用关闭时调用。
- 调用 `close()` 后，adapter 应拒绝新的 `run()`，并清理未完成回合。

---

## 8. 配置与注册

### 8.1 环境变量约定

```env
AGENT_BACKEND=claude-code
AGENT_TIMEOUT=300
AGENT_STATE_ROOT=tmp/agent_state
AGENT_HITL_MODE=turn_based

# claude-code
AGENT_CLAUDE_CODE_PATH=claude

# opencode
AGENT_OPENCODE_PATH=opencode
AGENT_OPENCODE_SERVER_URL=http://127.0.0.1:4096

# dsh
AGENT_DSH_PROVIDER=deepseek-official
AGENT_DSH_MODEL=deepseek-v4-flash
AGENT_DSH_RUNTIME_BIN=
AGENT_DSH_SESSION_ROOT=

# HITL
AGENT_HITL_MODE=turn_based
```

> **实际落地说明**：当前 TraceForge 后端 `config.py` / `.env` 使用简化名
> `AGENT_BACKEND`（默认 `claude-code`）、`OPENCODE_SERVER_URL`、`DSH_CLI_PATH`，
> 映射关系与示例见 `docs/agent-adapter-phase2-progress.md#10-配置适配实际落地`；
> 后续可将这些项平滑别名到本节 `AGENT_*` 约定名。

### 8.1.1 旧配置 → 新配置映射

| 旧配置 | 新配置 | 说明 |
|---|---|---|
| `CLAUDE_CLI_PATH` | `AGENT_CLAUDE_CODE_PATH` | 兼容别名 |
| `SDD_CLI_MODE` | `AGENT_BACKEND=mock|claude-code` | `mock` 对应 `AGENT_BACKEND=mock` |
| `CLAUDE_CLI_TIMEOUT` | `AGENT_TIMEOUT` | 全局缺省超时 |
| `CLI_STATE_ROOT` | `AGENT_STATE_ROOT`（新增） | 各 adapter 状态/会话根目录 |
| `CLI_BOOTSTRAP_TIMEOUT` | 任务级 `timeout_seconds` | 不再单独配置，统一走回合超时 |

**优先级**：`AgentRunRequest.timeout_seconds` > `AGENT_TIMEOUT` > adapter 内置默认值。

### 8.2 注册表

Adapter 必须注册到统一 registry：

| name | 实现 |
|---|---|
| `claude-code` | ClaudeCodeAdapter |
| `opencode` | OpenCodeAdapter |
| `dsh` | DSHAdapter |
| `mock` | MockAdapter |

注册方式（建议）：

```python
AGENT_BACKENDS: dict[str, type[AgentBackend]] = {
    "claude-code": ClaudeCodeAdapter,
    "opencode": OpenCodeAdapter,
    "dsh": DSHAdapter,
    "mock": MockAdapter,
}

def get_agent_backend(name: str | None = None) -> AgentBackend:
    # 默认返回新实例；需要共享实例时由具体 adapter 自行管理连接池。
    ...
```

> 实例策略：默认每次返回新实例，平台按任务持有；adapter 内部可复用底层 server/SDK 连接，但 `AgentBackend` 实例本身不承诺线程/并发安全。

---

## 9. 上下文与 Skills 注入

### 9.1 env 保留字段

平台会在 `request.env` 中传入统一上下文，adapter 应尽量透传给底层 Agent：

| key | 说明 |
|---|---|
| `TASK_ID` | 任务 ID |
| `WORKSPACE_ID` | 工作区 ID |
| `USER_ID` | 触发用户 |
| `AI_JOB_ID` | AI Job ID |
| `API_BASE_URL` | 平台后端地址 |
| `ACCESS_TOKEN` | 平台访问令牌 |
| `MOCK_BASE_URL` | API Mock 地址 |

> adapter 不得把 `ACCESS_TOKEN` 写入日志或原始 trace 的明文可读位置。

### 9.2 Skills

`AgentRunRequest.skills` 只描述平台侧 Skill 位置，具体布局由 adapter 决定：

| provider | 建议物化位置 |
|---|---|
| claude-code | `<project>/.claude/skills/<name>` |
| opencode | `<project>/.agents/skills/<name>`（当前 opencode Agent Skills 约定） |
| dsh | `<project>/.agents/skills/<name>`（与 opencode 共用 Agent Skills 布局） |

Skills 物化与清理规则：

- adapter 只负责“把平台 Skill 物化到 provider 布局”，并且只清理自己本次创建的文件。
- 建议维护一份 manifest（本次物化清单），记录创建的目录/文件，避免删除用户原有内容。
- 不建议每回合都清理；建议在会话结束/任务终态时由平台统一调用清理，或由 adapter 在 `close()` 中清理。
- 若目标位置已存在同名 Skill，应先跳过/备份，不得静默覆盖。

### 9.3 安全与脱敏

- `ACCESS_TOKEN`、API Key 等敏感凭据只能通过受控 env 传入，不得出现在 `AgentEvent.raw`、`log`、`raw_trace` 明文持久化中。
- adapter 持久化 `raw` / `log` / `raw_trace` 前必须统一脱敏，至少覆盖：token、authorization、api key、password、secret、私有文件内容。
- 远程/服务型 adapter（如 `opencode serve`）必须支持基础鉴权配置，推荐使用 `OPENCODE_SERVER_PASSWORD` 或等价机制；平台不得明文记录远程地址密码。
- `raw` 的保留目的是审计，不是“原样入库”；平台应限制 `raw` 的存储期限和访问权限。

---

## 10. 错误与异常规范

### 10.1 异常类型

```python
class AgentError(Exception): ...
class AgentTimeoutError(AgentError): ...
class AgentCancelledError(AgentError): ...
class AgentConfigurationError(AgentError): ...
class AgentProtocolError(AgentError): ...
```

### 10.2 规范

- 配置错误（找不到 CLI、缺少 API Key）→ 抛 `AgentConfigurationError`
- 超时 → 抛 `AgentTimeoutError` 或返回失败结果，二选一，但必须能区分
- 平台主动取消 → 抛 `AgentCancelledError`（或返回 `finish_reason="aborted"`）
- provider 事件格式无法解析 → 抛 `AgentProtocolError`
- 业务失败（agent 返回错误结果）→ 不抛异常，通过 `result/error` 事件 + `AgentRunResult.success=False` 表达
- **事件与异常二选一原则**：如果 adapter 已经推送了 `error` 事件，就不应再抛出异常；如果选择抛异常，就不要再推送 `error` 事件，由平台统一补发。
- 原则上 `run()` 必须返回 `AgentRunResult`，只有配置错误、协议错误、非预期编程错误才抛异常；取消/超时/业务失败优先通过 result 表达。

---

## 11. 新 Agent 接入检查清单

新 Agent 接入时，必须完成以下工作：

- [ ] 实现 `AgentBackend` 全部抽象方法（含 `close()`）
- [ ] 填写 `AgentCapabilities`，并核对 3.3 能力不变量
- [ ] 注册到 `AGENT_BACKENDS`
- [ ] 提供配置项与默认值，必要时补充旧配置映射
- [ ] 编写事件映射表（provider event → 统一 AgentEvent）
- [ ] 编写 golden fixtures（至少覆盖：new session、resume、text、tool_use、tool_result、result、error、log）
- [ ] 编写能力不变量 contract tests（例如 `supports_streaming_text=false` 不得发 `text_delta`）
- [ ] 通过 contract tests
- [ ] 不修改 `WorkflowEngine` / 前端协议即可完成接入
- [ ] 补充 adapter 的 README 或配置说明

---

## 12. 兼容层

现有代码继续使用 `create_cli_bridge()` 时应保持可用：

```python
# backend/app/engine/claude_bridge.py
def create_cli_bridge(cli_path: str | None = None) -> CliBridgeBase:
    # 兼容入口：未来内部返回一个同时实现 CliBridgeBase 与 AgentBackend 的封装
    ...
```

要求：

- 兼容入口返回的对象必须继续实现旧的 `CliBridgeBase` 方法（`start_session` / `cancel` / `interrupt` / `is_running`），避免旧调用方直接破坏。
- 新代码应优先使用统一 `AgentBackend`，旧调用方逐步迁移。
- 迁移期间不允许破坏存量功能。

> 注意：`AgentBackend.run()` 是“回合级”接口，旧 `CliBridgeBase.start_session() + wait()` 是“进程启动 + 等待”的两段式接口。兼容层需要封装这两段，不能让上层误以为两者签名等价。

---

## 13. 契约版本管理

- 本文档为契约 v0.2.0。
- 后续修改遵循语义化版本：
  - 新增事件类型 = minor（例如 v0.2.0 → v0.3.0）
  - 修改已有事件必填字段/语义、接口签名不兼容 = major
  - 修文案/示例/可选字段 = patch
- 任何契约变更需要同步更新：
  - `docs/agent-adapter-contract.md`
  - `docs/agent-adapter-phase1.md`
  - adapter golden fixtures
  - contract tests

---

## 14. 示例：Adapter 骨架

```python
# backend/app/agents/adapters/example.py
# 仅示意，不是正式实现

from app.agents.contract import (
    AgentBackend,
    AgentCapabilities,
    AgentEvent,
    AgentRunRequest,
    AgentRunResult,
    AgentEventSink,
)

class ExampleAdapter(AgentBackend):
    name = "example"
    capabilities = AgentCapabilities(
        supports_resume=True,
        supports_tool_events=True,
        hitl_modes=[],
    )

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        session_id = request.session_id or "example-session-1"

        await on_event(AgentEvent(
            type="session_started",
            payload={"provider_session_id": session_id, "model": request.model or "example-model"},
            provider=self.name,
        ))

        await on_event(AgentEvent(
            type="text",
            payload={"text": "hello from example adapter"},
            provider=self.name,
        ))

        return AgentRunResult(
            run_id=request.run_id,
            session_id=session_id,
            success=True,
            result_text="hello from example adapter",
            finish_reason="completed",
        )

    async def interrupt(self, run_id: str | None = None) -> None:
        ...

    async def cancel(self, run_id: str | None = None) -> None:
        ...

    def is_running(self, run_id: str | None = None) -> bool:
        return False

    async def close(self) -> None:
        ...
```

---

## 15. 与现有文件的映射

| 现有文件 | 在契约下的角色 |
|---|---|
| `backend/app/engine/claude_bridge.py` | 迁移为 `adapters/claude_code/` |
| `backend/app/engine/claude_event_adapter.py` | 迁移为 `adapters/claude_code/event_mapper.py` |
| `backend/app/engine/workflow_engine.py` | 只依赖 `AgentBackend + AgentEvent` |
| `backend/app/domains/ai/services/ai_job_service.py` | 使用统一 `AgentBackend.run()` |
| `backend/app/domains/api_mock/services/api_mock/cli_sync_service.py` | 使用统一事件流 |
| `backend/app/domains/skill/services/skill_analysis_service.py` | 使用统一 `AgentRunResult`，不再摸 `.process` |
| `backend/app/domains/task/services/task_cli_state_service.py` | 使用统一事件流 |

### 15.1 旧调用点迁移建议

| 旧调用方 | 旧依赖 | 新实现方式 |
|---|---|---|
| `workflow_engine.py` | Claude `handle_event()` | 改为 `AgentBackend.run()` + 统一 `AgentEvent` 分发 |
| `ai_job_service.run_cli_single_turn()` | 直接解析 `assistant/result` | 在 `on_event` 中收集 `text` / `result`；用 `AgentRunResult` 作为最终结果 |
| `api_mock.cli_sync_service()` | `flatten_claude_event()` | 在 `on_event` 中收集 `text`，日志行走 `log` 事件 |
| `skill_analysis_service()` | `bridge.process.returncode` | 使用 `AgentRunResult.return_code` / `finish_reason` |
| `task_cli_state_service()` | 监听 `system/init`、访问 `bridge.process` | 监听 `session_started`；`provider_session_id` 来自 payload；进程细节由 adapter 内部管理 |

---

## 16. 结论

该契约是阶段 1 的输出基线。后续所有 Agent 工具（claude-code、opencode、dsh 等）都按此契约接入，平台侧保持稳定，WorkflowEngine 与前端 UI 不需要随 Agent 类型变化而改动。

---

## 17. 审阅记录

| 版本 | 日期 | 审阅结论 | 主要修订 |
|---|---|---|---|
| v0.1 | 阶段 1 定稿 | 初次发布 | - |
| v0.1.1 | 阶段 1 审阅 | 通过，补充边界语义 | 新增 `log` 事件、`seq/time` 字段；明确 `finish_reason` 受控词表；补充 HITL 两种模式与 `respond_to_ask_user()` 可选方法；明确事件/异常二选一原则；补充 `permission_mode` 受控值和并发约束；强化 `create_cli_bridge()` 兼容层约束 |
| v0.2.0 | 第二轮独立审阅 | 通过但有 Major/Blocker，已修订 | 新增 `run_id`、`model`、`provider_options`、`close()`；`interrupt/cancel/is_running` 支持 run_id；`supports_hitl` 细化为 `hitl_modes`；补充 `finish_reason × success × Job` 状态矩阵；`ask_user` 增加 `ask_user_id`；补充能力不变量、配置别名映射、Skills 清理规则、安全脱敏、实例策略 |

---

## 18. 评审后仍需注意的事项（不阻塞契约）

1. OpenCode / DSH 的 HITL 具体协议需要在 Spike 中验证；DSH 是否产生 `ask_user`/approval 事件尚待确认。
2. 如果未来 Agent 支持“流式工具调用”或“并行工具事件”，需要评估是否引入 `event_id` / `parent_id` / `step_id`。
3. `finish_reason` 的新值需要先在契约登记，再在平台 Job 状态机中扩展。
4. `AgentRunResult.return_code` 到 `finish_reason` 的映射需要逐调用方补充迁移用例（阶段 2）。
5. 心跳/长连接保活事件未列入 v0.2.0，若 OpenCode Server/DSH 接入需要长任务保活，再新增 `heartbeat` 事件。
---

## 19. 会话 fork（v0.2.1 新增）

需求背景：研发态任务上传需求文档后，baseline 会话先完整读一遍文档（可能几十 MB）；
评审线程通过「fork baseline 会话」获得带完整文档上下文的独立新会话——
既避免每个讨论重读文档，又保证不同讨论之间上下文互不污染。

### 19.1 契约扩展

- `AgentCapabilities.supports_fork: bool`（默认 False）
- `AgentBackend.fork_session(session_id, *, source_dir, target_dir) -> str`（可选实现）：
  把 `source_dir` 中的既有会话 fork 成 `target_dir` 下的独立新会话，返回新会话 id；
  原会话必须保持只读。未实现时抛 `SessionForkError`。

### 19.2 各后端实现

| 后端 | 实现方式 | 说明 |
|---|---|---|
| claude-code | 原生 fork：baseline 快照一次性 stage 到任务目录 store（硬链接优先，跨卷回退复制；幂等），每线程首轮 `--resume <baseline_sid> --fork-session` 在任务目录生成专属新会话 id，原快照永不被续写。注意：claude 会话查找按 cwd 的 project store 隔离，跨目录 `--resume` 会报 No conversation found，因此 staging 不可省略 | 线程 cwd = 任务目录（task.project_path） |
| opencode | API：`POST /session/{id}/fork`（v1，v2 `/api/session/{id}/fork` 回退）复制全部历史（含工具调用），再 move 到任务目录 | baseline 会话在服务端永远只读 |
| dsh | 文件级：复制 `session.jsonl(.zstd)` 到新 id、任务目录 cwd 下并重写头部（zstd 需头部行单独成帧），web host prompt 冷启动时按新 id/cwd resume | 布局复刻 `session-persistence-jsonl/format.ts` |

### 19.3 编排（task_cli_state_service）

- baseline READY 后执行 fork 演练（`probe_session_fork`），失败会体现在 baseline message；
- 评审线程在**任务目录**（`task.project_path`，含全部 git worktree）中执行，
  评审答疑可直接读取仓库内容；
- 线程首次使用时 `ensure_thread_session()` 返回 ThreadSessionPlan：
  claude-code → 首轮 `--fork-session` 惰性 fork；opencode/dsh → eager fork 到任务目录；
  会话 id 持久化到 `sdd_asset_threads.cli_session_id`，此后只 resume 自己的会话，
  **绝不直接 resume baseline 会话**；
- fork 不可用时线程显式降级为独立新会话（重读文档），并在日志/baseline 状态中可见。

## 20. DSH Web Host server 模式（v0.2.1 新增）

配置 `DSH_SERVER_URL`（`dsh web --no-open --host 127.0.0.1 --port N` 启动）后，
dsh 后端从 headless CLI 切换为 Web Host server 模式（`DshServerAdapter`）：

- 传输：`POST /api/<method>` 信封 RPC（`client-request` / `server-response`，业务错误 HTTP 200 + `ok=false`）
  + `WS /api/events.mux` 下行事件流（loopback 免认证）；
- 能力：跨进程 resume（prompt 隐式冷启动 resume）、多轮、工具事件、token usage、
  approval/question HITL（`POST /api/respond` 回复）；
- headless CLI 模式仍可用（无 resume/usage/事件；CLI 不打印 session id，
  适配层通过扫描持久化目录最新写入兜底发现会话 id 供 fork 使用）。

## 21. 审阅记录（续）

| 版本 | 日期 | 审阅结论 | 主要修订 |
|---|---|---|---|
| v0.2.1 | 2026-08-22 | 新增 fork 能力 | `supports_fork` / `fork_session()` / `SessionForkError`；三后端 fork 实现；线程级 `cli_session_id` 编排；DSH Web Host server 模式（`DSH_SERVER_URL`）与文件级 fork（zstd 头部单帧重写） |
