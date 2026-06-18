# TraceForge

<p align="center">
  <strong>开发态资产管理 + AI 开发过程可追溯协作平台(Demo)</strong>
</p>

<p align="center">
  将开发过程中产生的需求、规范、决策、证据等结构化管理为可追溯资产；AI 与开发者全程协同，过程可观测、决策可审查、经验可沉淀。
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-blue">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115-green">
  <img alt="Vue" src="https://img.shields.io/badge/Vue-3.x-brightgreen">
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-5.x-blue">
  <img alt="MySQL" src="https://img.shields.io/badge/MySQL-5.7%2B%20%7C%208.0%2B-orange">
  <img alt="Status" src="https://img.shields.io/badge/status-internal%20preview-yellow">
</p>

---

## 项目简介

### 平台定位

**TraceForge** 是一个面向 **开发态资产管理 + AI 开发过程可追溯协作** 的平台。它将开发过程中产生的需求、规范、决策、证据等结构化管理为可追溯资产，同时让 AI 与开发者全程协同——过程可观测、决策可审查、经验可沉淀。

平台后端基于 **FastAPI** 构建，提供 RESTful API、WebSocket 实时通信、任务调度、Claude CLI Bridge、Skills 管理、API Mock、文档资产管理、全链路追溯、人机差异分析、知识库等能力。前端基于 **Vue 3 + TypeScript** 构建，结合 Element Plus、Pinia、Vue Router、Monaco Editor 等工具，提供面向研发团队的交互式工作台。

与传统”把需求丢给 AI 等待结果”的方式不同，本项目更强调：

- **资产化管理**：需求、规范、任务决策、人机差异、运行证据等开发过程产物结构化沉淀为可复用资产。
- **全链路追溯**：覆盖度矩阵贯穿 Requirement → Task → Spec → Plan → AI Run → Review → Delta → Evidence，每次修改可溯源。
- **人机协同**：AI 与开发者全程协同推进，HITL 关键决策点人工介入，人机差异分析归因每次修改。
- **过程可审计**：任务收尾时自动生成证据链与过程审计，Token 归因与成本全程可观测。
- **知识沉淀**：从真实 Task 过程中晋升长期知识资产，团队经验可积累、可检索、可复用。

> **一句话总结**：  
> TraceForge 试图把”需求资产 → AI 协作执行 → 人机差异归因 → 全链路追溯 → 知识沉淀”做成一个可管理、可观察、可审计、可复用的工程化闭环。

---

### 核心价值

| 价值 | 说明 |
|---|---|
| **让开发过程产物成为可追溯资产** | 需求、规范、任务决策、人机差异、运行证据等结构化管理，支持需求层级拆分和全链路追溯矩阵。 |
| **让 AI 执行过程可观察** | 通过任务状态、WebSocket 事件、执行日志、Token 归因和 AI Job 记录追踪执行过程。 |
| **让人工介入成为流程的一部分** | HITL 支持 AI 在关键节点暂停，等待用户确认、补充信息或决策；人机差异分析归因每次修改。 |
| **让团队能力可复用** | Skills 支持目录化包、版本管理、评审、Diff、Git/GitHub 集成和任务级临时编辑。 |
| **让接口联调更早发生** | API Mock 能力支持 OpenAPI 导入、端点管理、Mock Case、AI 自动生成和预览调试。 |
| **让知识从实践中沉淀** | 知识库从真实 Task 过程中晋升长期资产，支持业务概念分类、决策沉淀和候选晋升。 |

---

### 解决的问题

