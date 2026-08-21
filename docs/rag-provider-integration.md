# RAG Provider 对接文档

> 本文档面向后续具体 RAG 平台（WeKnora / LLMWiki / OpenSearch / Qdrant 等）对接。
> 当前 TraceForge 已完成 **RAG 适配层**，业务侧已经在“案例审批通过”和“审批后定位结果更新”时写入 outbox；
> 具体平台对接时只需要新增一个 `RagProvider` 实现并注册。

## 1. 当前已实现

```text
backend/app/domains/rag/
├── __init__.py
├── config.py（配置在 app/config.py 中）
├── schemas.py                 # RagDocument / RagChunk / RagOutboxStatus
├── models.py                  # SddRagOutbox
├── providers/
│   ├── base.py                # RagProvider Protocol
│   ├── httpx_provider.py      # 通用 HTTP Provider
│   └── mock_provider.py       # Mock Provider
└── services/
    ├── document_builder.py    # case → RagDocument
    ├── outbox_service.py      # enqueue / claim / ack / retry
    └── ingest_worker.py       # 后台轮询消费者
```

### 已接入业务触发点

| 触发点 | 文件 | 行为 |
|---|---|---|
| 案例审批通过 | `case_center/services/case_service.py` | 调用 `outbox_service.enqueue_case_published()` |
| 审批通过后修改定位结果 | `task/services/diagnosis_result_service.py` | 复用同一 `doc_key` 覆盖更新 |

### 已有表

- `sdd_rag_outbox`：
  - `doc_key` 唯一（当前格式 `case:{case_id}`）
  - `payload_json` 标准文档
  - `status`: `PENDING / INDEXING / INDEXED / FAILED`
  - `retry_count` / `error_message` / `next_retry_at` / `locked_until`

## 2. 数据流

```text
案例审批通过 / 审批后定位结果更新
   │
   ▼
outbox_service.enqueue_case_published()
   │
   ▼
sdd_rag_outbox（PENDING）
   │
   ▼
RAG Ingest Worker 轮询
   │
   ▼
RagProvider.upsert(document)
   │
   ▼
成功 → INDEXED / 失败 → retry_count + next_retry_at
```

## 3. 标准文档结构

```json
{
  "doc_id": "rag:case:{case_id}",
  "source_type": "case",
  "source_id": "{case_id}",
  "workspace_id": "ws-xxx",
  "namespace": "knowledge",
  "visibility": "workspace | public",
  "status": "published",
  "version": 1,
  "title": "案例标题",
  "content": "Markdown 结构化正文",
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
    { "id": "case-xxx:root-cause", "text": "...", "heading": "根因" }
  ]
}
```

### 更新策略

- 同一 `doc_key` 只保留一条 outbox 记录。
- 重复入队会：
  - `version + 1`
  - 重置为 `PENDING`
  - 覆盖 `payload_json`
- 因此最终推送的是最新版本文档，不会产生重复。

## 4. 对接新 RAG 平台

### 4.1 实现 RagProvider 协议

在 `backend/app/domains/rag/providers/` 下新增文件，例如 `weknora_provider.py`：

```python
from app.domains.rag.providers.base import RagProvider
from app.domains.rag.schemas import RagDocument


class WeKnoraRagProvider(RagProvider):
    def upsert(self, document: RagDocument) -> bool:
        # 把 document 转换为 WeKnora API 参数
        # 调用 WeKnora 上传/更新接口
        # 成功返回 True，失败返回 False（worker 会自动重试）
        ...

    def delete(self, doc_key: str, namespace: str = "knowledge") -> bool:
        # 删除接口（当前业务未强制使用，但协议保留）
        ...

    def health_check(self) -> bool:
        ...
```

### 4.2 注册 Provider

在 `backend/app/domains/rag/providers/__init__.py` 的 `create_provider()` 中增加分支：

```python
if provider_name == "weknora":
    return WeKnoraRagProvider(
        base_url=settings.RAG_API_BASE_URL,
        api_key=settings.RAG_API_KEY,
    )
```

### 4.3 配置示例

```dotenv
RAG_ENABLED=true
RAG_PROVIDER=weknora            # 或 llmwiki / httpx / mock
RAG_API_BASE_URL=http://127.0.0.1:8080
RAG_API_KEY=your-token
RAG_API_TIMEOUT_SECONDS=10
```

### 4.4 启动 Worker

`RAG_ENABLED=true` 时，FastAPI 启动会自动拉起：

```text
RAG ingest worker started provider=weknora
```

## 5. 通用 HTTP Provider 现约

如果平台只是简单的 REST API，可以直接用 `HttpRagProvider`：

| 方法 | 路径 | 请求体 |
|---|---|---|
| POST | `{base}/documents/upsert` | `{"document": {...标准文档...}}` |
| DELETE | `{base}/documents/{doc_key}` | - |

鉴权头：

```http
Authorization: Bearer {RAG_API_KEY}
Content-Type: application/json
```

如果目标平台接口不是这个路径，建议直接新增平台专用 Provider，而不是改通用 HTTP Provider。

## 6. Outbox 手动运维

### 查询待推送

```sql
SELECT id, doc_key, status, retry_count, next_retry_at
FROM sdd_rag_outbox
WHERE status IN ('PENDING', 'FAILED')
ORDER BY created_at;
```

### 人工重推失败记录

直接把失败记录重置为 `PENDING`：

```sql
UPDATE sdd_rag_outbox
SET status = 'PENDING', retry_count = 0, error_message = NULL, next_retry_at = NULL, locked_until = NULL
WHERE status = 'FAILED';
```

### 删除某条 outbox（如不想再推送）

```sql
DELETE FROM sdd_rag_outbox WHERE doc_key = 'case:case-xxx';
```

## 7. 对接验收测试

接入新平台后至少验证：

- [ ] `RAG_ENABLED=true`、`RAG_PROVIDER=新平台` 时 worker 能启动
- [ ] 案例审批通过后 outbox 从 `PENDING` → `INDEXED`
- [ ] 审批后修改定位结果后，同一 `doc_key` 版本 `+1` 并再次 `INDEXED`
- [ ] RAG 平台关闭时 outbox 进入重试，恢复后最终 `INDEXED`
- [ ] 超过 `RAG_RETRY_MAX` 后进入 `FAILED`
- [ ] 权限字段：`PUBLIC` → `public`，其他 → `workspace`