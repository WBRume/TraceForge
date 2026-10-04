# OpenCode 真实执行恢复验收

从 `backend` 目录显式执行（会调用真实模型与 shell 工具）：

```powershell
python -m tests.live_opencode.verify_recovery --run-live
```

默认读取 `backend/.env` 中的 OpenCode 地址、HTTP 认证，以及服务端默认模型。
可用 `--model provider/model` 指定模型，或用 `--cases sse_disconnect restart_running` 选择场景。
普通 pytest 不会自动收集或运行这些脚本。

## 独立执行进程的实际链路

每个用例启动独立 Python 后台进程，运行生产 `run_queue → TaskAgentEngine → OpenCodeAdapter`
和真实数据库事务；恢复由生产 reaper / `claim_existing_sync` 接管，结果由现有 finalizer 收敛。
业务流程不替换为 mock。只有 HTTP transport 包装故障注入，底层全部访问当前真实 OpenCode serve。
测试的数据库为独立落盘 SQLite，跨进程保留检查点；不访问项目的业务数据库。

阈值仅作用于测试进程：空闲 6 秒、静默核验 1 秒、租约 5 秒、心跳 1 秒；绝对时限按场景为 45–180 秒。
真实工具向自己的工作目录写开始/结束记录，静默睡眠 15–90 秒后输出唯一标记。

| 场景 | 故障与断言 |
| --- | --- |
| `sse_disconnect` | 静默工具执行中切断两条真实 SSE 连接，检查重连、跨多个空闲周期存活、最终 SUCCESS |
| `missing_terminal_sse` | 丢弃全部 session SSE 帧（仅保留服务连接/心跳帧），仅凭持久化快照恢复工具和最终回复 |
| `restart_running` | 工具运行时硬结束后台进程，确认 OpenCode 仍 active，再启动新进程，检查同一 job/session/prompt/deadline 接管 |
| `restart_finished` | 后台进程离线期间让远端任务完成，等原 deadline 到期后再重启，检查优先补查成功终态 |
| `hard_timeout` | 工具执行超过绝对时限，检查持久化 stopping、一次远端 interrupt 和 INTERRUPTED 收敛 |

成功恢复的用例都断言：一次 prompt POST、一个 provider 用户输入、一次真实工具执行、一条最终回复、零 interrupt。
所有用例只停止自己的子进程，结束后删除自己创建的 OpenCode session。生产服务和用户会话保持运行。
不创建 Webhook 端点、不投递外部提醒、不更改现有 `.env`。

## 证据和边界

证据位于 `backend/tmp/opencode-live/<timestamp>/`：汇总 `report.json`、每用例 `evidence.json`、
SQLite 数据库、每进程 HTTP/SSE/所有权轨迹、终态快照、控制台日志和工具执行记录。
凭据不写入证据。测试仅在自身目录写文件，失败也清理已知的独立会话。

本验收覆盖真实队列/引擎后台进程的硬退出和重启；不启动完整 HTTP 应用，不替代生产 MySQL
并发验证、浏览器多人进出会话验收或连续 8 小时稳定性测试。

## 完整 HTTP 服务与实际 MySQL

在已授权重启本机 8000 端口服务的维护窗口中执行：

```powershell
python -m tests.live_opencode.verify_http_recovery --run-live --restart-http
```

这个入口会重启当前 HTTP 服务，访问当前 `.env` 配置的真实 MySQL、Redis 和 OpenCode。
开始前检查没有 PENDING/RUNNING/WAITING_HITL/TERMINATING 作业；保留既有 ORPHANED 记录，由正常服务管理。
脚本记录原服务的启动命令和工作目录，在内存中保留进程环境；退出时按原配置重新启动并检查
`/health/ready`。原先由 IDE 启动的服务会变为后台运行，IDE 不再持有新进程。

仅在实际 MySQL 中创建独立测试用户、工作区和任务记录，随后通过真实 `/api/auth/login`、
`chat-submissions`、`session-state`、`ai-jobs` 和任务 WebSocket 执行验收。
消息受理、Git 检查点、队列、执行、接管、回执及终态落库均走完整应用。
两个账号分别为 OWNER / VIEWER；WebSocket 客户端遵守 `resync_required → REST 快照 → resync_complete`
协议。HTTP 重试并发提交同一消息 ID，检查只产生一条回执、一个作业和一个 provider 用户输入。

`http_service.py` 运行原 `app.main:app` 的全部路由及 lifespan，缩短阈值仅作用于该子进程。
它只包装真实 HTTP transport 记录不含凭据的请求轨迹，并用本地 stop 文件触发 uvicorn 的正常关闭。
不会替换 MySQL/Redis、恢复流程、provider 响应或工具结果。

| 场景 | 验证 |
| --- | --- |
| `http_graceful_running` | 工具静默 65 秒；两个客户端退出超过 6 秒空闲阈值后，正常关闭完整服务并重启，保留远端执行 |
| `http_crash_running` | 工具静默 55 秒；强制结束完整 HTTP 进程后重启，重新获取 MySQL 执行所有权 |
| `http_crash_finished` | 工具静默 15 秒；完整服务离线期间远端完成，等原 65 秒截止时间已过再启动，补查成功终态 |

三项均断言同一 job/session/prompt/deadline、attempt 由 1 增至 2、旧所有权写入被拒绝、
SUCCESS 与 SUCCEEDED 回执同时收敛、一条最终回复、一次工具执行和零 interrupt。
运行中恢复的两项还核对两个重连客户端均收到 `chat_job_done`；离线完成项由 HTTP 快照补齐终态。

证据位于 `backend/tmp/opencode-http-live/<timestamp>/`，包含 MySQL 检查点快照、HTTP/SSE 轨迹、
客户端事件、真实工具记录及服务恢复/数据清理记录。脚本删除自己创建的 provider sessions，
通过正常删除 API 清理自身任务和工作区，删除两名专用测试用户；保留本地证据文件。
不创建 Webhook 端点、不更改 `.env`，普通 pytest 不会收集这些显式入口。
这个入口仍不替代浏览器 UI 验收或连续 8 小时耐久性测试。
