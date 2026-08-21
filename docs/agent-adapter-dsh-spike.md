# DSH Spike 准备

> 目标：确认 DSH（DeepSeek Harness）如何以统一 `AgentBackend` 接入 TraceForge。
> 状态：已执行（headless CLI 真实调用成功；Adapter 默认走 CLI subprocess，不依赖 Python SDK / 本地仓库）

---

## 1. 本地环境已知信息

- DSH CLI：`dsh` launcher 位于 `~/.dsh/bin/dsh.cmd`
- DSH 源码：`D:\work\tool\deepseek-harness`
- DSH Home：`~/.dsh`
- 已确认 DSH 提供以下接入方式：

| 方式 | 形态 | 是否适合 TraceForge |
|---|---|---|
| `dsh --profile headless "task"` | 一次性 CLI | 可用但无流式事件 |
| Python SDK | `deepseek-harness-sdk` + JSON-RPC stdio | ✅ 最推荐 |
| TypeScript SDK | `@deepseek-ai/dsh-sdk-client` | 后端迁 Node 时才考虑 |
| ACP server | `@deepseek-ai/dsh-acp` | 父 agent/编辑器场景 |
| Session Query | 查 JSONL 会话 | 事后审计 |

---

## 2. Python SDK 关键结论（已从源码确认）

- 安装：`python -m pip install deepseek-harness-sdk`
- 入口：

```python
from deepseek_harness import DeepSeekHarness

with DeepSeekHarness(
    provider="deepseek-official",
    model="deepseek-v4-flash",
) as harness:
    result = harness.run("say hi")
```

- `Session.run(input, session_id=...)`：session_id 可复用
- 事件流：
  - `session.event`：完整 session 日志事件
  - `session.status`：`running` / `idle`
  - 事件类型：`agent/inbox/spliced`、`turn/start`、`user/message`、`assistant/chunk`、`assistant/message`、`tool/call`、`tool/result`、`turn/end`
- 返回 `RunResult(session_id, final_response, finish_reason, events, notifications, session_root)`
- 已知限制：
  - Python SDK 是同步 API
  - 无 wire 级 prompt cancel
  - 无 per-session close
  - SDK 当前未安装在 TraceForge 后端环境

---

## 3. Spike 要回答的问题

- [ ] 安装 `deepseek-harness-sdk` 后能否直接启动本地 runtime？
- [ ] `session.event` 中 `assistant/message` 的 content 结构？
- [ ] `assistant/chunk` 的 `text-delta` 字段？
- [ ] `tool/call` / `tool/result` 的事件字段？
- [ ] `turn/end` 的 `reason.kind` 取值？
- [ ] DSH 是否有 `ask_user` / approval / permission 事件？
  - 若无，HITL 如何实现？
- [ ] session_id 续跑是否稳定？
- [ ] 启动/关闭 runtime 的生命周期成本？
- [ ] 是否能注入 TraceForge env（`API_BASE_URL`、`ACCESS_TOKEN`、Skills）？

---

## 4. Spike 执行结果

- `python -m pip install deepseek-harness-sdk` 从当前 PyPI 镜像装到的是 **placeholder 包**（`0.0.0.dev0`），不是真实 SDK。
- 真实 SDK 位于 DSH 源码仓库：`D:\work\tool\deepseek-harness\python\sdk`，可通过 `PYTHONPATH=...\python\sdk\src` 使用。
- **真实调用验证**：在 DSH 源码根目录执行
  `dsh --profile headless "只回复两个字: 好的"` 成功返回 `好的`；在临时目录执行会因内部 shell spawn 的 `cwd` 不可见而报 `spawn pwsh.exe ENOENT`，改用真实源码目录即可。
- 注意：Python SDK 的 `deepseek-harness-runtime-bin` 只有 `manylinux` / `macosx` 平台 wheel，**Windows 无法通过 requirements 直接安装**；因此 Windows 上不依赖 SDK。
- 本地 runtime 依赖 `deepseek-harness-runtime-bin`（exe）或 dev-only node closure；当前 checkout 未构建完整 closure，直接启动 `dsh-sdk-jsonrpc-demo` 会因 pnpm symlink 解析不到 `@deepseek-ai/dsh-*` 插件而失败。
- 已确认 SDK API：
  - `DeepSeekHarness(start/close)` 生命周期
  - `Session.run(input, session_id=...)` 返回 `RunResult(session_id, final_response, finish_reason, events, notifications, session_root)`
  - 事件类型：`agent/inbox/spliced`、`turn/start`、`step/start`、`user/message`、`assistant/chunk`、`assistant/message`、`tool/call`、`tool/result`、`step/end`、`turn/end`
  - `assistant/chunk.data.chunk.type`：`block-start` / `text-delta` / `block-end` / `tool-call-delta` / `usage` / `finish`
  - `assistant/message.data.usage`：`inputTokens` / `outputTokens`
  - `turn/end.data.reason.kind`：`completed` 等
- 事件样本取自官方快照：
  `python/sdk/tests` 与 `scripts/snapshots/python-sdk-single-exe/advanced/session.jsonl`。
- 结论：`DSHAdapter` 在 Windows 默认走 **CLI subprocess 模式**（`dsh --profile headless`），避免 TraceForge 依赖 DSH 源码仓库；`map_dsh_event()` 保留，供未来 Linux/macOS SDK 模式使用。
- `DSHAdapter.run()` 已实现基础 CLI subprocess 接线；golden fixture 为 `dsh_session_sample.jsonl`。

---

## 5. Spike 执行步骤

```bash
# 1. 安装 SDK（建议在 backend venv 中）
python -m pip install deepseek-harness-sdk

# 2. Python 冒烟脚本
python - <<'PY'
from deepseek_harness import DeepSeekHarness

with DeepSeekHarness(
    provider="deepseek-official",
    model="deepseek-v4-flash",
) as harness:
    result = harness.run("say hi")
    print(result.session_id)
    print(result.finish_reason)
    for event in result.events:
        print(event.get("type"))
PY

# 3. 采集 session.event 样本并保存到临时文件
# 4. 验证 session_id 续跑
# 5. 验证关闭/取消行为
```

> 需要 `DEEPSEEK_API_KEY` 或本地代理可用；若不可用，可先做“runtime 启动/关闭”和协议握手验证。

---

## 6. 需要保存的证据

- `initialize` 握手响应
- `session.event` 原始样本（脱敏）
- `assistant/message` 的 content block 样本
- `tool/call` / `tool/result` 样本
- `turn/end` 的 `reason.kind` 样本
- 是否有 permission/ask_user 事件

---

## 7. 验收标准

- [x] 确认真实 SDK 源码与事件 schema（PyPI placeholder 问题已定位）
- [x] 产出 DSH 事件到统一 `AgentEvent` 映射表初稿（`event_mapper.py`）
- [x] 产出 DSH golden fixture 样本（原始 + 归一化）
- [x] 明确 HITL 支持方式（待 runtime 打包后实现）
- [x] 更新 `docs/agent-adapter-phase2-progress.md`

---

## 8. 风险

| 风险 | 说明 |
|---|---|
| 需要模型凭据 | 无凭据时只能做协议层验证 |
| Python SDK 同步 API | FastAPI 中需 `asyncio.to_thread()` 包装 |
| 无 wire cancel | 取消需关闭 runtime 子进程 |
| 运行时体积/启动耗时 | 每个任务一个 runtime 时需评估复用策略 |