| 常见痛点 | 平台思路 |
|---|---|
| 需求文档写完后和实际开发过程脱节 | 通过 Task Spec / Asset 将规范文档纳入任务执行上下文，支持需求层级拆分 |
| AI 辅助开发缺少统一入口 | 以任务为中心组织 Claude CLI 会话、Skills、日志和执行状态 |
| Prompt / Skills 难以沉淀和复用 | 通过 Skills 管理、版本控制、任务级编辑和评审机制沉淀团队经验 |
| AI 执行过程不可控 | 通过 Workflow Engine、HITL、WebSocket 和日志提供可观察、可中断能力 |
| AI 输出与人工修改差异不可见 | 人机差异分析（Human Delta）归因 AI 输出与人工最终修改之间的差异 |
| 前后端接口依赖阻塞开发 | 通过 API Mock 项目、端点、Mock Case、AI 自动生成和预览能力支持并行联调 |
| 评审、讨论、文档、执行记录分散 | 通过文档资产、评论讨论、证据链和任务历史统一沉淀协作过程 |
| 开发经验无法跨任务复用 | 知识库从真实 Task 过程晋升长期资产，支持决策沉淀和知识检索 |

---

### 平台能力概览

| 能力域 | 说明 |
|---|---|
| **开发态资产管理** | 需求资产库、任务资产表、证据注册表，结构化管理开发过程产物 |
| **全链路追溯** | 覆盖度矩阵贯穿 Requirement → Task → Spec → Plan → AI Run → Review → Delta → Evidence |
| **人机差异分析** | Human Delta 归因 AI 输出与人工最终修改之间的差异，支持差异看板和风险聚合 |
| **AI 协作执行** | 通过 Claude CLI / AI 会话辅助执行任务，Token 归因与成本全程可观测 |
| **HITL 人机协同** | 关键决策点人工介入，需求双向澄清（Clarification），确保高风险操作安全 |
| **工作流引擎** | 负责任务阶段推进、状态变更、HITL 暂停与恢复 |
| **Skills 管理** | 管理目录化技能包，支持版本、Diff、评审、发布和任务级临时编辑 |
| **API Mock** | 支持 OpenAPI 导入、端点管理、实体管理、Mock Case、AI 自动生成和预览调试 |
| **知识库** | 从真实 Task 过程晋升长期知识资产，支持业务概念分类和决策沉淀 |
| **实时协作** | 基于 WebSocket 推送任务、API Mock、文档讨论等协作事件 |
| **过程审计** | 任务收尾时自动生成证据链与过程审计，决策可审查、经验可沉淀 |
| **权限控制** | 基于 JWT 与工作区成员权限控制用户访问范围 |

---

### 核心模块详解

#### 1. 工作区管理（Workspace）

工作区是平台中的资源隔离单元，用于承载团队成员、任务、项目路径、权限和相关资产。

主要能力：

- 多工作区隔离
- 成员访问控制
- 工作区级权限判断
- 项目路径配置
- 与任务、文档资产、Skills、API Mock 项目、需求资产关联

适合场景：

- 按项目组织 AI 辅助开发任务
- 按团队隔离不同业务线资源
- 为内部测试团队提供独立实验空间

---

#### 2. 任务管理（Task）

任务是一次 AI 辅助开发过程的核心载体。它将需求描述、规范文档、项目路径、Skills、AI 会话和执行日志串联起来。

主要能力：

- 创建任务
- 初始化任务
- 启动任务
- 取消任务
- 完成任务
- 查看任务历史
- 上传任务规范
- 清理任务历史
- 导出任务会话
- 查看任务关联的 AI Jobs

---

#### 3. 需求资产管理（Requirement）

需求资产是平台的核心管理对象之一，将需求从文档级别提升为可追溯、可拆分、可关联的结构化资产。

主要能力：

- 需求创建与编辑
- 需求层级拆分
- 需求与 Task 关联
- 需求双向澄清（Clarification）
- 覆盖度矩阵（Coverage Matrix）
- 人工差异标记

价值：

- 让需求不再是静态文档，而是贯穿开发全过程的活跃资产
- 支持需求到实现的全链路追溯
- 通过澄清机制确保需求理解一致

---

#### 4. 规范文档与文档资产

平台将规范文档视为 AI 执行的关键上下文，而不是单纯的附件。

主要能力：

- 上传任务规格文档
- 文档资产管理
- 文档版本记录
- 评论与讨论
- 文档评审
- 资产历史追踪
- 与任务执行过程关联

价值：

