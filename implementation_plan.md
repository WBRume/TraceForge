# SDD Native 平台 — Python + FastAPI 全栈实施计划

构建基于 Python + FastAPI 的"规范驱动开发 (SDD) 基础能力平台"，通过 PTY 桥接 claudecode CLI + superpowers 能力包，以 SDD (红-绿-重构) 闭环自动生成可运行代码。

## 确认参数

| 项 | 值 |
|---|---|
| Python | 3.11+ |
| MySQL | `localhost:3306` / `root` / `root` / `sdd_platform` |
| claudecode CLI | 已安装，superpowers 已集成 |
| PTY 桥接 | Windows: `wexpect` / `winpty` |
| 前端主题 | **亮色**，天蓝 + 白色 |
| 门户页 | 需要大型 Portal 介绍页，登录后跳转工作区 |

---

## 设计系统 (ui-ux-pro-max 生成)

| 页面 | 风格 | 配色 | 字体 |
|------|------|------|------|
| **MASTER** | Glassmorphism + Data-Dense | Primary `#1E40AF` / Secondary `#3B82F6` / CTA `#F59E0B` / Bg `#F8FAFC` | Fira Code + Fira Sans |
| **Portal** | Enterprise Gateway + Social Proof | Primary `#0EA5E9` / CTA `#F97316` / Bg `#F0F9FF` | Outfit + Work Sans |
| **Chat** | Glassmorphism | Backdrop blur 10-20px, Z-depth layers | 继承 MASTER |
| **Dashboard** | Data-Dense Dashboard | Blue data `#1E40AF` + Amber highlights `#F59E0B` | Fira Code + Fira Sans |

