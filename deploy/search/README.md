# 全局历史搜索部署

实现 BM25 + nested kNN + **Python RRF**。两路召回共用短期 PIT，分别取最多 200 个父实体，以 `1/(60+rank)` 等权融合，保留最多 200 个候选。首次检索后的分页只读用户隔离的 Redis 快照并重新授权，不再调用 embedding 或 ES。无需 Elastic Enterprise / 原生 RRF 授权。

验证基线：ES 9.5.2、官方 Python 客户端 9.3.0、Python 3.11、MySQL、Redis、硅基流动 BAAI/bge-m3（1024 维）。生产要求认证、TLS 或受控内网；Compose 中 `search-local-es` 仅为本机单节点开发配置，不是高可用部署。

## 日常启动

已经完成初始化的环境，只需照常启动 backend。`SEARCH_ENABLED=true` 时，backend 默认自动运行搜索和向量两个异步 worker，关闭 backend 时一并停止；不再需要额外终端或进程命令。当前单机环境沿用这种方式。

## 首次配置

在 backend/.env 或部署目录 .env 中设置 `.env.example` 的 SEARCH 字段。密钥不能提交 Git。`SEARCH_CONFIG_ENCRYPTION_KEY` 是 Fernet 密钥，与 MySQL 中加密后的配置一同备份；`SEARCH_CURSOR_SECRET` 使用独立随机值。API、两个 worker 必须配置相同的加密密钥、数据库和 Redis 命名空间。

1. 备份现有数据库，检查 `python -m alembic current` 和 `heads`。新增迁移 `d5f60718293a` 接续 `c4e5f6a7b8d9`，仅增加搜索表和 nullable 排序列，不清空业务数据。
2. 在 backend 目录安装 requirements 并执行 `python -m alembic upgrade head`，先保持 `SEARCH_ENABLED=false`。新应用需要新 schema；不要先启动新代码再迁移。
3. 使用管理员页面配置 endpoint/key/model 并测试；也可使用 `python -m app.domains.search.cli configure` 从本地 `SEARCH_EMBEDDING_API_KEY` 创建已探测且加密保存的硅基流动 profile。配置完成后可清除环境中的 bootstrap API key，保留 Fernet 密钥。
4. 创建目标：`python -m app.domains.search.cli create-index --target traceforge-search-v1-000001 --embedding-profile PROFILE_ID`。物理索引绑定不可变模型空间；仅轮换 API key 无需重建。
5. 设置 `SEARCH_ENABLED=true` 后照常启动 backend，正文与向量 worker 自动运行；未激活索引时页面会显示准备状态。系统配置页可完成模型测试、建立索引、验证和激活，下面的 CLI 命令是可选方式。
6. 执行 `python -m app.domains.search.cli backfill --target traceforge-search-v1-000001 --batch-size 100`。断线可 `resume --run-id RUN_ID`，search worker 也会继续 pending 回填。管理员“建立新索引”会创建持久化回填记录。回填走相同版本协议并分批补齐 sort_seq。
7. 使用 `status` 查看 outbox、embedding job、回填状态；`retry` 显式重试 dead 作业。首次回填和向量完成后执行 `verify --target INDEX`，再 `activate --target INDEX`。
8. 激活完成后即可通过顶部入口或双 Shift 搜索；无需为 worker 再启动进程。输入框与 IME 中不触发快捷键。

管理员的模型测试会发送两条合成文本；回填会向配置的供应商发送收录的可见正文分段。默认每 profile 后台 2 请求/秒（每批最多 16 段），查询 16 请求/秒、API 同时最多 8 次搜索。按实际供应商配额调小，不能视为供应商保证值。初始查询 embedding 预算 800ms、搜索总预算 2s；provider 超时会明确回退关键词。连接探测的 10s 预算不等于在线延迟目标。

## 可选的独立 worker 部署

仅在需要独立分配资源时，将 API 的 `SEARCH_WORKERS_ENABLED=false`，再运行 `python -m app.domains.search.worker --kind search` 和 `python -m app.domains.search.worker --kind embedding`。容器对应 `docker compose --profile search up -d search-worker embedding-worker`；默认无需启用该 profile。API 单副本约束保持不变。

内置 worker 发生循环级异常时每 5 秒重试；关闭时先停止领取新作业，最多等待 15 秒，再取消未完成作业。未完成的租约会在到期后重新领取（当前 300 秒），版本与租约校验保持有效。

## 一致性与恢复

业务事务仅写 MySQL state/outbox。任务和消息 ORM 写入/更新/删除由事务内捕获维护；撤销和清空的 bulk delete 另记范围重扫事件，任务/工作区级联删除也记录范围事件。范围重扫重新读取当前源，保留并发新增消息。删除后立即回表拒绝返回旧摘要，后台完整墓碑最终移除正文和向量。

索引版本是 `2*source_version+phase`，正文 phase=0，全部向量就绪或墓碑 phase=1。写入为严格 external 完整替换；409 必须检查现存版本和身份。worker 的确认受租约 token 保护。正文成功但未创建 embedding job 时崩溃，可重投并补建作业。

模型更换创建新 profile 和 building target。worker 同步 active/building/standby，避免混写向量空间。API 从 MySQL 活动目标取得物理索引及绑定 profile。激活阶段和租约持久化；中断后等待 30 秒租约到期，对同一 target 重跑 activate，恢复别名与 DB 状态。旧目标保留为 standby，回滚前重新 verify。

关闭搜索：先将 SEARCH_ENABLED=false，再按需停止 worker；保留 state/outbox/jobs 和业务消息。不要删除 ES 数据卷或重置 MySQL。紧急应用回滚可保留新增表列；schema downgrade 仅在旧应用已部署并完成备份后另行安排。

## 验证

普通测试：

```text
python -m pytest tests/search/test_search_contracts.py -q
python -m pytest tests/task/test_task_chat_history_ordering.py tests/task/test_task_session_interrupt_resume.py tests/ai/test_chat_message_idempotency_service.py tests/websocket/test_task_websocket_handler.py -q
python -m compileall -q app
```

真实基础设施测试需显式设置 `SEARCH_LIVE_TESTS=1` 后运行 `python -m pytest tests/search/test_search_live.py -q`。仅创建和删除 `traceforge_search_test_<随机值>` MySQL 数据库和 `traceforge-search-test-<随机值>` ES 索引；不触及业务库、已有索引和读别名。需要 CREATE/DROP DATABASE 测试权限、ES 测试索引权限、Redis 和供应商凭据；会发送少量合成文本请求。

前端运行 `npm run test:run -- src/composables/__tests__/useDoubleShift.spec.ts src/composables/__tests__/useGlobalSearch.spec.ts src/composables/__tests__/useChatMessageContext.spec.ts` 和 `npm run build`（包含 vue-tsc）。

待实际业务灰度衡量：50 组人工标注查询的召回质量、大规模回填耗时、混合负载 P95/P99、资源用量和供应商额度。小样本联通测试不能代替容量验收。可见消息当前按落库消息分别检索，不支持跨消息短语；思考过程和原始工具 JSON 不收录。
