<script setup lang="ts">
import { useRouter } from 'vue-router'
import { 
  ChevronLeft, Monitor, Server, Database, 
  Terminal, Workflow, Cpu,
  Layers, Lock,
  Settings, ServerCog, Code,
  GitBranch, Verified, LibraryBig, Eye, Shield, Zap, Plug
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
      <div class="subtitle">开发态资产管理 · AI 可追溯协作 · 端到端闭环工程架构</div>
    </header>

    <!-- Diagram Canvas -->
    <main class="diagram-canvas">
      
      <!-- Layer 1: Presentation & Workbench Layer -->
      <div class="layer-section layer-presentation">
        <div class="layer-header">
          <div class="layer-badge badge-presentation">LAYER 1</div>
          <Monitor class="w-4 h-4 text-sky-600" />
          <span>前端视图与交互工作台层 (VUE 3 + TYPESCRIPT + PINIA)</span>
        </div>
        <div class="workbench-grid">
          <div class="node-card card-workbench">
            <div class="card-title"><Terminal class="w-4 h-4 text-sky-600" /> 任务协同工作台 (Task Chat)</div>
            <div class="card-desc">PTY 终端会话 · 语音转录输入 · 计划文档快照 · Token 成本归因</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><Layers class="w-4 h-4 text-emerald-600" /> 资产与追溯工作台 (Assets)</div>
            <div class="card-desc">需求树状拆分 · 块级规格评审 · 覆盖度矩阵 · 证据链注册表</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><ServerCog class="w-4 h-4 text-indigo-600" /> 契约隔离工作台 (API Mock)</div>
            <div class="card-desc">OpenAPI 导入 · 实体推导 · 多场景 Mock Case · 动态代理网关</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><GitBranch class="w-4 h-4 text-purple-600" /> 人机差异工作台 (Delta Workbench)</div>
            <div class="card-desc">ChangeProposal 比对 · 修改四维归因 · 风险聚合与幻觉率评估</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><LibraryBig class="w-4 h-4 text-amber-600" /> 知识中心与案例库 (Knowledge & Playbooks)</div>
            <div class="card-desc">四维知识资产 · 真实故障排障剧本 (Playbook) · 案例晋升评审</div>
          </div>
          <div class="node-card card-workbench">
            <div class="card-title"><Settings class="w-4 h-4 text-slate-600" /> 系统能力配置中心 (System Config)</div>
            <div class="card-desc">运行时能力矩阵 · 产品项目管理 · 可插拔插件管理与探针测试</div>
          </div>
        </div>
      </div>

      <!-- Connector 1 -->
      <div class="connection-pipe">
        <div class="pipe-label">HTTP RESTful API · WebSocket 双向广播 · Vite Proxy / 反向代理</div>
      </div>

      <!-- Layer 2: Gateway & Protocol Layer -->
      <div class="layer-section layer-gateway">
        <div class="layer-header">
          <div class="layer-badge badge-gateway">LAYER 2</div>
          <Zap class="w-4 h-4 text-blue-600" />
          <span>接入网关与通信协议层 (GATEWAY & PROTOCOLS)</span>
        </div>
        <div class="node-grid-3">
          <div class="node-card card-gateway">
            <div class="card-title"><ServerCog class="w-4 h-4 text-blue-600" /> 动态虚拟代理网关</div>
            <div class="card-desc">单接口 MOCK 仿真与 PROXY 真实切流 · 异常混沌注入</div>
          </div>
          <div class="node-card card-gateway">
            <div class="card-title"><Plug class="w-4 h-4 text-sky-600" /> WebSocket 实时协同总线</div>
            <div class="card-desc">Agent 运行态推送 · 工具调用实时流 · 协作事件广播</div>
          </div>
          <div class="node-card card-gateway">
            <div class="card-title"><Lock class="w-4 h-4 text-indigo-600" /> 安全鉴权与隔离拦截</div>
            <div class="card-desc">OAuth2 三方登录 (GitHub/GitLab) · JWT 鉴权 · 工作区 RBAC 隔离</div>
          </div>
        </div>
      </div>

      <!-- Connector 2 -->
      <div class="connection-pipe">
        <div class="pipe-label">FastAPI 核心调度 · 状态机生命周期派发</div>
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
            <div class="card-title"><Workflow class="w-4 h-4 text-indigo-600" /> SDD 工作流状态机引擎</div>
            <div class="card-desc">驱动任务阶段流转：初始化 → 执行态 → 挂起态 → 收尾终态</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><Terminal class="w-4 h-4 text-sky-600" /> 终端交互桥接 (Agent Bridge)</div>
            <div class="card-desc">Claude CLI 进程调度 · PTY 交互式输入输出 · Stdout 协议解析</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><Shield class="w-4 h-4 text-emerald-600" /> 人在回路协调器 (HITL)</div>
            <div class="card-desc">高风险改动挂起拦截 · 需求双向澄清 (Clarification) 上下文对齐</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><GitBranch class="w-4 h-4 text-purple-600" /> 人机差异归因引擎 (Delta)</div>
            <div class="card-desc">ChangeProposal 与 Final Patch AST 对比 · 四维差异归因打标</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><Verified class="w-4 h-4 text-blue-600" /> 任务收尾工作流引擎</div>
            <div class="card-desc">基准比对 (Baseline) → 专家审查 (Review) → 最终摘要 (Summary)</div>
          </div>
          <div class="node-card card-core">
            <div class="card-title"><Eye class="w-4 h-4 text-teal-600" /> 全链路追溯覆盖服务</div>
            <div class="card-desc">Requirement 到 Evidence 全节点矩阵计算 · 断链阻断预警</div>
          </div>
          <div class="node-card card-core col-span-2">
            <div class="card-title"><Code class="w-4 h-4 text-amber-600" /> 可插拔插件适配层 (Pluggable Provider Adapters)</div>
            <div class="card-desc">LLM 模型提供商适配 · 语音 ASR 插件 (Web 直连 / 桌面离线 Whisper/FunASR) · 向量 Embedding 插件</div>
          </div>
        </div>
      </div>

      <!-- Connector 3 -->
      <div class="connection-pipe">
        <div class="pipe-label">异步作业分发 · 知识回填 · 计划快照比对</div>
      </div>

      <!-- Layer 4: Async Workers & Ops Layer -->
      <div class="layer-section layer-ops">
        <div class="layer-header">
          <div class="layer-badge badge-ops">LAYER 4</div>
          <Cpu class="w-4 h-4 text-amber-600" />
          <span>异步作业与运营调度层 (ASYNC WORKERS & OPS LAYER)</span>
        </div>
        <div class="node-grid-3">
          <div class="node-card card-ops">
            <div class="card-title"><Cpu class="w-4 h-4 text-amber-600" /> 任务作业队列 (Ops Queue)</div>
            <div class="card-desc">异步长任务调度 · AI Job 记录追踪 · 失败显式重试与死信管理</div>
          </div>
          <div class="node-card card-ops">
            <div class="card-title"><Database class="w-4 h-4 text-purple-600" /> RAG 向量回填 Worker</div>
            <div class="card-desc">知识库切片分段 · 异步向量化批量推送 · 索引版本平滑轮换</div>
          </div>
          <div class="node-card card-ops">
            <div class="card-title"><Layers class="w-4 h-4 text-emerald-600" /> 计划文档快照引擎</div>
            <div class="card-desc">按工作区独立扫描 · 识别任务创建快照相对变更 · 过滤存量噪声</div>
          </div>
        </div>
      </div>

      <!-- Connector 4 -->
      <div class="connection-pipe">
        <div class="pipe-label">持久化数据链路 · 状态缓存 · 本地沙箱隔离</div>
      </div>

      <!-- Layer 5: Infrastructure & Storage Layer -->
      <div class="layer-section layer-infra">
        <div class="layer-header">
          <div class="layer-badge badge-infra">LAYER 5</div>
          <Database class="w-4 h-4 text-slate-700" />
          <span>持久化存储与基础设施层 (INFRASTRUCTURE & DATA LAYER)</span>
        </div>
        <div class="infra-grid">
          <div class="node-card card-infra">
            <div class="card-title"><Database class="w-4 h-4 text-blue-600" /> MySQL 8.0</div>
            <div class="card-desc">工作区 · 需求资产库 · 任务决策 · 证据注册表 · 知识实体</div>
          </div>
          <div class="node-card card-infra">
            <div class="card-title"><Server class="w-4 h-4 text-red-600" /> Redis 内存快照</div>
            <div class="card-desc">分布式锁 · 会话状态暂存 · 混合检索 PIT 游标 · 隔离分页缓存</div>
          </div>
          <div class="node-card card-infra">
            <div class="card-title"><Eye class="w-4 h-4 text-emerald-600" /> Elasticsearch 9.x</div>
            <div class="card-desc">BM25 词法全文 + nested kNN 向量 + Python RRF 等权混合检索</div>
          </div>
          <div class="node-card card-infra">
            <div class="card-title"><Code class="w-4 h-4 text-slate-700" /> Git Worktree 沙箱</div>
            <div class="card-desc">任务物理隔离工作树 · 基准代码版本控制 · 环境安全沙盒</div>
          </div>
          <div class="node-card card-infra">
            <div class="card-title"><Cpu class="w-4 h-4 text-purple-600" /> 推理执行基础设施</div>
            <div class="card-desc">Claude CLI Bridge · 本地离线 Whisper/FunASR · 云端大模型接口</div>
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
