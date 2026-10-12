<h1 align="center">TraceForge</h1>

<p align="center">
  <strong>用 AI 开发功能、排查故障，并在同一个任务里协作、审查和接手代码。</strong>
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&amp;logoColor=white">
  <img alt="FastAPI 0.115.6" src="https://img.shields.io/badge/FastAPI-0.115.6-009688?logo=fastapi&amp;logoColor=white">
  <img alt="Vue 3.5" src="https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vuedotjs&amp;logoColor=white">
  <img alt="TypeScript 5.9" src="https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&amp;logoColor=white">
  <img alt="Node.js 22.12+" src="https://img.shields.io/badge/Node.js-22.12%2B-5FA04E?logo=nodedotjs&amp;logoColor=white">
  <img alt="MySQL 8.0" src="https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&amp;logoColor=white">
</p>

<p align="center">
  <img alt="Status: internal preview" src="https://img.shields.io/badge/status-internal%20preview-yellow">
  <a href="LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/License-Apache%202.0-blue"></a>
</p>

<p align="center">
  <a href="#用它做什么">功能介绍</a> ·
  <a href="#开始使用">开始使用</a> ·
  <a href="#文档导航">文档导航</a> ·
  <a href="#当前边界">当前边界</a>
</p>

---

## 项目简介

TraceForge 把需求、代码仓库、Agent 会话、文档和执行记录放到一起。你可以让 Agent 在服务器或本机执行任务，随时补充信息、确认方案、查看代码变化，并把排查结果保存为下次可用的案例和诊断规程。

支持 Web、Electron、Tauri；可接入 Claude Code、OpenCode、DSH。

> **项目状态**：当前为开发中的内部预览项目，适合小团队试用与功能验证，尚不保证生产环境的完整性和稳定性。
>
> **Agentic 实现说明**：当前很多功能直接调用 Claude Code、OpenCode、DSH 等底层编码 Agent，主要通过提示词和流程串联验证业务流程，尚未按完整的 Agent 架构建设。面向真实业务场景，应按业务职责设计独立的专用 Agent，分别管理上下文、工具权限、执行状态与结果验证，按需调用底层编码 Agent 的执行能力。当前实现不代表生产级 Agent 架构或最佳实践。

## 用它做什么

### 开发一个功能

1. **准备任务**：创建工作区，关联一个或多个仓库，填写需求；按需附上规格文档、选择 Skills、Agent 和模型。
2. **边执行边协作**：查看回复、工具调用和代码变化；Agent 需要选择或补充信息时，在会话中回答。同事可参与讨论，也可通过分享链接查看或提交建议。
3. **审查并收尾**：查看计划文档、代码差异和人工修改记录，确认交付结果，并将任务结果回写到关联需求。

