# TraceForge 全局搜索部署

[项目首页](../../README.md) · [后端配置](../../backend/README.md) · [Docker 部署](../docker/README.md)

## PostgreSQL

业务库需使用 PostgreSQL 18，在 `public` 安装 `pg_jieba` 和 `vector`。Alembic 首次升级时创建扩展、倒排索引和向量索引。Redis 保存用户隔离的分页快照和向量请求限额。

```dotenv
SEARCH_ENABLED=true
SEARCH_BACKEND=postgresql
SEARCH_WORKERS_ENABLED=true
SEARCH_EMBEDDING_PROTOCOL=openai_compatible
SEARCH_EMBEDDING_ENDPOINT=https://api.siliconflow.cn/v1/embeddings
SEARCH_EMBEDDING_MODEL=BAAI/bge-m3
SEARCH_EMBEDDING_API_KEY=
```

复制配置到本机 `backend/.env` 或部署目录的 `.env`，也可在系统配置的全局搜索页面设置向量服务。密钥只保存在服务端。PostgreSQL 向量索引接受 1024 维向量。

任务、用户及助手的可见消息、已入库及技术验证案例、诊断规程使用同一检索范围。全文检索使用 pg_jieba 分词、GIN 索引和标题加权排序。混合检索使用 PostgreSQL 全文排序、pgvector 余弦近邻和 RRF 融合。向量服务未配置或请求失败时，继续返回关键词结果，响应标明本次执行的检索模式。配置向量服务会将可检索正文与查询发送至该服务；原始工具输出、思考过程和未发布的执行消息不进入索引。

向量候选在融合前须满足余弦相似度门槛。默认模型实测采用 0.58，单个西文词及最多四字的中文短词采用 0.70。关键词路径独立返回全文命中。

业务写入与变更事件在同一事务内提交。搜索 worker 回填和更新 PostgreSQL 投影，再由向量 worker 异步计算。正文更新时删除旧向量，检索回表复核权限、来源版本和删除状态。更换向量模型会使用新的向量空间并回填。默认由 API 启动两个 worker；使用 Compose 独立 worker 时，在部署 `.env` 设置 `SEARCH_WORKERS_ENABLED=false`，启动 `search` profile。API 和 worker 使用同一业务库、Redis 和密钥。

```powershell
python -m app.domains.search.cli status
python -m app.domains.search.cli retry
```

`retry` 重排失败队列。供应商发生 HTTP 402、429 或临时服务故障时，后台按退避规则重试。停用搜索时设置 `SEARCH_ENABLED=false`，保留业务数据和索引。

## Elasticsearch

- `SEARCH_BACKEND=elasticsearch` 使用已激活的 Elasticsearch 索引。
- `SEARCH_BACKEND=auto` 优先使用已配置并激活的 Elasticsearch，连接失败时回退 PostgreSQL。
- 在系统配置填写 `SEARCH_ES_URL`、认证信息和需要的向量服务。Compose 的 `search-local-es` profile 可启动开发用 Elasticsearch 9。

Elasticsearch 使用两个物理索引存放任务与消息、案例与诊断规程。v3 为四类内容建立向量索引。切换到新目标需要回填、核验并激活；系统配置可自动执行，以下命令可手动操作。

```powershell
python -m app.domains.search.cli configure
python -m app.domains.search.cli create-index --target traceforge-search-v3-000001 --embedding-profile <profile-id>
python -m app.domains.search.cli backfill --target traceforge-search-v3-000001
python -m app.domains.search.cli verify --target traceforge-search-v3-000001
python -m app.domains.search.cli activate --target traceforge-search-v3-000001
```

纯关键词 Elasticsearch 可省略 `configure` 和 `--embedding-profile`。激活会切换读别名，旧目标留在 standby。PostgreSQL 持续维护自己的投影，可直接切回。