- 让 AI 执行基于明确需求
- 让评审意见保留在文档上下文中
- 让需求、实现和讨论形成可复盘链路

---

#### 5. Claude CLI / AI 会话执行

平台通过 Claude CLI Bridge 连接 AI 执行能力，由 Workflow Engine 统一调度任务执行过程。

主要能力：

- Claude CLI 调用
- AI Job 管理
- 会话恢复
- 任务状态推送
- 执行日志记录
- CLI 事件解析
- 工具调用状态追踪
- Token 归因与成本统计

---

#### 6. HITL 人机协作机制

HITL（Human-In-The-Loop）用于让 AI 在关键节点暂停，等待人工补充信息或确认决策。

主要能力：

- AI 执行过程中触发人工确认
- 任务状态进入挂起态
- 用户确认后恢复执行
- 关键问题和回答进入任务历史
- 需求双向澄清（Clarification）
- 支持更安全的 AI 执行闭环

适合场景：

- 需求不明确时要求人工确认
- 设计方案需要用户选择
- 风险操作前需要确认
- AI 无法判断上下文时请求补充信息
- 需求理解存在歧义时双向澄清

---

#### 7. Skills 体系

Skills 是平台中用于沉淀团队经验和 AI 执行上下文的核心模块。它不只是简单 Prompt，而是可以被版本化、评审、Diff 和任务级使用的技能包。

主要能力：

- Skills 创建与编辑
- 目录化 Skill Package
- 版本管理
- Git 工作树集成
- GitHub 导入
- 发布状态管理
- 版本 Diff
- 行级评审
- 专家评分
- 任务执行态 Skills 查看
- 初始化时调整任务 Skills
- Runtime Skill 临时编辑

---

#### 8. API Mock

API Mock 模块用于帮助团队在接口尚未完全实现时提前开展前端开发、测试和联调。

主要能力：

- API Mock 项目管理
- OpenAPI / Swagger 文档导入
- Endpoint 管理
- Entity 管理
- Mock Case 管理
- 请求匹配
- Mock 预览
- Gateway / Proxy 调试
- API Mock 协作事件
- 自动生成 Mock Case 的扩展能力

典型场景：

- 后端接口未完成，前端先行开发
- 测试人员构造稳定 Mock 数据
- 根据 OpenAPI 文档快速生成接口管理视图
- 对不同响应场景维护多个 Mock Case

---

#### 9. 人机差异分析（Human Delta）

人机差异分析模块用于归因 AI 输出与人工最终修改之间的差异，是质量保障和过程审计的核心能力。

主要能力：

- Human Delta 生成与管理
- AI 输出（ChangeProposal）与人工最终修改（Final Patch）对比
- 差异归因与分类
- 差异看板与风险聚合
- 与证据链和知识库关联
- 从差异中晋升知识资产

价值：

- 让 AI 与人工协作的质量可量化
- 让每次修改的来源可追溯
- 为团队优化 AI 使用策略提供数据支撑

---

#### 10. 全链路追溯（Traceability）

全链路追溯是平台的核心能力之一，贯穿从需求到证据的完整链路，让开发过程的每个环节都可溯源。

主要能力：

- 覆盖度矩阵（Coverage Matrix）
- 贯穿 Requirement → Task → Spec → Plan → AI Run → Review → Delta → Evidence
- 证据注册表（Evidence Registry）
- 风险聚合与状态派生
- 过程审计报告


---

#### 11. 知识库（Knowledge Base）

知识库不是普通文档库，而是从真实 Task 过程中晋升的长期资产，承载团队的决策经验和业务知识。

主要能力：

- 知识资产晋升（从 Decision、Human Delta、Clarification、Review Comment）
- 业务概念分类
- 知识候选管理
- 与需求、任务关联
- 知识检索与复用

价值：

- 让开发经验不再随任务结束而流失
- 让团队决策过程可追溯、可复用
- 为新任务提供上下文参考

---

#### 12. 实时协作与 WebSocket

平台通过 WebSocket 支持任务执行、API Mock、文档讨论等场景的实时状态同步。

