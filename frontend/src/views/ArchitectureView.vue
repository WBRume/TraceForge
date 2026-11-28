<script setup lang="ts">
import { useRouter } from 'vue-router'
import { 
  ChevronLeft, Monitor, Server, Database, 
  Terminal, Workflow, Cpu,
  Layers, Lock,
  Settings, ServerCog, Code,
  GitBranch, Verified, LibraryBig, Eye, Shield, Zap, Plug,
  Laptop, LayoutDashboard, Search, FileText, Share2, Bell
} from '@/components/icons'

const router = useRouter()
</script>

<template>
  <div class="arch-container">
    <!-- Header -->
    <header class="arch-header">
      <div class="back-btn" @click="router.push('/')">
        <ChevronLeft class="w-5 h-5" />
        <span>返回首页</span>
      </div>
      <h1 class="title">TraceForge 全景系统架构拓扑</h1>
      <div class="subtitle">开发态资产管理 · 多引擎可追溯协作 · 双桌面便携协同与可视洞察全栈架构</div>
    </header>

    <!-- Diagram Canvas -->
    <main class="diagram-canvas">
      
      <!-- Layer 1: Presentation & Workbench Layer -->
      <div class="layer-section layer-presentation">
        <div class="layer-header">
          <div class="layer-badge badge-presentation">LAYER 1</div>
          <Monitor class="w-4 h-4 text-sky-600" />
          <span>多端交互与业务工作台层 (WEB · ELECTRON · TAURI 2 / VUE 3 + PINIA)</span>
        </div>
        <div class="workbench-grid">
          <div class="node-card card-workbench">
            <div class="card-title"><Terminal class="w-4 h-4 text-sky-600" /> 任务协同与会话工作台 (Task Chat)</div>
            <div class="card-desc">多引擎流式交互 · 图片与消息/Diff 批注 · 在线/离线语音 · 思考胶囊与计划快照 · Token 归因</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><Layers class="w-4 h-4 text-emerald-600" /> 资产白板与原文审阅 (Assets & Canvas)</div>
            <div class="card-desc">列表/无限白板模式切换 · 业务关系图谱 · DOCX/MD 原文精确选区与联合修订 · 跨工作区成员负载</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><ServerCog class="w-4 h-4 text-indigo-600" /> 契约隔离工作台 (API Mock)</div>
            <div class="card-desc">OpenAPI 导入 · 实体推导 · AI 多场景 Mock Case 生成 · 动态代理网关 · 混沌异常联调</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><GitBranch class="w-4 h-4 text-purple-600" /> 差异归因与产物交付 (Delta & Export)</div>
            <div class="card-desc">ChangeProposal 与本地交接四维归因 · 产物分类筛选 · PDF/Office/HTML 在线预览 · 流式 ZIP 导出</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><LibraryBig class="w-4 h-4 text-amber-600" /> 知识中心与排障案例库 (Knowledge)</div>
            <div class="card-desc">业务/框架/运维知识资产 · 真实故障诊断报告 · 后台规程晋升评审 · 标准化排障剧本 (Playbook)</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><LayoutDashboard class="w-4 h-4 text-cyan-600" /> 2.5D 代码沙盘与任务剧场 (Diorama)</div>
            <div class="card-desc">2.5D 等距与俯视多仓沙盘 · 提交时间轴回放 · 成员协作锚点 · 无仓工作区 3D 近期任务剧场轮播</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><Laptop class="w-4 h-4 text-blue-600" /> 桌面端漫游、浮窗与独立绘图板</div>
            <div class="card-desc">多标签页与多窗口拆合记忆 · 置顶会话外置浮窗 · 全局热键 (Ctrl+Alt+D) 绘图板与手绘草图识别</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><Code class="w-4 h-4 text-teal-600" /> 桌面本地协同控制台 (Local Collab)</div>
            <div class="card-desc">本地仓库映射与文件事件刷新 · 轮次备份 · 远端基线三方合并与 Agent 适配 · VS Code / IDEA 直达</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><Settings class="w-4 h-4 text-slate-600" /> 配置、运维中心与全局检索 (Centers)</div>
            <div class="card-desc">配置中心 (/config) · 运维中心 (/ops) 队列监控 · 用户/工作区设置拆分 · 双击 Shift 全局混合搜索</div>
          </div>
        </div>
      </div>

      <!-- Connector 1 -->
      <div class="connection-pipe">
        <div class="pipe-label">HTTP RESTful · RoomEnvelope v2 WebSocket · 跨端 JSON Schema + Ajv 校验 · 桌面原生 IPC 桥</div>
      </div>

      <!-- Layer 2: Gateway & Protocol Layer -->
      <div class="layer-section layer-gateway">
        <div class="layer-header">
          <div class="layer-badge badge-gateway">LAYER 2</div>
          <Zap class="w-4 h-4 text-blue-600" />
          <span>接入网关、安全鉴权与跨端协议层 (GATEWAY, SECURITY & CONTRACTS)</span>
        </div>
        <div class="node-grid-3">
          <div class="node-card card-gateway">
            <div class="card-title"><ServerCog class="w-4 h-4 text-blue-600" /> 动态虚拟代理网关</div>
            <div class="card-desc">单接口 MOCK 仿真与 PROXY 真实后端切流 · 异常混沌注入与响应预览</div>
          </div>
          <div class="node-card card-gateway">
            <div class="card-title"><Plug class="w-4 h-4 text-sky-600" /> RoomEnvelope v2 协同总线</div>
            <div class="card-desc">按代次与单调序号投递会话、白板在线状态与任务事件 · 断线重同步屏障</div>
          </div>
          <div class="node-card card-gateway">
            <div class="card-title"><FileText class="w-4 h-4 text-cyan-600" /> 跨端强类型契约与 MCP 2026</div>
            <div class="card-desc">前后端共享契约与 Ajv 校验 · MCP 2026-07-28 协议 · 桌面资源命令/回执 v2</div>
          </div>
          <div class="node-card card-gateway">
            <div class="card-title"><Lock class="w-4 h-4 text-indigo-600" /> 鉴权隔离与外部分享入口</div>
            <div class="card-desc">OAuth2 (GitHub/GitLab) · JWT · 工作区 RBAC · 链接邀请 (/join) 与免登录分享 (/share)</div>
          </div>
          <div class="node-card card-gateway">
            <div class="card-title"><Laptop class="w-4 h-4 text-violet-600" /> 桌面内置资源与纯 IPC 通道</div>
            <div class="card-desc">Electron / Tauri 2 共用原生协议 · 内置 Node 本地资源服务 · 零端口占用纯 IPC 执行</div>
          </div>
          <div class="node-card card-gateway">
            <div class="card-title"><Bell class="w-4 h-4 text-emerald-600" /> 站内通知与双通道 Webhook</div>
            <div class="card-desc">个人/工作区订阅与任务创建者通知 · 服务端直投公网 IM 或桌面客户端本地回环代理</div>
          </div>
        </div>
      </div>

      <!-- Connector 2 -->
      <div class="connection-pipe">
        <div class="pipe-label">FastAPI 核心调度 · 协作状态机单点写入 · MCP 领域工具调用 · 统一作业队列派发</div>
      </div>

      <!-- Layer 3: Core Orchestration Layer -->
      <div class="layer-section layer-core">
        <div class="layer-header">
          <div class="layer-badge badge-core">LAYER 3</div>
          <Server class="w-4 h-4 text-indigo-600" />
          <span>中枢编排与业务引擎层 (CORE ORCHESTRATION ENGINE - FASTAPI)</span>
        </div>
        <div class="core-engine-grid">
          <div class="node-card card-core">
            <div class="card-title"><Workflow class="w-4 h-4 text-indigo-600" /> 任务协作状态机引擎</div>
            <div class="card-desc">单点写入 + status_seq CAS 串行化 · 幂等事件回执 · 运行中引导与会话代次恢复</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><Terminal class="w-4 h-4 text-sky-600" /> 多引擎会话调度器 (Agent Registry)</div>
            <div class="card-desc">统一驱动 Claude Code CLI、OpenCode Server 与 DSH · 归一化工具事件与 Token 统计</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><Plug class="w-4 h-4 text-cyan-600" /> MCP 领域工具执行器 (Domain Tools)</div>
            <div class="card-desc">Streamable HTTP MCP 临时端口 · 业务产物强类型校验提交 · 只读沙箱读取与诊断守卫</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><Shield class="w-4 h-4 text-emerald-600" /> 人在回路与双向澄清协调器</div>
            <div class="card-desc">高危操作拦截与持久化问答回执 · 批注上下文注入 · 访客建议编辑采纳</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><FileText class="w-4 h-4 text-blue-600" /> 文档画布与联合修订引擎</div>
            <div class="card-desc">DOCX 书签区间/MD 精确选区映射 · 多已解决讨论联合提案 · 原位片段改写与草稿发布</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><Layers class="w-4 h-4 text-teal-600" /> 资产白板投影与负载引擎</div>
            <div class="card-desc">需求/文档/任务/案例/规程关系实时投影与权限裁剪 · 跨工作区成员运行负载聚合</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><Share2 class="w-4 h-4 text-violet-600" /> 本地协同与基线三方合并引擎</div>
            <div class="card-desc">远端基线增量三方合并 · Agent 自动适配冲突 · 本地交接纳入差异历史与增量评审</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><Verified class="w-4 h-4 text-purple-600" /> 差异归因、收尾与证据审计引擎</div>
            <div class="card-desc">ChangeProposal AST 比对与四维归因 · 三步收尾校验 · 覆盖度矩阵与受控附件导出</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><Search class="w-4 h-4 text-rose-600" /> 混合检索与规程诊断引擎</div>
            <div class="card-desc">多语料分区 RRF 混合检索 · 证据链行动板渲染 · 后台并行案例提炼与排障剧本驱动</div>
          </div>
          <div class="node-card card-core col-span-2">
            <div class="card-title"><Code class="w-4 h-4 text-amber-600" /> 可插拔插件与多能力适配器 (Pluggable Provider Adapters)</div>
            <div class="card-desc">多 Agent 后端注册表 (Claude Code / OpenCode / DSH) · 语音 ASR 插件 (百炼流式 / OpenAI 兼容 / 桌面离线 SenseVoice-Small) · Embedding 向量协议适配与探针检测</div>
          </div>
        </div>
      </div>

      <!-- Connector 3 -->
      <div class="connection-pipe">
        <div class="pipe-label">统一持久化作业调度 · 知识向量回填 · 增量快照与多仓沙盘统计</div>
      </div>

      <!-- Layer 4: Async Workers & Ops Layer -->
      <div class="layer-section layer-ops">
        <div class="layer-header">
          <div class="layer-badge badge-ops">LAYER 4</div>
          <Cpu class="w-4 h-4 text-amber-600" />
          <span>统一作业队列与异步计算层 (UNIFIED JOBS & ASYNC WORKERS)</span>
        </div>
        <div class="node-grid-3">
          <div class="node-card card-ops">
            <div class="card-title"><Cpu class="w-4 h-4 text-amber-600" /> 统一持久化作业队列 (sdd_ai_jobs)</div>
            <div class="card-desc">统筹任务准备、API Mock、Skill 分析、联合修订、规程晋升与删除归档；支持版本快照与幂等重试</div>
          </div>
          <div class="node-card card-ops">
            <div class="card-title"><Database class="w-4 h-4 text-purple-600" /> RAG 向量回填与索引 Worker</div>
            <div class="card-desc">按任务/消息/案例/规程语料切片 · 异步嵌入批量回填与 HNSW 索引版本平滑轮换</div>
          </div>
          <div class="node-card card-ops">
            <div class="card-title"><Layers class="w-4 h-4 text-emerald-600" /> 快照、沙盘扫描与流式打包引擎</div>
            <div class="card-desc">计划文档相对增量快照 · 2.5D 多仓 Git 提交与模块热力扫描缓存 · 产物安全校验与流式 ZIP 导出</div>
          </div>
        </div>
      </div>

      <!-- Connector 4 -->
      <div class="connection-pipe">
        <div class="pipe-label">统一存储链路 · 分布式锁与快照缓存 · 本地沙箱与双端运行时</div>
      </div>

      <!-- Layer 5: Infrastructure & Storage Layer -->
      <div class="layer-section layer-infra">
        <div class="layer-header">
          <div class="layer-badge badge-infra">LAYER 5</div>
          <Database class="w-4 h-4 text-slate-700" />
          <span>持久化存储与运行时基础设施层 (INFRASTRUCTURE & RUNTIME LAYER)</span>
        </div>
        <div class="infra-grid">
          <div class="node-card card-infra">
            <div class="card-title"><Database class="w-4 h-4 text-blue-600" /> PostgreSQL 18 (核心库)</div>
            <div class="card-desc">业务资产 · pg_jieba 中文全文检索 · pgvector 1024 维 HNSW 向量检索</div>
          </div>
          <div class="node-card card-infra">
            <div class="card-title"><Server class="w-4 h-4 text-red-600" /> Redis 内存快照</div>
            <div class="card-desc">分布式行级协调锁 · 撤销恢复暂存 · 搜索隔离分页快照 · ASR 凭证限流</div>
          </div>
          <div class="node-card card-infra">
            <div class="card-title"><Eye class="w-4 h-4 text-emerald-600" /> Elasticsearch 9.x（可选）</div>
            <div class="card-desc">BM25 词法全文 + nested kNN 向量 · Python RRF 等权混合检索扩展</div>
          </div>
          <div class="node-card card-infra">
            <div class="card-title"><Code class="w-4 h-4 text-slate-700" /> Git Worktree 与持久化存储</div>
            <div class="card-desc">多仓并发隔离工作树 · 会话与协同快照目录 · 受控结项证据附件存储</div>
          </div>
          <div class="node-card card-infra">
            <div class="card-title"><Cpu class="w-4 h-4 text-purple-600" /> 多引擎与双桌面运行时</div>
            <div class="card-desc">Claude Code / OpenCode / DSH · Electron & Tauri 2 · 内置 Node 资源服务与离线 ASR</div>
          </div>
        </div>
      </div>

    </main>

    <!-- Legend -->
    <footer class="arch-legend">
      <div class="legend-item">
        <div class="dot dot-presentation"></div>
        <span>前端交互层</span>
      </div>
      <div class="legend-item">
        <div class="dot dot-gateway"></div>
        <span>接入网关层</span>
      </div>
      <div class="legend-item">
        <div class="dot dot-core"></div>
        <span>中枢调度层</span>
      </div>
      <div class="legend-item">
        <div class="dot dot-ops"></div>
        <span>异步作业层</span>
      </div>
      <div class="legend-item">
        <div class="dot dot-infra"></div>
        <span>基础设施层</span>
      </div>
    </footer>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&family=Poppins:wght@500;600;700&display=swap');