需要用自己的编辑器改代码时，可在桌面端开启**本地协同**：Agent 在服务器执行，你继续编辑本机仓库；按需交接本地修改、接收云端结果，冲突文件先备份再确认处理。[使用条件与操作](frontend/README.md#本地协同)

### 排查一个问题

1. **描述现象**：新建问题定位任务，提供日志、堆栈或异常现象；有历史经验时，可选择推荐的诊断规程。
2. **逐步排查**：Agent 分析证据、提出假说和验证办法。绑定规程后可逐阶段确认，也可开启自动推进；证据不足或执行失败时暂停。
3. **保留经验**：把现象、证据、根因和解决办法整理为案例，再从案例提炼诊断规程。提炼任务在后台运行，生成草案后由人确认，供后续任务复用。

普通日志分析无需搭建实验环境；要做真实复现与回归验证，再配置专用环境。[诊断规程说明](backend/app/domains/diagnosis_playbook/README.md)

## 任务之外的常用能力

| 你要做的事 | 对应功能 |
| --- | --- |
| 管理多个仓库的开发任务 | 工作区关联多仓库；任务详情可查看各仓库的来源分支和创建时提交 |
| 复用团队的执行方法 | Skills 导入、编辑、版本比较、评审，以及任务内临时调整 |
| 让前后端提前联调 | 导入 OpenAPI，维护接口和 Mock 场景，用 AI 生成数据并预览响应 |
| 找回以前的排查过程 | 搜索任务、消息、案例和规程；支持 SQLite 关键词检索，可选 ES + 向量检索 |
| 查看本次任务产出的文档 | 按工作区配置计划文档目录，显示相对任务初始快照新增或修改的 Markdown |
| 和同事一起跟进 | 工作区成员权限、文档评审讨论、会话分享、站内通知、桌面提醒和 Webhook |
| 用语音补充任务信息 | 语音转文字写入输入框；支持配置在线供应商，桌面构建可选离线识别 |
| 管理服务连接与功能开关 | 管理员在系统配置中设置 Agent、搜索、语音等能力，并检查连接状态 |

## 开始使用

### 本机开发

准备 **Python 3.10+、Node.js 22.12+、MySQL 8.0、Redis 和 Git**。执行 AI 任务还需要配置至少一个真实 Agent。

1. 按[后端启动指南](backend/README.md#首次启动)创建虚拟环境、配置数据库与 Redis、执行迁移并启动 API。
2. 在新的终端启动前端：

   ```powershell
   cd frontend
   npm ci
   npm run dev
   ```

3. 打开 [本地页面](http://localhost:5173)，注册并登录。首个注册账号为管理员；配置 Agent 连接后，创建工作区和第一个任务。

使用本机资源或本地协同时，将 `npm run dev` 换为 `npm run dev:electron`。Tauri 开发、客户端打包和语音配置见[前端与桌面指南](frontend/README.md)。

### Docker 部署

按 [Docker 部署指南](deploy/docker/README.md)配置并启动 MySQL、Redis、API 和 Web。默认访问 [本地 Web 服务](http://localhost:8080)；Agent 登录或远端连接需单独配置。

## 文档导航

| 文档 | 什么时候看 |
| --- | --- |
| [后端启动与开发](backend/README.md) | 首次安装、Agent 配置、开发检查和排错 |
| [前端与桌面客户端](frontend/README.md) | Web / Electron / Tauri 开发、打包、本地协同和语音输入 |
| [Docker 部署](deploy/docker/README.md) | 启动整套服务、配置容器连接和持久化目录 |
| [历史搜索部署](deploy/search/README.md) | 选择 SQLite 或 Elasticsearch，配置向量检索、回填和恢复 |
| [诊断规程](backend/app/domains/diagnosis_playbook/README.md) | 案例复用、分阶段排查、真实实验和执行边界 |
| [DSH 诊断守卫插件](integrations/dsh-playbook/README.md) | 为专用诊断 Host 配置工具执行限制 |
| [OpenCode 真实恢复验收](backend/tests/live_opencode/README.md) | 验证断流、进程重启和后端恢复；会调用真实服务 |
| [数据库迁移](backend/alembic/README.md) | 更新数据库结构或新增 Alembic 迁移 |

## 当前边界

- **本机资源需要桌面端**：浏览器可创建和使用服务器资源任务。本机 Agent 资源还需启用内网访问配置，见[后端说明](backend/README.md#本机-agent-资源)。
- **本地协同有适用范围**：仅支持服务器执行的研发任务，问题定位任务不支持；首次绑定需核对每个仓库的初始提交和本地改动。
- **部分资产页面仍在建设**：资产中心的“追溯”和“知识库”分区是占位页面，不代表完整能力已交付；案例中心与诊断规程有独立入口。
- **部署按单 API 进程运行**：当前仍有进程内会话状态，不应直接增加 API worker 或容器副本。

技术栈：FastAPI / SQLAlchemy / Alembic、Vue 3 / TypeScript / Pinia、MySQL / Redis。

许可证：[Apache License 2.0](LICENSE)。
