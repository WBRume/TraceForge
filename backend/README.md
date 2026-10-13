# TraceForge 后端启动与开发

[项目首页](../README.md) · [全部文档](../README.md#文档导航) · [前端与桌面](../frontend/README.md) · [Docker 部署](../deploy/docker/README.md)

后端提供任务与 Agent 执行、工作区与资产、案例与诊断规程、API Mock、搜索和实时协作接口。

## 首次启动

以下命令从仓库根目录开始，使用 Windows PowerShell。需要 Python 3.10+、MySQL 8.0、Redis 和 Git；Linux 部署可使用 [Docker](../deploy/docker/README.md)，镜像已处理 Windows 专用依赖。

### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
cd backend
Copy-Item .env.example .env
```

已有 `.env` 时保留现有文件，只补充新增配置。以下后端命令均在 `backend/` 目录和该虚拟环境中执行。

### 2. 准备数据库和 Redis

先启动 MySQL 与 Redis。在 MySQL 中创建数据库：

```sql
CREATE DATABASE sdd_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

编辑从[配置模板](.env.example)复制得到的本地 `.env`，至少核对以下项目：

| 配置 | 填写内容 |
| --- | --- |
| `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME` | 本机数据库的地址、账号和库名 |
| `JWT_SECRET_KEY` | 自己生成并持久保存的随机密钥，替换模板值 |
| `REDIS_URL`、`REDIS_PASSWORD` | Redis 地址和密码；无认证时密码留空 |
| `DISTRIBUTED_LOCK_BACKEND` | 模板使用 `redis`；消息撤销等操作依赖它 |
| `AGENT_BACKEND` | `claude-code`、`opencode` 或 `dsh`，连接方式见下文 |

可用 `python -c "import secrets; print(secrets.token_urlsafe(48))"` 生成 JWT 密钥。不要提交 `.env` 或凭据。

基础搜索使用 SQLite 即可，在 `.env` 中设置 `SEARCH_BACKEND=sqlite`，不需要另装 Elasticsearch；搜索分页仍需要 Redis。完整配置见[历史搜索部署](../deploy/search/README.md)。

### 3. 迁移并启动

```powershell
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

已有数据库应先备份再升级。保持单 worker，启动时不要加 `--reload`，以免自动重载中断任务和 CLI 会话。需要远程访问时改为 `--host 0.0.0.0`，并同步配置前端地址、CORS 与网络访问范围。

检查 [存活状态](http://localhost:8000/health)、[就绪状态](http://localhost:8000/health/ready) 和 [API 文档](http://localhost:8000/docs)，再按[前端指南](../frontend/README.md#开发)启动页面。首个注册账号自动成为管理员，可进入系统配置管理 Agent 等连接。

## 配置 Agent

只需配置要使用的后端；模型能否使用取决于对应 Agent 服务的配置和授权。

| Agent | 准备工作 | 环境配置 |
| --- | --- | --- |
| Claude Code | 在运行 TraceForge 后端的机器安装并完成登录或 API 授权，确认运行账号能执行 CLI | `AGENT_BACKEND=claude-code`、`CLAUDE_CLI_PATH=claude` |
| OpenCode | 启动可访问的 OpenCode 服务，配置可用模型 | `AGENT_BACKEND=opencode`、`OPENCODE_SERVER_URL`；开启认证时填写 `OPENCODE_SERVER_USERNAME` / `OPENCODE_SERVER_PASSWORD` |
| DSH | 准备可访问的 DSH 服务与可用模型 | `AGENT_BACKEND=dsh`、`DSH_SERVER_URL`；按服务要求填写 `DSH_BROWSER_TOKEN` / `DSH_BROWSER_COOKIE` |

模板中的 OpenCode / DSH 地址分别为 `http://127.0.0.1:4097`、`http://127.0.0.1:3080`，需改成实际地址。地址必须能从后端进程访问；容器内的 `127.0.0.1` 指向容器自身。

管理员也可在系统配置中管理受支持的功能和连接，已保存的配置会覆盖对应环境默认值。任务使用其绑定的 Agent；修改平台默认值不会自动迁移既有任务。

### 本机 Agent 资源

本机资源任务由 Electron / Tauri 客户端创建，使用桌面内置资源服务。服务器必须能访问客户端所在内网，需要配置：

```dotenv
LOCAL_RESOURCES_MODE=intranet
LOCAL_RESOURCES_ENCRYPTION_KEY=<持久保存的 Fernet 密钥>
LOCAL_RESOURCES_ALLOWED_NETWORKS=<允许访问的客户端网段>
```

密钥可用 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 生成；API 和 worker 使用同一密钥。修改环境后重启后端，Docker 需重建容器配置。客户端会按需启动资源服务，无需另外安装宿主程序。服务器任务的本地代码同步见[本地协同](../frontend/README.md#本地协同)。

## 其他配置

- **完整变量**：以 [`.env.example`](.env.example) 和 [`app/config.py`](app/config.py) 为准。配置文件固定读取 `backend/.env`，进程环境变量可覆盖它。
- **持久化目录**：Skills、CLI 状态、上传文件、任务快照和工作区目录需要保留。主要存储路径的相对值以 `backend/` 为基准解析，部署时建议使用明确的绝对路径或持久化卷。
- **协同快照**：在 `.env` 设置 `COLLABORATION_SNAPSHOT_ROOT=G:/TraceForgeData/collaboration`，重启后端后，新建存储使用该目录；留空则使用 `TASK_SESSION_SNAPSHOT_ROOT/collaboration`。已有任务会保留原存储位置，配置修改不搬迁或删除旧数据。Git 文件内容复用 `TASK_SESSION_SNAPSHOT_ROOT` 下的会话快照，备份时需要同时保留两个目录与数据库。
- **配置密钥**：`FEATURE_CONFIG_MASTER_KEY` 用于保存功能配置中的密钥；未单独设置时从 JWT 密钥派生。与数据库一起备份相关密钥，避免换密钥后无法解密既有配置。
- **计划文档**：在“设置 → 工作区设置 → 计划文档目录”配置相对任务根目录的路径。未配置时不扫描；历史任务缺少初始快照时会提示，不展示全部存量文档。
- **可选能力**：[搜索与向量检索](../deploy/search/README.md)、[语音输入](../frontend/README.md#语音输入构建时选择-api--离线--关闭)、[诊断规程与实验环境](app/domains/diagnosis_playbook/README.md)分别配置。

## 数据库迁移

```powershell
python -m alembic current
python -m alembic heads
python -m alembic upgrade head
```

新增迁移和检查要求见 [Alembic 说明](alembic/README.md)。应用升级前先完成迁移，不通过重建数据库处理版本差异。

## 开发检查

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python check_file_lines.py
python -m pytest tests
```

后端测试限定 `tests` 目录，避免收集 `tmp/` 中外部项目的测试。真实 OpenCode 验收会访问真实模型与服务，应按[专用说明](tests/live_opencode/README.md)显式运行。

### 代码规范

统一配置为 [`ruff.toml`](ruff.toml)，Ruff 版本由 [`requirements-dev.txt`](requirements-dev.txt) 固定；升级时同步调整 `required-version`。目标 Python 3.10，120 列、4 空格缩进、双引号。仓库根目录运行 `python -m ruff check backend` 也会读取同一配置。

规则检查未定义名称、未使用导入、导入排序、可变默认值、闭包捕获、异常链和后台任务引用等。生产函数的圈复杂度与分支数上限均为 15，语句数上限为 60；超限时按职责重构。测试和 Alembic 迁移仅豁免这三项结构指标。

允许有意义的返回中间变量、显式异常忽略、普通 if/else 和嵌套资源上下文；不强制所有函数添加文档字符串或类型注解，不对长 URL、字符串和中文注释强制截断。FastAPI 的依赖声明使用精确白名单。

默认检查不改源码，不启用不安全自动修复。`F401` 仍报告但不自动删除导入，避免破坏 ORM 注册或插件加载；公开导出使用 `__all__` 或显式重导出。局部例外用带规则编号和原因的 `# noqa: CODE`，不用整文件统一忽略。

日常先检查具体文件、查看修复差异，再运行相关测试；提交前执行上面的全量检查。GitHub Actions 的 `Source quality` 工作流检查 Ruff、格式和文件行数。

### 单文件行数

Python、Vue、TypeScript、JavaScript、样式与 HTML 源文件最多 1500 行，含空行和注释；Vue 的 template / script / style 合并计算。检查覆盖 Git 已跟踪与未忽略的新文件，存量超限文件也会失败。

前端 build / test 脚本先执行门禁，后端完整 pytest 包含门禁测试。具体前端命令见[前端指南](../frontend/README.md#适配边界和检查)。

## 常见问题

| 现象 | 优先检查 |
| --- | --- |
| API 启动或就绪检查失败 | 虚拟环境、依赖、`DB_*` 配置、迁移版本，以及 Redis 是否可访问 |
| Agent 无法执行 | CLI 是否对服务运行账号可用；远端 URL、认证和模型是否正确 |
| 前端请求失败或 404 | API 是否为当前代码启动；Web 开发代理 `VITE_DEV_API_TARGET`，桌面端的服务器地址配置 |
| 跨域请求被拒绝 | `CORS_ORIGINS` 是否包含实际前端来源 |
| 新的环境配置没有生效 | 是否重启服务；Docker 是否重新创建容器；系统配置是否已有覆盖值 |
| 搜索没有结果 | 搜索是否开启、回填状态、Redis；使用 ES 时再检查索引和向量配置 |

默认日志在 `backend/logs/sdd_app.log`，Agent 会话日志在 `backend/logs/ai_sessions/`；可通过 `LOG_DIR` / `AI_SESSION_LOG_DIR` 调整。