主要能力：

- 任务执行事件推送
- AI 输出实时展示
- 工具调用状态展示
- API Mock 协作事件
- 文档讨论实时同步
- 在线状态与协作事件广播

价值：

- 多人同时观察任务进展
- 及时发现 AI 执行异常
- 让评论、讨论、状态变化不依赖手动刷新

---

#### 13. 仪表板与运行观测

平台保留任务执行过程中的成本、耗时、状态和结果信息，用于后续统计与复盘。

主要能力：

- 任务耗时统计
- 成本统计
- 任务结果记录
- 执行日志
- AI 会话日志
- API Mock 执行记录
- Dashboard 指标沉淀

---

#### 14. 认证、权限与运行保障

平台面向内部团队协作，提供基础认证、权限和运行保障能力。

主要能力：

- JWT 认证
- 工作区成员权限
- 资源隔离
- 日志记录
- 可选 Redis 分布式锁
- 单 worker 内部测试部署建议
- 路径与本地文件存储隔离

---

### 能力边界说明

> 当前项目面向**内部小团队测试**和能力孵化，重点关注开发态资产管理、AI 协作过程可追溯、人机差异分析、知识沉淀、Skills 复用、API Mock 支撑和文档评审协作。
>
> 对于生产化部署、多实例运行、跨 worker WebSocket pub/sub、完整任务队列化等能力，建议根据实际代码进展和部署策略逐步启用。内部测试阶段建议优先采用单 worker 部署，以保证 CLI 会话状态和运行态一致性。

## 环境要求

- **Python**: 建议 Python 3.10+
- **Node.js**: 建议 Node.js 18+
- **MySQL**: 5.7+ 或 8.0+
- **Git**: 用于 Skills 的 Git 集成
- **Claude CLI**: 需要预先安装并配置到系统 PATH
- **Redis**: 可选，仅在使用分布式锁功能时需要

## 后端启动

```bash
# 1. 进入后端目录
cd backend

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
# Windows PowerShell 可使用：Copy-Item .env.example .env
cp .env.example .env
# 关键配置项见下方"环境变量配置"章节

# 4. 确保 MySQL 数据库已创建
# CREATE DATABASE sdd_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

# 5. 运行数据库迁移
alembic upgrade head

# 6. 启动 FastAPI 服务
uvicorn app.main:app --reload
```

后端默认运行在 `http://localhost:8000`，可通过 `http://localhost:8000/docs` 访问 API 文档。

## 前端启动

```bash
# 1. 进入前端目录
cd frontend

# 2. 安装依赖
npm install

# 3. 启动开发服务器
npm run dev:electron
```

前端默认运行在 `http://localhost:5173`。

## 环境变量配置

后端配置固定从 `backend/.env` 读取。首次启动时，在 `backend/` 目录下复制 `backend/.env.example` 为 `.env`，再按本机数据库、路径和密钥调整：

| 变量名 | 说明 | 默认值 / 示例 |
|---|---|---|
| APP_NAME | 应用名称 | TraceForge |
| APP_VERSION | 应用版本 | 1.0.0 |
| DEBUG | 调试模式 | true |
| DB_HOST | 数据库主机 | localhost |
| DB_PORT | 数据库端口 | 3306 |
| DB_USER | 数据库用户名 | root |
| DB_PASSWORD | 数据库密码 | change-me（本地按需填写） |
| DB_NAME | 数据库名称 | sdd_platform |
| JWT_SECRET_KEY | JWT 密钥 | **生产环境必须修改** |
| JWT_ALGORITHM | JWT 算法 | HS256 |
| CLAUDE_CLI_PATH | Claude CLI 路径 | claude |
| PLATFORM_API_BASE_URL | 平台 API 地址 | http://localhost:8000 |
| SKILLS_STORAGE_ROOT | Skills 存储根目录 | storage/skills |
| API_MOCK_TEMP_ROOT | API Mock 临时目录 | tmp/api_mock_workspace |
| CLI_STATE_ROOT | CLI 状态目录 | tmp/cli_state |
| LOG_LEVEL | 日志级别 | INFO |
| LOG_DIR | 日志目录 | ./logs |
| REDIS_ENABLED | 是否启用 Redis | false（可选） |
| REDIS_URL | Redis 连接地址 | redis://127.0.0.1:6379/0 |
| DISTRIBUTED_LOCK_BACKEND | 分布式锁后端 | local |