完整设计系统文件: [MASTER.md](file:///g:/proj/SDD-native/design-system/sdd-native/MASTER.md) | [portal.md](file:///g:/proj/SDD-native/design-system/sdd-native/pages/portal.md) | [chat.md](file:///g:/proj/SDD-native/design-system/sdd-native/pages/chat.md) | [dashboard.md](file:///g:/proj/SDD-native/design-system/sdd-native/pages/dashboard.md)

---

## 架构总览

```
┌──────────────────────────────────────────────────────────────────────────┐
│                Portal UI (Vue 3 + Vite + Pinia + ECharts)               │
│  ┌────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Portal │ │ Chat UX  │ │ 富文本   │ │ 资产查询 │ │ 效能看板      │  │
│  │ 门户页 │ │ (对话流) │ │ 卡片    │ │          │ │ (ECharts)     │  │
│  └────────┘ └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
│  ┌────────┐ ┌──────────┐ ┌──────────┐                                 │
│  │ 登录   │ │ 工作区   │ │ HITL    │                                 │
│  │ 注册   │ │ 管理     │ │ 交互卡片 │                                 │
│  └────────┘ └──────────┘ └──────────┘                                 │
└────────────────────────────┬───────────────────────────────────────────┘
            WebSocket / REST │
┌────────────────────────────┴───────────────────────────────────────────┐
│               Backend (Python 3.11+ / FastAPI / SQLAlchemy)            │
│  ┌────────────┐ ┌───────────┐ ┌────────────┐ ┌──────────────────┐    │
│  │ REST API   │ │ WebSocket │ │ 工作流引擎 │ │ Claude Bridge    │    │
│  │ (Auth+CRUD)│ │ (双向)    │ │ (状态机)   │ │ (wexpect PTY)    │    │
│  └────────────┘ └───────────┘ └────────────┘ └───────┬──────────┘    │
│  ┌────────────┐ ┌───────────┐ ┌────────────┐         │              │
│  │ JWT/RBAC   │ │ Asset Svc │ │ MCP(预留)  │         │              │
│  └────────────┘ └───────────┘ └────────────┘         │              │
│  ┌──────────────────────────────────────────┐         │              │
│  │      SQLAlchemy + Alembic (ORM+迁移)      │         │              │
│  └──────────────────┬───────────────────────┘         │              │
└──────────────────────┼─────────────────────────────────┼──────────────┘
                       │                                 │
                ┌──────┴──────┐                  ┌───────┴──────────┐
                │ MySQL       │                  │ claudecode CLI + │
                │ sdd_platform│                  │ superpowers      │
                └─────────────┘                  └──────────────────┘
```

---

## Proposed Changes

### 一、后端 (Python + FastAPI)

路径: `g:\proj\SDD-native\backend`

---

#### [NEW] 项目结构

```
backend/
├── requirements.txt
├── alembic.ini + alembic/versions/
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # Pydantic Settings
│   ├── database.py             # SQLAlchemy 引擎
│   ├── dependencies.py         # get_db / get_current_user
│   ├── models/                 # ORM (user/task/log/asset/metric)
│   ├── schemas/                # Pydantic DTO (auth/task/asset/ws)
│   ├── routers/                # 路由 (auth/workspace/task/asset/dashboard)
│   ├── services/               # 业务逻辑
│   ├── engine/                 # 核心引擎
│   │   ├── claude_bridge.py    # wexpect PTY 桥接
│   │   ├── workflow_engine.py  # 三阶段状态机
│   │   ├── state_protocol.py   # [AGENT_STATE_SYNC] 解析
│   │   └── hitl_manager.py     # HITL 挂起/恢复
│   ├── ws/                     # WebSocket 管理
│   └── middleware/             # 日志 + RBAC 中间件
```

核心依赖: `fastapi` `uvicorn[standard]` `sqlalchemy` `alembic` `pymysql` `python-jose[cryptography]` `passlib[bcrypt]` `pydantic-settings` `python-multipart` `wexpect` `loguru` `websockets`

---

#### [NEW] 数据库 Schema (10 张表, 均含 workspace_id + creator_id)

| 表 | 用途 |
|---|---|
| `users` | 用户账号 |
| `workspaces` | 工作区 |
| `workspace_members` | 成员关系 + 角色 (OWNER/DEVELOPER/VIEWER) |
| `sdd_tasks` | 任务 (含 project_path / git_repo_url / status / retry_count) |
| `sdd_plan_nodes` | Plan 树节点 |
| `sdd_execution_logs` | CLI 执行日志 (phase / log_type / content) |
| `sdd_test_results` | 测试结果 (UT/E2E/API) |
| `sdd_assets` | 过程资产 (SPEC/PROMPT/PLAN/DIFF/REPORT) |
| `sdd_dashboard_metrics` | 看板指标 |
| `chat_messages` | 对话消息 (role / message_type / metadata_json) |

---

#### [NEW] API 设计

| 分组 | 端点 |
|------|------|
| Auth | `POST /auth/register` · `/auth/login` · `/auth/refresh` |
| Workspace | `CRUD /workspaces` · `POST /workspaces/{id}/members` |
| Task | `CRUD /tasks` · `POST /tasks/{id}/start\|cancel` |
| Chat | `GET /tasks/{id}/messages` · WebSocket `/ws/task/{id}` |
| Asset | `GET /assets` (多维检索) |
| Dashboard | `GET /dashboard/overview\|success-rate\|phase-duration\|retry-heatmap` |

---

#### [NEW] Claude CLI 桥接

- 接口抽象 `CliBridgeBase` + Mock/Real 实现
- Windows: `wexpect.spawn()` 启动 claudecode 进程
- 异步读取 PTY 输出 → 解析 `[AGENT_STATE_SYNC]` 状态标签
- 检测交互式提示符 → HITL 挂起 → WebSocket 推送前端
- 自纠正闭环: 失败 → 重试 (≤3 次) → 熔断 → 人工接管

---

### 二、前端 (Vue 3 + Vite + Pinia)

路径: `g:\proj\SDD-native\frontend`

---

#### [NEW] 路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` | `PortalView` | **门户介绍页** (Hero + 功能 + 登录入口) |
| `/login` | `LoginView` | 登录/注册 |
| `/workspaces` | `WorkspaceView` | 工作区管理 |
| `/ws/:wsId/chat` | `ChatView` | 主对话界面 |
| `/ws/:wsId/chat/:taskId` | `ChatView` | 任务对话 |
| `/ws/:wsId/assets` | `AssetQueryView` | 资产查询 |
| `/ws/:wsId/dashboard` | `DashboardView` | 效能看板 |

---

#### [NEW] 核心页面设计

**Portal 门户页**: Enterprise Gateway 模式  
- Hero 区: 大标题 + 副标题 + 产品截图 + CTA (开始使用 / 登录)
- 功能特性: Bento Grid 卡片展示核心能力
- 社会证明: 客户 Logo / 统计数字
- Footer: 链接 + 版权

**Chat 对话页**: 类 ChatGPT 体验
- 左侧: 对话历史侧边栏
- 中央: 气泡对话流 (仅自然语言，CLI 输出折叠在"思考"面板)
- 右侧/顶部: **富文本卡片** (Plan 树 / 进度 / 报告) — 独立置顶不随气泡滚动
- HITL 卡片: 确认/取消按钮、下拉选择

**Dashboard 看板页**: Data-Dense Dashboard
- KPI 统计卡片 + ECharts 图表 (饼/柱/热力图)

---

## Verification Plan

### Automated
```bash
# 后端
pip install -r requirements.txt
uvicorn app.main:app --reload      # → http://localhost:8000/docs
python -m pytest tests/ -v

# 前端
npm install && npm run build       # 构建验证
npm run dev                        # → http://localhost:5173
```

### Manual
1. Portal: 门户页展示 → 点击"开始使用" → 跳转登录
2. Auth: 注册 → 登录 → Token 缓存
3. Workspace: 创建工作区 → 跳转 Chat 页
4. Chat UX: 发送消息 → 气泡渲染 → 富文本卡片置顶
5. Dashboard: 统计卡片 + 图表渲染 (Mock 数据)
6. API: Swagger UI `/docs` 验证所有端点

> [!NOTE]
> CLI 桥接和 MCP 调度内置 Mock 模式。配置 `SDD_CLI_MODE=real` 切换真实桥接。
