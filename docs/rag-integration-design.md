# RAG 推送集成方案设计

## 1. 背景与目标

TraceForge 中“问题定位（DIAGNOSIS）”完成后，会走：

```text
问题定位会话
  → 一键总结问题案例
  → 确认采纳 / 转案例草稿
  → 提交评审
  → 专家审批通过（APPROVED）
  → 案例正式入库
```

本方案只在**案例审批通过、正式入库**后，将结构化案例异步、可靠、可幂等地推送到 RAG 服务，为后续“相似问题检索 / 经验复用 / 智能问答”提供数据基础。

本设计不绑定具体 RAG 厂商，统一抽象为 `RagProvider`，可对接自研 HTTP 服务、OpenSearch、Qdrant、Dify、RAGFlow 等。

> 适配层代码已落地，具体平台对接步骤见 [rag-provider-integration.md](./rag-provider-integration.md)。

## 2. 推送边界

### 允许推送

| 阶段 | 推送内容 | 触发点 |
|---|---|---|
| 案例审批通过入库 | 终态案例文档（`knowledge`） | `case_service.review_case()` 审批 `APPROVED` |
| 审批通过后修改定位结果 / 诊断明细 | 更新同一案例的终态 RAG 文档 | 定位结果更新时，若关联案例已 `APPROVED`，重新推送 |

### 不允许推送

| 阶段 | 原因 |
|---|---|
| 问题定位过程中 | 过程结论尚未收敛，不应进入 RAG |
| 转案例草稿 / 提交评审 / 评审中 | 未经过专家确认，质量不可靠 |
| 案例被驳回后重新提交 | 尚未最终入库 |

> **核心原则：RAG 只接收“已入库的终态案例”。**
> 审批通过后的定位结果修改，本质是“已入库案例的维护性更新”，可以推送，但必须以**同一案例文档**覆盖更新，而不是作为独立过程文档推送。

## 3. 总体架构

```text
┌────────────────────────────────────────────────────────────┐
│ TraceForge Backend                                          │
│                                                            │
│  案例审批通过（APPROVED） / 审批后定位结果更新              │
│        │                                                   │
│        ▼                                                   │
│  RAG Outbox Service      写入 sdd_rag_outbox                │
│        │                                                   │
│        ▼                                                   │
│  RAG Ingest Worker      轮询 outbox → 组装标准文档          │
│        │                                                   │
│        ▼                                                   │
│  RagProvider 适配层      HTTP / OpenSearch / Qdrant / ...   │
└────────────────────────────────────────────────────────────┘
```

关键设计：

- **事件先落库，不直接调 RAG**：利用 Outbox 模式保证“案例审批成功”和“RAG 推送”不处于同一事务，避免 RAG 故障影响案例审批主流程。
- **RAG 适配器可插拔**：通过配置切换 Provider。
- **文档以 `source_id=case_id` 为唯一键**：同一案例只保留一份 RAG 文档，重复审批/重试不会产生重复文档。

## 3.1 技术选型：消息队列 vs 本地 Outbox Worker

### 方案 A：本地 Outbox + 应用内 Worker（推荐现阶段）

```text
业务事务
  → sdd_rag_outbox
  → 应用内后台 Worker 定时/事件轮询
  → RagProvider → RAG
```

优点：

- 不引入 RabbitMQ / Kafka 等新组件，部署运维成本低。
- 与当前 TraceForge 后台任务风格一致（已有 `queue_provision_jobs`、`asyncio.to_thread`、背景任务）。
- Outbox 本身在数据库层保证不丢失；Worker 只负责“尽力消费并更新状态”。
- 重试、退避、死信都在同一个服务内实现，出问题好排查。

缺点：

- Worker 跑在业务进程里，多实例部署时需要分布式锁防止同一 outbox 被重复消费。
- 吞吐量有限，不适合超大批量/跨服务消费。

### 方案 B：消息队列（Redis Stream / RabbitMQ / Kafka）

```text
业务事务
  → sdd_rag_outbox（可选，作为可靠来源）
  → Producer 发送 MQ
  → Consumer 消费 → RagProvider → RAG
```

优点：

- 适合高吞吐、多消费者、跨团队/跨服务解耦。
- MQ 自身提供削峰、重试、死信等能力。

缺点：

