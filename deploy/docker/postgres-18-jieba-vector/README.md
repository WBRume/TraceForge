# PostgreSQL 18.7 + pg_jieba + pgvector Docker 环境

本目录包含集成了 **PostgreSQL 18.7**、**pgvector (向量检索)** 以及 **pg_jieba (结巴中文分词)** 的自定义 Docker 镜像构建与编排配置。

---

## 包含组件及版本
- **PostgreSQL**: `18.7 (Debian 18.7-1.pgdg12+2)`
- **pgvector**: `v0.8.7` (支持向量检索与索引，如 HNSW, IVFFlat)
- **pg_jieba**: `v1.1.1` (包含完整 cppjieba 词库与 HMM 模型，提供 jiebacfg 分词器)

## 本地镜像标签
- `postgres:18.7-jieba-vector`
- `postgres-18-jieba-vector:latest`

---

## 快速使用

### 方式 1：Docker Compose 启动（推荐）
在当前目录下执行：
```bash
docker compose up -d
```
启动后容器将映射主机端口 `5432`，默认数据库为 `aidb`，用户为 `postgres`，密码为 `mysecretpassword`。

### 方式 2：Docker CLI 直接运行
```bash
docker run -d \
  --name postgres-18-ai \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=mysecretpassword \
  -e POSTGRES_DB=aidb \
  -p 5432:5432 \
  -v pgdata:/var/lib/postgresql \
  postgres:18.7-jieba-vector
```

---

## 验证与测试

### 1. 进入数据库控制台
```bash
docker exec -it postgres-18-ai psql -U postgres -d aidb
```

### 2. 启用并验证扩展

用于 TraceForge 时，在业务库运行 `alembic upgrade head`，基线迁移会启用这两个扩展。单独启动 PostgreSQL 做下文测试时，在 `aidb` 中执行以下 SQL。

```sql
CREATE EXTENSION IF NOT EXISTS pg_jieba WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'pg_jieba');
```

### 3. 测试中文分词
```sql
SELECT to_tsvector('jiebacfg', '开源中文分词与向量检索集成测试成功');
```

### 4. 测试向量运算与检索
```sql
-- 创建测试表
CREATE TABLE test_items (
    id serial PRIMARY KEY,
    content text,
    embedding vector(3)
);

-- 插入向量数据
INSERT INTO test_items (content, embedding) VALUES
('项目A', '[1, 2, 3]'),
('项目B', '[4, 5, 6]'),
('项目C', '[1, 0, 0]');

-- 计算余弦相似度并排序
SELECT content, embedding <=> '[1, 2, 2]' AS distance
FROM test_items
ORDER BY distance ASC;
```