> **注意**：
> - 生产或测试环境必须修改 `JWT_SECRET_KEY`
> - 相对路径会以 `backend/` 目录为基准解析；也可以按实际环境改为绝对路径
> - 数据库账号密码不要提交到仓库
> - Claude CLI 路径需要确保可执行

## 数据库迁移

### 运行迁移

```bash
cd backend
alembic upgrade head
```

### 创建新迁移

```bash
cd backend
alembic revision --autogenerate -m "migration message"
```

> **前提**：确保 MySQL 数据库已创建（`CREATE DATABASE sdd_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`）

## 常用开发命令

### 前端

```bash
cd frontend
npm run dev          # 启动开发服务器
npm run build        # 构建生产版本
npm run preview      # 预览生产构建
npm run test         # 运行测试（Vitest）
npm run test:run     # 单次运行测试
```

### 后端

```bash
cd backend
uvicorn app.main:app --reload     # 启动开发服务器
alembic upgrade head              # 运行数据库迁移
alembic revision --autogenerate -m "message"  # 创建迁移
```

## 部署说明

> **重要提示**：当前项目处于开发阶段，部署时请注意以下事项：

1. **单 worker 部署**：项目当前依赖进程内运行态和 CLI 会话状态，建议初期采用单 worker 部署。避免在未完成运行态锁、任务队列、WebSocket pub/sub 改造前贸然多 worker 部署。

2. **路径配置**：所有存储路径（`SKILLS_STORAGE_ROOT`、`API_MOCK_TEMP_ROOT`、`CLI_STATE_ROOT` 等）必须使用绝对路径，并确保运行用户有读写权限。

3. **Claude CLI 确认**：部署前确认 Claude CLI 可正常执行，且 `CLAUDE_CLI_PATH` 配置正确。

4. **数据库连接**：确保 MySQL 可正常连接，Alembic 迁移已执行完毕。

5. **Redis 分布式锁**：如需启用分布式锁功能，需要部署 Redis 并配置 `REDIS_ENABLED=true`。

## 日志与排错

### 日志目录

- **应用日志**：`backend/logs/sdd_app.log`
- **AI 会话日志**：`backend/logs/ai_sessions/`

### 常见问题排查

**后端启动失败**
- 检查 Python 版本是否符合要求
- 检查依赖是否安装完整
- 检查 `.env` 配置文件是否存在且格式正确
- 检查 MySQL 服务是否正常运行

**数据库连接失败**
- 确认 MySQL 服务已启动
- 验证 `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD` 配置正确
- 确认数据库已创建

**Claude CLI 不可用**
- 确认 Claude CLI 已安装并添加到系统 PATH
- 验证 `CLAUDE_CLI_PATH` 配置正确
- 在终端执行 `claude` 命令测试是否正常

**前端接口地址不正确**
- 检查后端服务是否运行在正确端口
- 检查前端 `VITE_API_BASE_URL` 环境变量配置

**CORS 问题**
- 确认 `CORS_ORIGINS` 配置包含前端地址
- 检查浏览器控制台具体错误信息

## 内部协作流程

1. **测试**：提交前运行相关测试
   ```bash
   # 前端测试
   cd frontend && npm run test:run
   
   # 后端测试（待补充测试命令）
   ```

2. **不提交以下内容**：
   - `.env` 文件
   - 日志文件（`logs/` 目录）
   - 本地临时文件
   - 敏感信息和密钥

> **注意：本项目开发尚未完成，当前仅为 Demo / 概念验证项目，不保证功能完整性与稳定性，请勿用于生产环境。**

## License

本项目基于 [MIT License](./LICENSE) 开源。
