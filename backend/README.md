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

### OpenCode / DSH 服务切换

系统配置先验证新地址的连接、认证和协议，通过后保存并推进对应 Agent 的地址版本。后续派发使用新配置，已派发的作业继续关联原执行服务。TraceForge 展示已保存的聊天历史、作业结果和产物，Agent 上下文由 OpenCode 或 DSH 管理。备份、恢复和验证由运维人员在 Agent 侧完成。

1. **清点未结束作业。** 在原服务上等待作业完成，或请求停止并确认结果。队列中心显示「旧服务不可达，执行结果未知」时，作业记录、已知进度和原服务关联会保留。原服务恢复后先核对结果，确认仍在运行时再停止。确认旧作业已结束或已停止前，同一工作区暂停派发替代作业。其他工作区可以使用新服务。
2. **按 Agent 备份会话数据。** 以旧实例运行账号和实际部署配置为准，容器部署需核对挂载的持久化卷。

   - **OpenCode**：备份实际使用的会话数据库和关联的持久化数据。使用 SQLite 时，服务在线期间应通过 SQLite 的备份机制获取一致快照。只需保留指定会话时，也可使用部署版本支持的原生会话导出与导入。 [OpenCode 数据位置](https://opencode.ai/docs/cli/paths) · [会话命令](https://opencode.ai/docs/cli/commands/#session) · [SQLite 备份说明](https://www.sqlite.org/backup.html)
   - **DSH**：备份实际配置的完整会话存储目录，保留按工作目录和会话 ID 组织的目录结构，以及会话目录内的持久化文件。使用 JSONL 持久化时，以部署配置指定的会话根目录为准。 [DSH 会话持久化说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/session/session-persistence-jsonl/README.md)

3. **记录运行环境。** 记录 Agent 版本、启动配置和工作目录映射。更换主机时，另行备份工作区的未提交改动及需要保留的本地文件。
4. **在目标服务验证后再下线旧服务。** 从 TraceForge 后端验证新地址和认证可用，在目标 Agent 上确认所需会话能按原 ID 打开、会话归属正确且工作目录匹配，并确认未结束作业已收尾。
5. **续接任务。** 地址切换后，打开存量任务时会在发送前核验原会话，并分批检查同一 Agent 地址版本下的其他存量会话。通过结果按原会话 ID 和工作目录保存，可在后续打开和发送时复用。在当前版本上新建的会话由实际创建确认，无需补查。原会话确认不可用时，任务保留历史，选择「新建会话」后才能发送。若在同一地址补恢复了原会话，刷新任务页面即可重新核验。手动新建时请补充所需背景，首条请求只使用本次输入。查询超时、服务不可达或认证失败时保留原会话关联，发送遇到这类异常时走普通会话中断流程。

### 接入新的 Agent

实现 [AgentBackend](app/agents/contract.py) 的执行、停止和资源释放接口，以及 `bind_tools(request, tools)` 异步上下文管理器。在应用启动时通过 [register_backend](app/agents/registry.py) 注册；内置接入入口是 [adapters/register_all](app/agents/adapters/__init__.py)。注册后，工作区选项、平台配置、连接测试和模型选择读取同一份元数据，不需要在业务 domain 或前端增加 Agent 名称分支。

`tools` 遵循 [AgentToolContext](app/agents/tools.py)：`definitions` 提供工具名、说明和 JSON Schema，`await tools.invoke(name, arguments, call_id)` 返回 `AgentToolResult(data, is_error)`。Adapter 将定义交给 Agent，并把每次调用结果送回同一模型回合；校验失败允许模型修正参数。MCP Adapter 可复用 [serve_tools](app/agents/tool_transports/mcp.py)，原生工具 Adapter 直接绑定回调，无需启动 HTTP 服务。

```python
register_backend(
    "my-agent",
    MyAgentAdapter,
    label="My Agent",
    settings=(
        AgentSetting(
            "server_url",
            ConfigField(
                "my_agent_url",
                "服务地址",
                "MY_AGENT_URL",
                "url",
                default_value="http://127.0.0.1:9000",
            ),
        ),
        AgentSetting(
            "api_key",
            ConfigField(
                "my_agent_key",
                "访问密钥",
                "MY_AGENT_KEY",
                "secret",
            ),
        ),
    ),
)
```

`AgentSetting` 来自 `app.agents.registration`，`ConfigField` 来自 `app.domains.system_config.services.config_fields`。字段同时用于环境默认值、加密保存、脱敏展示、连接测试与构造参数映射；新增字段无需修改全局 `Settings`。`model_format="provider/model"` 可声明模型标识格式，否则由 Adapter 接收不透明模型名。带凭据热更新逻辑的 Adapter 可通过 `runtime_kwargs` 配置运行实例；配置草稿测试使用独立参数，不覆盖运行配置。

工具绑定必须限制在本次调用，隔离会话权限，并在成功、失败、超时及取消时清理；运行结束后的调用由领域执行器拒绝。领域工具只确认业务产物通过校验，现有业务服务负责落库。新 Adapter 默认声明工具绑定能力，未实现 `bind_tools` 会在注册时失败。既有 DSH 与 Mock 明确声明不支持领域工具绑定，普通会话仍可使用；OpenCode 当前采用本机 MCP 与独立目录，保留其同机部署限制。

接入回归可参考 [原生 Adapter 契约测试](tests/agents/test_tool_registration.py)，其中验证了注册后执行现有领域回合、校验修正、重复提交、并发隔离、退出撤销，以及配置保存和连接草稿隔离。

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
- **结项证据附件**：在 `.env` 设置 `TASK_EVIDENCE_ATTACHMENT_ROOT` 后重启后端，例如 `TASK_EVIDENCE_ATTACHMENT_ROOT=G:/TraceForgeData/evidence-attachments`。默认值为 `storage/task-evidence-attachments`。切换目录时，先停后端并将原目录内按任务 ID 存放的文件复制到新目录，再启动后端。
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

默认使用 pytest-xdist 自动并行执行，最多启动 8 个进程；可通过 `python -m pytest tests -n 4` 指定进程数。快照目录逐例隔离。

串行执行及统计慢用例使用 `python -m pytest tests -n 0 --durations=25`。并行调度只用于提高吞吐，不能作为单用例优化或串行耗时对照的依据。

### 生成跨端协议

安装后端依赖和前端 npm 依赖后，改动 Python 协议模型或 DSH 诊断工具定义时，从仓库根目录运行以下命令。Python 脚本导出 Web 和桌面运行时共用的 JSON Schema，并生成 DSH 工具清单。Node 脚本再从 JSON Schema 生成 TypeScript 类型和校验器使用的 Schema 索引。提交时一并更新生成文件。

```powershell
python backend/scripts/export_protocols.py
node frontend/scripts/generate-contracts.mjs
```

### 代码规范

统一配置为 [`ruff.toml`](ruff.toml)，Ruff 版本由 [`requirements-dev.txt`](requirements-dev.txt) 固定；升级时同步调整 `required-version`。目标 Python 3.10，120 列、4 空格缩进、双引号。仓库根目录运行 `python -m ruff check backend` 也会读取同一配置。

规则检查未定义名称、未使用导入、导入排序、可变默认值、闭包捕获、异常链和后台任务引用等。生产函数的圈复杂度与分支数上限均为 15，语句数上限为 60；超限时按职责重构。测试和 Alembic 迁移仅豁免这三项结构指标。

允许有意义的返回中间变量、显式异常忽略、普通 if/else 和嵌套资源上下文；不强制所有函数添加文档字符串或类型注解，不对长 URL、字符串和中文注释强制截断。FastAPI 的依赖声明使用精确白名单。

默认检查不改源码，不启用不安全自动修复。`F401` 仍报告但不自动删除导入，避免破坏 ORM 注册或插件加载；公开导出使用 `__all__` 或显式重导出。局部例外用带规则编号和原因的 `# noqa: CODE`，不用整文件统一忽略。

日常先检查具体文件、查看修复差异，再运行相关测试；提交前执行上面的全量检查。GitHub Actions 的 `Source quality` 工作流检查 Ruff、格式和文件行数。

### 单文件行数

Python、Vue、TypeScript、JavaScript、样式与 HTML 源文件最多 1500 行，含空行和注释；Vue 的 template / script / style 合并计算。检查覆盖 Git 已跟踪与未忽略的新文件，存量超限文件也会失败。

前端 build / test 脚本先执行门禁，后端完整 pytest 包含门禁测试。具体前端命令见[前端指南](../frontend/README.md#适配边界和检查)。

## 后台作业与队列中心

`sdd_ai_jobs` 保存执行状态、进度、版本、取消意图和结果提交记录。技能分析表保留分析报告；API Mock 表保留业务关联；准备作业表保留创建请求与资源关联。它们的执行字段是统一作业的只读投影，不再保存另一份执行结论。

领域执行通过 `jobs/domain_jobs.py` 提交与上报，复用现有认领、租约、心跳、进程监督和回收器。产物和 `completion_json` 在同一事务中提交；执行资源确认结束后，由 convergence 推进终态。恢复读取已经提交的完成证据，避免重做业务副作用。初始化继续使用既有的逐步恢复日志，并关联独立作业；基线资源的有效性与每次构建历史分别保存。

队列查询在数据库中完成授权、筛选、计数和分页。排序为业务更新时间、创建时间、ID 的降序；心跳不改变业务更新时间。每一页读取当前数据库快照，动态变化时刷新列表；静态数据有确定顺序。列表、详情和操作使用同一权限及能力规则。`version` 用于拒绝重复或迟到的快照，进度百分比不参与新旧判断。

`sdd_job_attempts` 保存实际认领的尝试；`sdd_job_events` 保存已提交版本并承担通知重投。通知失败不阻止调度。用户重新执行会创建带 `retry_of_job_id` 的新作业，同一原作业的重复重新执行命令返回同一个后继；原终态与结果保留。自动故障恢复保留原身份并新增尝试。重新执行默认重放已保存的业务输入，执行身份采用当前操作者；WORKTREE 分析读取当前工作副本，基线重新准备当前规格版本，两者在新作业中记录输入政策与版本依据。

### 数据切换

1. 停止接收新作业，排空运行中的旧执行进程；保存数据库及外部资源回执备份。迁移期间不能同时运行旧版与新版写入进程。
2. 在后端目录执行 `python -m alembic upgrade head`，应用 `d91f20a4c6e8`。迁移复用现有身份，回填历史管理信息，删除三类领域表中的重复执行列。无执行证据的旧活动记录进入人工核实，已结束记录不会因此重新执行。
3. 核对旧记录映射、终态数量、产物关联及待核实记录，再启动新版服务。有效的已有执行归属与远端定位信息保留，由现有恢复机制处理；不能凭缺失通知重跑工作。
4. 验证队列分页、领域页面、取消、重新执行和通知恢复。已经提交结果的记录只补做收尾。资源快照变为过期，不修改此前成功的作业。

本次结构迁移采用向前修复；不提供直接降级删除新事实的操作。需要恢复旧版本时，应使用经过验证且版本匹配的完整备份，并先核实迁移后产生的外部副作用。

### 后续执行后端

`jobs/backends.py` 描述执行能力与当前 durable 后端。执行归属、外部任务 ID、计划 ID、应执行时间和幂等命令身份均由平台持久化；认领与回收仅处理所属后端。定时触发身份基于计划及带时区的应执行时点。

Celery 与计划调度尚未实现，也未安装相应依赖。接入时需要实现可靠投递、外部身份绑定、受保护的状态与结果上报、控制确认和故障对账，并明确唯一重试责任方。计划还需约定补跑及重叠策略；暂停计划不取消已接受的执行。派发成功、撤销请求和外部技术状态不能直接替代平台作业结果。

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
