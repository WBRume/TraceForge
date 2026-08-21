# Agent 适配层：旧调用点迁移准备

> 目标：把 `api_mock`、`skill_analysis`、`task_cli_state` 等仍使用 `CliBridgeBase` 原始事件回调的调用点，逐步迁移到统一 `AgentBackend.run()` / `AgentEvent` 路径。
> 状态：准备中（兼容层已保证现状可用，新路径待逐个切换）

---

## 1. 现状

`create_cli_bridge()` 在 real 模式下已返回 `ClaudeCodeAdapter`，它同时实现：

- 旧 `CliBridgeBase`：`start_session()` / `wait()` / `session_id` / `process`
- 新 `AgentBackend`：`run(request, on_event)` / `interrupt()` / `cancel()` / `is_running()` / `close()`

因此以下旧调用点当前不破坏，但仍在消费 **Claude 原始 NDJSON 事件**，而不是统一 `AgentEvent`：

| 调用点 | 文件 | 当前消费内容 |
|---|---|---|
| API Mock 分析 | `backend/app/domains/api_mock/services/api_mock/cli_sync_service.py` | `assistant` 文本块、`result` |
| Skill 语义分析 | `backend/app/domains/skill/services/skill_analysis_service.py` | `assistant` 文本块、`result` |
| Task CLI 基线 bootstrap | `backend/app/domains/task/services/task_cli_state_service.py` | `system.init` session_id、`assistant` 首个文本 |

---

## 2. 统一事件映射对应表

旧 Claude 原始事件 → 统一 `AgentEvent`（由 `ClaudeCodeAdapter` 的 `map_claude_event()` 完成）：

| 旧事件 | 统一 `AgentEvent` | 迁移后取数位置 |
|---|---|---|
| `system.init` | `session_started` | `payload.provider_session_id` / `payload.model` |
| `assistant` + `content[].type=text` | `text` | `payload.text` |
| `assistant` + `content[].type=thinking` | `thinking` | `payload.text` |
| `assistant` + `content[].type=tool_use` | `tool_use` | `payload.tool_use_id` / `tool_name` / `tool_input` |
| `assistant` + `content[].type=tool_result` | `tool_result` | `payload.tool_use_id` / `output` / `is_error` |
| `assistant` usage | `usage` | `payload.input_tokens` 等 |
| `result` | `result` | `payload.result` / `finish_reason` / `usage` |
| `result.is_error=true` | `error` | `payload.result` |

---

## 3. 迁移步骤模板

每个旧调用点按以下模式改造：

```python
from app.agents import AgentRunRequest
from app.engine.claude_bridge import create_cli_bridge

backend = create_cli_bridge()  # 现在就是 ClaudeCodeAdapter

async def on_agent_event(event):
    if event.type == "text":
        text = event.payload.get("text") or ""
        ...
    elif event.type == "session_started":
        session_id = event.payload.get("provider_session_id")
        ...
    elif event.type == "result":
        result_text = event.payload.get("result") or ""
        ...
    elif event.type == "usage":
        ...
    # event.raw 保留原始 Claude NDJSON，可用于现有 flatten/log 逻辑

result = await backend.run(AgentRunRequest(
    prompt=prompt,
    project_path=project_path,
    session_id=session_id,
    env={...},
), on_agent_event)
```

---

## 4. 各调用点要点

### 4.1 `api_mock/cli_sync_service.py`

- 当前 `run_claude_session()` 返回 `(result_texts, assistant_texts)`。
- 迁移后：
  - `text` 事件追加到 `assistant_texts`
  - `result` / `error` 事件追加到 `result_texts`
  - `raw` 字段继续喂给 `flatten_claude_event()` / `on_event` 兼容层（如保留）
  - `wait()` 改为 `await backend.run(...)`；超时/取消语义由 `AgentRunRequest.timeout_seconds` + `backend.cancel()` 承担

### 4.2 `skill_analysis_service.py`

- 当前 `_run_claude_semantic_analysis()` 收集文本后从 JSON 中解析。
- 迁移后同样监听 `text` 与 `result`/`error`。
- `session_id` 可从 `session_started` 拿，供会话复用。

### 4.3 `task_cli_state_service.py`

- 当前靠 `system.init` 获取 `session_id`，靠首个 `assistant` 文本推进 bootstrap 进度。
- 迁移后：
  - `session_started.payload.provider_session_id` → 写 `baseline_session_id`
  - 首个 `text` 事件 → `ready_seen = True`，推进进度到 72

---

## 5. 风险与兼容策略

- `ClaudeCodeAdapter.run()` 目前只支持 `turn_based` HITL；长连接 HITL 仍走旧桥或待 OpenCode/DSH 后续支持。
- 旧调用点若依赖原始 `flatten_claude_event(event)`，可通过 `event.raw` 保留原始数据，避免一次性破坏日志/审计。
- 每个调用点迁移后应做一次端到端回归（真实 Claude CLI 可用性已确认）。