- 需要额外引入并运维 MQ 组件。
- 当前 RAG 推送量很小（只有案例审批通过），MQ 属于过度设计。

### 推荐结论

**当前阶段采用“本地 Outbox + 应用内异步 Worker + Redis 分布式锁”**：

- 不引入新基础组件；
- 已有 Redis 可用来做 `locked_until` 防重复消费；
- 后续如果 RAG 消费方增加、跨服务消费或吞吐量上来，再在 `outbox_service` 与 worker 之间抽象一层 `RagTransport`，把“本地 Worker”平滑替换成“MQ Producer/Consumer”，业务触发点代码不需要改。

## 3.2 RAG 平台适配边界

当前**只设计 RAG 适配层**，不绑定具体 RAG 平台，也不做具体平台对接细节。

```text
TraceForge 业务
   → RAG Outbox Service
   → RagProvider（适配层协议）
   → 具体平台（WeKnora / LLMWiki / OpenSearch / Qdrant / 其他）
```

- 本方案只定义 `RagProvider` 协议、标准文档模型、Outbox 可靠推送机制。
- WeKnora、LLMWiki 等具体平台选择与适配实现**放到后续单独阶段再做**。
- 后续选型落地时，只需要新增一个 `RagProvider` 实现，并把 `RAG_PROVIDER` 配置切到对应平台，业务触发点代码不需要改。

## 4. 核心概念

### 4.1 标准 RAG 文档模型

```json
{
  "doc_id": "rag:case:case-xxx",
  "source_type": "case",
  "source_id": "case-xxx",
  "workspace_id": "ws-xxx",
  "namespace": "knowledge",
  "visibility": "workspace | public",
  "status": "published",
  "version": 1,
  "title": "接口偶发超时定位",
  "content": "案例结构化正文，拼接为可检索文本",
  "metadata": {
    "case_id": "case-xxx",
    "source_task_id": "task-xxx",
    "product_name": "...",
    "product_version": "...",
    "site_name": "...",
    "category": "PUBLIC | PRODUCT | SITE | TEMPORARY",
    "priority": "P0",
    "approved_at": "...",
    "reviewer_id": "...",
    "review_round": 1
  },
  "chunks": [
    {
      "id": "chunk-1",
      "text": "...",
      "heading": "根因"
    }
  ]
}
```

字段说明：

- `source_type` 固定为 `case`，当前只推送已入库案例。
- `namespace=knowledge`：正式知识库。
- `visibility`：
  - `PUBLIC` → `public`
  - `PRODUCT / SITE / TEMPORARY` → `workspace`（按需可调整）
- `version`：同一案例的文档版本，用于幂等 upsert。审批通过时推送 `version=1`；审批通过后若修改定位结果并重新推送，则递增到 `version+1`。

### 4.2 RAG Outbox 表

```sql
CREATE TABLE sdd_rag_outbox (
  id             VARCHAR(36) PRIMARY KEY,
  doc_key        VARCHAR(200) NOT NULL,          -- case:case_id
  payload_json   JSON NOT NULL,                  -- 标准化文档
  status         VARCHAR(20) NOT NULL DEFAULT 'PENDING',
  retry_count    INT NOT NULL DEFAULT 0,
  next_retry_at  DATETIME NULL,
  locked_until   DATETIME NULL,
  created_at     DATETIME NOT NULL,
  updated_at     DATETIME NOT NULL,
  UNIQUE KEY uk_rag_outbox_doc_key (doc_key)
);
```

状态机：

```text
PENDING → INDEXING → INDEXED
              │
              └── FAILED → RETRY（指数退避）→ INDEXED
```

- `doc_key` 唯一，同一案例重复入队不会产生重复推送。
- 支持批量重试与死信（超过最大重试次数后标记 `FAILED` 并告警）。

### 4.3 RAG Provider 接口

```python
class RagProvider(Protocol):
    def upsert(self, document: RagDocument) -> bool: ...
    def delete(self, doc_key: str, namespace: str) -> bool: ...
    def health_check(self) -> bool: ...
```

当前实现范围：

- `HttpRagProvider`：通用 REST API 适配，作为后续对接具体平台的基座。
- `MockRagProvider`：本地 Mock，用于测试和联调。

