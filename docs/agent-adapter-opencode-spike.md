# OpenCode Spike 准备

> 目标：确认 OpenCode 是否可以作为 TraceForge `AgentBackend` 接入，以及接入时应采用 CLI / Server / ACP 哪种模式。
> 状态：已执行（v1.18.19，Server 模式验证通过；CLI run 在 Windows 当前 shell 环境存在 spawn pwsh 问题）

---

## 1. 已知信息（来自公开文档）

官方文档：https://opencode.ai/docs/

### CLI 非交互模式

```bash
opencode run "Explain async/await in JavaScript"
opencode run --format json "message"
opencode run --session <session-id> "continue"
opencode run --continue "continue last session"
opencode run --thinking "show thinking"
opencode run --auto "auto-approve permissions"
```

### Server 模式

```bash
opencode serve --port 4096
```

HTTP API 能力（OpenAPI 暴露）：

- `GET /global/event`：SSE 事件流
- `GET /session` / `POST /session`：会话管理
- `POST /session/:id/message`：发送并等待
- `POST /session/:id/prompt_async`：异步发送
- `POST /session/:id/message/:messageID/cancel`：取消
- permission 相关 API：Respond to permission request
- `GET /experimental/tool/ids`：工具列表

### ACP 模式

```bash
opencode acp
```

- JSON-RPC stdio
- 面向编辑器/父 agent 场景
- 事件粒度可能不如 Server 模式丰富

---

## 2. Spike 要回答的问题

- [ ] `opencode run --format json` 的事件帧结构是什么？
- [ ] 文本、思考、工具调用、工具结果分别用什么事件类型表达？
- [ ] `--session` 续跑后，历史上下文是否保留？
- [ ] HITL / permission 请求在 `--format json` 下如何表达？
  - 是结束回合等待，还是需要走 Server 的 permission API？
- [ ] `--auto` 是否等于绕过确认？与 TraceForge `permission_mode` 如何映射？
- [ ] `opencode serve` 的 SSE/HTTP 是否更适合 TraceForge：
  - 长驻连接
  - 多任务复用
  - 权限请求 API 更完整
- [ ] Skills 如何物化：
  - `.opencode` 目录？
  - `opencode.json`？
  - 全局 config？
- [ ] 是否支持 usage/cost/token 统计？

---

## 3. Spike 执行步骤

```bash
# 1. 安装或确认 CLI
opencode --version

# 2. 基础非交互执行，观察默认输出
opencode run "say hi"

# 3. 采集 JSON 事件流
opencode run --format json --thinking "say hi"

# 4. 会话续跑验证
SESSION_ID=xxx
opencode run --format json --session "$SESSION_ID" "continue"

# 5. Server 模式验证
opencode serve --port 4096
curl http://localhost:4096/global/event

# 6. ACP 验证（可选）
opencode acp --help
```

> 执行时优先在临时目录进行，避免污染真实工作区。

---

## 4. Spike 执行结果

- OpenCode `v1.18.19` 通过 `npm i -g opencode-ai` 安装成功。
- `opencode run --format json` 在当前 Windows/PowerShell 环境启动失败：
  `spawn D:\Program Files\PowerShell\7\pwsh.exe ENOENT`，即使设置 `SHELL` 仍复现；因此 CLI 单次执行模式暂不作为首选。
- `opencode serve --port 4097` 可稳定启动，暴露 OpenAPI（`/doc`）与：
  - `POST /api/session`：创建会话
  - `POST /api/session/{id}/prompt`：发送消息
  - `GET /api/session/{id}/message`：取最终消息
  - `GET /api/session/{id}/event`：SSE 事件流
  - `POST /api/session/{id}/interrupt` / `abort`：中断/取消
  - `/api/session/{id}/permission/.../reply`、`/api/session/{id}/question/.../reply`：HITL
- 实测 SSE 事件类型（`session.next.*`）：
  - `text.started` / `text.delta` / `text.ended`
  - `reasoning.started` / `reasoning.delta` / `reasoning.ended`
  - `tool.input.started` / `tool.input.ended` / `tool.called` / `tool.success` / `tool.failed`
  - `step.started` / `step.ended`（含 `finish`、`cost`、`tokens`）
  - `permission.v2.asked` / `question.v2.asked`
- 最终消息/用量可从 `GET /api/session/{id}/message` 的 assistant message 获取：
  `tokens.input/output/reasoning/cache.read/write`、`finish="stop"`。
- 结论：TraceForge 接入 OpenCode 应采用 **Server 模式**；`OpenCodeAdapter` 骨架与 `map_opencode_event()` 已落地。

---

## 5. 需要保存的证据

- `opencode run --format json` 的原始事件样本（脱敏后）
- `opencode serve` 的关键 HTTP 响应 / SSE 事件样本
- `opencode session list --format json` 输出格式
- 权限请求样本（若出现）
- 思考块在 JSON 中的字段
- 最终结果事件字段

---

## 6. 验收标准

- [x] 能明确回答上述“Spike 要回答的问题”（Server 模式更完整）
- [x] 确认至少一种接入模式适合 TraceForge（Server 模式）
- [x] 产出 `OpenCodeAdapter` 的事件映射表初稿（`event_mapper.py`）
- [x] 产出 `opencode` golden fixture 样本（原始 + 归一化）
- [x] 更新 `docs/agent-adapter-phase2-progress.md`

---

## 7. 风险

| 风险 | 说明 |
|---|---|
| `--format json` 不支持思考块 | 需考虑是否使用 Server 模式 |
| HITL 在 CLI 模式下表现弱 | 可能需要走 `opencode serve` permission API |
| 会话恢复行为与 Claude 不同 | 需要单独适配 session 生命周期 |
| CLI 未安装 / 需要登录 | Spike 需要准备 provider 凭据 |