.arch-container {
  min-height: 100vh;
  background: #f8fafc;
  font-family: 'Outfit', sans-serif;
  color: #0f172a;
  padding: 3rem 2rem 5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.arch-header {
  text-align: center;
  margin-bottom: 3.5rem;
  position: relative;
  width: 100%;
  max-width: 1180px;
}

.back-btn {
  position: absolute;
  left: 0;
  top: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: #0ea5e9;
  font-weight: 600;
  font-size: 0.9375rem;
  cursor: pointer;
  transition: color 0.2s;
}

.back-btn:hover {
  color: #0284c7;
}

.title {
  font-family: 'Poppins', sans-serif;
  font-size: 2.25rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
  color: #0f172a;
}

.subtitle {
  color: #64748b;
  font-size: 1rem;
}

/* Canvas */
.diagram-canvas {
  width: 100%;
  max-width: 1180px;
  display: flex;
  flex-direction: column;
  gap: 0;
}

/* Layer Section */
.layer-section {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 1.25rem;
  padding: 1.75rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
  position: relative;
  transition: border-color 0.3s;
}

.layer-section:hover {
  border-color: #cbd5e1;
}

.layer-header {
  font-size: 0.75rem;
  font-weight: 700;
  color: #64748b;
  letter-spacing: 0.06em;
  display: flex;
  align-items: center;
  gap: 0.625rem;
  margin-bottom: 1.25rem;
}

.layer-badge {
  font-size: 0.6875rem;
  font-weight: 800;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  letter-spacing: 0.05em;
}

.badge-presentation { background: #e0f2fe; color: #0369a1; }
.badge-gateway { background: #dbeafe; color: #1d4ed8; }
.badge-core { background: #ede9fe; color: #6d28d9; }
.badge-ops { background: #fef3c7; color: #b45309; }
.badge-infra { background: #f1f5f9; color: #334155; }

/* Grid Layouts */
.workbench-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.node-grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.core-engine-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.col-span-2 {
  grid-column: span 3;
}

.infra-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 1rem;
}

/* Node Card */
.node-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.875rem;
  padding: 1.125rem;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
}

.node-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.08);
}

.card-workbench:hover { border-color: #38bdf8; background: #f0f9ff; }
.card-gateway:hover { border-color: #60a5fa; background: #eff6ff; }
.card-core:hover { border-color: #a78bfa; background: #f5f3ff; }
.card-ops:hover { border-color: #fbbf24; background: #fffbeb; }
.card-infra:hover { border-color: #94a3b8; background: #f1f5f9; }

.card-title {
  font-size: 0.9375rem;
  font-weight: 700;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.375rem;
}

.card-desc {
  font-size: 0.8125rem;
  color: #64748b;
  line-height: 1.5;
}

/* Connecting Pipe */
.connection-pipe {
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.connection-pipe::before {
  content: '';
  position: absolute;
  width: 2px;
  height: 100%;
  background: linear-gradient(to bottom, #cbd5e1, #94a3b8);
  z-index: 1;
}

.pipe-label {
  background: #ffffff;
  padding: 0.25rem 0.875rem;
  border: 1px solid #e2e8f0;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  z-index: 2;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);
}

/* Legend */
.arch-legend {
  margin-top: 4rem;
  display: flex;
  flex-wrap: wrap;
  gap: 2rem;
  padding: 1.25rem 2.5rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 9999px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8125rem;
  color: #475569;
  font-weight: 600;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot-presentation { background: #0284c7; }
.dot-gateway { background: #2563eb; }
.dot-core { background: #7c3aed; }
.dot-ops { background: #d97706; }
.dot-infra { background: #475569; }

/* Responsive */
@media (max-width: 1024px) {
  .workbench-grid, .node-grid-3, .core-engine-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .col-span-2 {
    grid-column: span 2;
  }
  .infra-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .workbench-grid, .node-grid-3, .core-engine-grid, .infra-grid {
    grid-template-columns: 1fr;
  }
  .col-span-2 {
    grid-column: span 1;
  }
  .arch-legend {
    border-radius: 1rem;
    gap: 1rem;
    padding: 1rem;
  }
}
</style>