具体平台（WeKnora / LLMWiki / OpenSearch / Qdrant 等）的适配实现**后续选型后再做**。

## 5. 推送场景设计

### 5.1 推送场景：案例审批入库后的终态知识

#### 触发点 1：审批通过入库

在 `case_service.review_case()` 中，`conclusion == "approve"` 且事务提交成功后，写入 outbox：

```python
# 伪代码
case.status = CaseStatus.APPROVED.value
db.commit()

rag_outbox_service.enqueue_case_published(db, case)
```

#### 触发点 2：审批通过后修改定位结果

案例已 `APPROVED` 后，如果用户修改了关联任务的定位结果 / 诊断明细，需要把最新结论同步到 RAG：

```python
# 伪代码：diagnosis_result 更新成功后
if case_linked_to_task and case.status == CaseStatus.APPROVED.value:
    rag_outbox_service.enqueue_case_published(db, case)  # 复用同一 doc_key，version + 1
```

> 这里推送的不是“过程知识”，而是**已入库案例的更新版本文档**。
> 更新必须复用 `doc_key=case:case_id`，覆盖旧内容，避免生成重复文档。
> 只有定位结果修改发生在**案例审批通过之后**才推送；审批通过前仍不推送。

#### 推送内容

- `title`：案例标题
- `content`：由案例结构化字段拼接为 Markdown：
  - 问题描述
  - 产品 / 版本 / 局点
  - 分析过程
  - 根因
  - 解决方案
  - 代码上下文
  - 对话快照摘要
  - 诊断明细
  - 最终评审意见（通过）
- `metadata`：`case_id`、`source_task_id`、`category`、`priority`、`product_name`、`product_version`、`site_name`、`approved_at`、`reviewer_id`、`review_round`
- `namespace=knowledge`
- `visibility`：
  - `PUBLIC` → `public`
  - `PRODUCT / SITE / TEMPORARY` → `workspace`（按需可调整）

#### 更新策略

- 同一 `case_id` 只保留一份终态文档。
- 案例被驳回后重新提交再审批通过时，以最新 `review_round` 覆盖。
- 审批通过后如果修改了关联定位结果，以同一 `doc_key` 重新入队，`version + 1` 覆盖更新。
- 除了“定位结果修改”这一种维护性更新外，其他案例字段修改默认不推送（如有需要可单独扩展“案例维护同步”流程）。

## 6. 配置设计

```dotenv
# .env.example
RAG_ENABLED=false
RAG_PROVIDER=httpx          # 当前仅适配层实现：httpx / mock；具体平台后续按选型追加
RAG_API_BASE_URL=http://127.0.0.1:8080
RAG_API_KEY=
RAG_API_TIMEOUT_SECONDS=10
RAG_INGEST_BATCH_SIZE=20
RAG_RETRY_MAX=5
RAG_RETRY_BACKOFF_BASE_SECONDS=2
```

对应 `backend/app/config.py` 新增配置节：

```python
class RagSettings(BaseModel):
    enabled: bool = False
    provider: str = "httpx"
    api_base_url: str = ""
    api_key: str = ""
    api_timeout_seconds: int = 10
    ingest_batch_size: int = 20
    retry_max: int = 5
    ...
```

## 7. 可靠性设计

1. **业务事务与推送解耦**
   - 案例 `APPROVED` 提交后先写入 `sdd_rag_outbox`。
   - 若 RAG 服务不可用，只影响 outbox，不影响案例审批成功响应。

2. **幂等**
   - 以 `doc_key=case:case_id` + `version` 保证重复推送不产生重复文档。
   - Provider 侧建议支持按 `doc_id` upsert/delete。

3. **重试与退避**
   - 失败后按 `2^n` 秒递增重试，最多 `RAG_RETRY_MAX` 次。
   - 超过后标记 `FAILED`，保留 payload 供人工补偿。

4. **顺序**
   - 同一个 `doc_key` 只处理最新版本，旧版本 outbox 可被覆盖/丢弃。
   - 不同 `doc_key` 无严格顺序要求。

5. **审计**
   - 每次 outbox 入队、推送成功、失败、重试都写 `audit_log`。

## 8. 权限与安全

- 已入库案例的 `PUBLIC` 分类可进入公共知识库，其他分类保持工作区隔离。
- 推送前做脱敏：
  - 不包含用户密码、Token、密钥等敏感字段。
  - 代码上下文如包含私有路径，按工作区隔离。
- RAG API Key 只存在服务端配置，不进入前端。

## 9. 代码结构建议

```text
backend/app/domains/rag/
├── __init__.py
├── config.py                  # RagSettings
├── schemas.py                 # RagDocument / RagChunk / RagOutboxStatus
├── models.py                  # SddRagOutbox
├── services/
│   ├── outbox_service.py      # enqueue / retry / ack / dead-letter
│   ├── document_builder.py    # case → RagDocument
│   └── ingest_worker.py       # asyncio 后台轮询任务
├── providers/
│   ├── base.py                # RagProvider Protocol（适配层核心）
│   ├── httpx_provider.py      # 通用 HTTP 适配（后续平台对接基于此扩展）
│   └── mock_provider.py       # 本地 Mock，测试用
│   # 具体平台适配（WeKnora / LLMWiki / OpenSearch / Qdrant）后续按选型结果新增
└── routers.py                 # 可选：outbox 状态查询/重试接口
```

## 10. 触发点接入清单

| 文件 | 改动 |
|---|---|
| `backend/app/domains/case_center/services/case_service.py` | `review_case()` approve 后调用 `rag_outbox_service.enqueue_case_published()` |
| `backend/app/domains/task/services/diagnosis_result_service.py` | 定位结果更新成功时，若关联案例已 `APPROVED`，则调用 `rag_outbox_service.enqueue_case_published()` 覆盖更新 |
| `backend/app/config.py` | 新增 `RagSettings` |
| `backend/.env.example` | 新增 `RAG_*` 配置示例 |
| `backend/alembic/versions/xxx_add_rag_outbox.py` | 新增 `sdd_rag_outbox` 表 |

不需要接入：

- 问题定位过程中的定位结果保存/编辑（审批通过前）
- 一键总结问题案例成功
- 转案例草稿 / 提交评审 / 评审中 / 驳回

## 11. 实施计划

### Phase 1：RAG 基础能力 + 案例终态推送（当前目标）

1. 新增 `sdd_rag_outbox` 表。
2. 实现 `RagProvider` 协议 + `MockRagProvider` + `HttpRagProvider`。
3. 实现 `outbox_service` 与后台 `ingest_worker`。
4. 在 `case_service.review_case()` APPROVED 后入队。
5. 在 `diagnosis_result_service` 中增加：关联案例 `APPROVED` 时，定位结果更新后复用同一 `doc_key` 入队更新。
6. 补测试：审批通过会入队、审批通过后修改定位结果会覆盖更新、失败重试、幂等 upsert。

### Phase 2：具体 RAG 平台对接（选型后做）

1. 确定平台（WeKnora / LLMWiki / 其他）。
2. 基于 `HttpRagProvider` 新增对应平台适配实现。
3. 配置 `RAG_PROVIDER` 与 `RAG_API_*`，做真实联调。
4. 验证文档 upsert / delete、权限隔离、索引状态等。

### Phase 3：RAG 检索与复用（可选）

1. Provider 增加 `search(query, filters)`。
2. 问题定位中可“相似案例推荐”：
   - 输入：当前现象/根因
   - 过滤：`namespace=knowledge`、`visibility`、`category`
   - 返回：相似案例列表，供诊断过程参考。
3. 前端在诊断结果卡片或对话框中展示“相似案例”。

## 12. 测试策略

- **Outbox 单元测试**：入队、同 key 覆盖、删除事件。
- **Document Builder 测试**：案例 → 标准文档字段完整。
- **Provider 测试**：使用 `MockRagProvider` 断言 upsert/delete 调用；`HttpRagProvider` 使用 `respx`/`httpx.MockTransport`。
- **集成测试**：
  - 审批通过后 outbox 出现 `PENDING`。
  - worker 消费后变为 `INDEXED`。
  - RAG 服务异常时进入 `RETRY`，恢复后成功。
  - 问题定位过程中定位结果更新/一键总结成功，**不产生**任何 outbox 记录。
  - 审批通过后再更新定位结果，**产生**更新 outbox，且 `doc_key=case:case_id` 覆盖旧文档，不重复。
- **权限测试**：公开/工作区隔离 metadata 正确。