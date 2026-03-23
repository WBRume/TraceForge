<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { 
  ChevronLeft, Book, Shield, Zap, Code, 
  Workflow, Terminal, LayoutDashboard, MessageSquare,
  CheckCircle, ArrowRight, Info
} from 'lucide-vue-next'

const router = useRouter()

const sections = [
  { id: 'intro', title: '平台简介', icon: Book },
  { id: 'stack', title: '技术栈与约束', icon: Shield },
  { id: 'workflow-1', title: '阶段一：规格与规划', icon: Workflow },
  { id: 'workflow-2', title: '阶段二：代码生成', icon: Code },
  { id: 'workflow-3', title: '阶段三：环境测试', icon: Zap },
  { id: 'hitl', title: '人机协同 (HITL)', icon: MessageSquare },
  { id: 'protocol', title: '通信协议', icon: Terminal },
  { id: 'portal', title: '可视化要求', icon: LayoutDashboard }
]

const activeSection = ref('intro')
const scrollToSection = (id: string) => {
  activeSection.value = id
  const el = document.getElementById(id)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

onMounted(() => {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting && entry.intersectionRatio > 0.5) {
        activeSection.value = entry.target.id
      }
    })
  }, { threshold: 0.5 })

  sections.forEach(s => {
    const el = document.getElementById(s.id)
    if (el) observer.observe(el)
  })
})
</script>

<template>
  <div class="docs-layout">
    <!-- Sidebar -->
    <aside class="docs-sidebar">
      <div class="sidebar-header" @click="router.push('/')">
        <ChevronLeft class="w-5 h-5" />
        <span>返回门户</span>
      </div>
      
      <nav class="sidebar-nav">
        <a 
          v-for="s in sections" 
          :key="s.id"
          href="javascript:void(0)"
          class="nav-item"
          :class="{ active: activeSection === s.id }"
          @click="scrollToSection(s.id)"
        >
          <component :is="s.icon" class="w-4 h-4" />
          {{ s.title }}
        </a>
      </nav>
    </aside>

    <!-- Main Content -->
    <main class="docs-content">
      <div class="content-container">
        <!-- Intro -->
        <section id="intro" class="doc-section">
          <h1>规范驱动开发 (SDD) 基础能力平台</h1>
          <p class="lead">SDD Native 是一个顶级的 AI Agent 原生研发平台，旨在通过“规格驱动”理念，将复杂的系统工程 (SE) 文档转化为高质量、可运行的生产代码。</p>
          
          <div class="info-card">
            <Info class="w-5 h-5 text-blue-500" />
            <div class="info-body">
              <strong>核心使命：</strong>消除研发过程中的歧义，实现从规格说明书到全栈项目的自动化闭环演化。
            </div>
          </div>

          <div class="grid-2 mt-8">
            <div class="feature-box">
              <h3>输入源 (Input)</h3>
              <ul>
                <li>SE 规格文档解析内容</li>
                <li>全局 Task ID 追踪</li>
                <li>多租户操作上下文 (User/Workspace)</li>
                <li>物理隔离的 Project Path</li>
              </ul>
            </div>
            <div class="feature-box">
              <h3>执行边界 (Execution)</h3>
              <ul>
                <li>Python 边车 (Sidecar) 引擎</li>
                <li>Claude Code CLI 工具链</li>
                <li>Superpowers 自动化脚本库</li>
                <li>伪终端 (PTY) 实时流转</li>
              </ul>
            </div>
          </div>
        </section>

        <hr />

        <!-- Stack -->
        <section id="stack" class="doc-section">
          <h2>1. 技术栈与底层约束</h2>
          <div class="stack-grid">
            <div class="stack-item">
              <div class="stack-label">前端</div>
              <div class="stack-value">Vue3 + Vite + Pinia + Chat UX</div>
            </div>
            <div class="stack-item">
              <div class="stack-label">后端</div>
              <div class="stack-value">Python 3.14 + FastAPI + JWT</div>
            </div>
            <div class="stack-item">
              <div class="stack-label">数据库</div>
              <div class="stack-value">MySQL (多租户物理/逻辑隔离)</div>
            </div>
            <div class="stack-item">
              <div class="stack-label">核心引擎</div>
              <div class="stack-value">Claude Code CLI + PTY Bridge</div>
            </div>
          </div>
          <p class="mt-4 text-slate-600">所有数据资产（任务、日志、配置）必须包含 <code>workspace_id</code> 和 <code>creator_id</code>，确保企业级多租户安全。</p>
        </section>

        <!-- Workflow 1 -->
        <section id="workflow-1" class="doc-section">
          <h2>2. 阶段一：规格转换与规划 (Spec to Plan)</h2>
          <div class="workflow-steps">
            <div class="step">
              <div class="step-num">2.1</div>
              <div class="step-content">
                <h3>规格语义化与头脑风暴 (Brainstorming)</h3>
                <p>调用 <code>/brainstorming</code> 命令。基于 Superpowers 内置规范，将原始文档转化为标准化的系统设计文档 (Design Doc)。</p>
              </div>
            </div>
            <div class="step">
              <div class="step-num">2.2</div>
              <div class="step-content">
                <h3>工作区初始化 (Git Worktrees)</h3>
                <p>调用 <code>/using-git-worktrees</code>。支持远程 Git 仓库同步或本地初始化，创建隔离的工作区基线。</p>
              </div>
            </div>
            <div class="step">
              <div class="step-num">2.3</div>
              <div class="step-content">
                <h3>计划生成与任务拆解 (Writing Plans)</h3>
                <p>调用 <code>/writing-plans</code>。将宏观设计拆解为可由 Agent 自动执行的微观任务计划。</p>
              </div>
            </div>
          </div>
        </section>

        <!-- Workflow 2 -->
        <section id="workflow-2" class="doc-section">
          <h2>3. 阶段二：SDD 代码生成与自纠正</h2>
          <div class="loop-container">
            <div class="loop-box green">
              <CheckCircle class="w-6 h-6" />
              <span>红-绿-重构 (TDD) 闭环</span>
            </div>
            <ArrowRight class="w-6 h-6 text-slate-300" />
            <div class="loop-box blue">
              <Code class="w-6 h-6" />
              <span>Subagent 驱动代码生成</span>
            </div>
          </div>
          <p class="mt-4">执行 <code>/subagent-driven-development</code> 配合 <code>/test-driven-development</code>。所有具体的流程规范由 Superpowers 接管，Agent 负责高层调度与纠偏。</p>
        </section>

        <!-- Workflow 3 -->
        <section id="workflow-3" class="doc-section">
          <h2>4. 阶段三：环境自动化测试</h2>
          <div class="mcp-grid">
            <div class="mcp-card">
              <h4>前端测试 (Playwright)</h4>
              <p>调度 Chrome 模拟用户操作，验证 UI 渲染与路由逻辑。</p>
            </div>
            <div class="mcp-card">
              <h4>后端测试 (Postman)</h4>
              <p>自动化测试 API 状态码、JSON 结构及数据库持久化。</p>
            </div>
            <div class="mcp-card">
              <h4>全链路 E2E</h4>
              <p>串联前端 UI 与后端接口，执行数据一致性验证。</p>
            </div>
          </div>
        </section>

        <!-- HITL -->
        <section id="hitl" class="doc-section">
          <h2>5. 异常处理与人机协同 (HITL)</h2>
          <div class="hitl-illustration">
            <div class="hitl-box">Agent 运行中</div>
            <div class="hitl-line danger">破坏性确认 (覆盖/删除)</div>
            <div class="hitl-box highlight">UI 挂起 & 等待确认</div>
            <div class="hitl-line success">用户点击 -> 继续执行</div>
          </div>
          <p class="mt-6">任何自纠正闭环超过 3 次重试或遇到需要决策的 [y/N] 提示时，后台立即挂起 PTY 进程，通过 WebSocket 将交互卡片推送到前端界面。</p>
        </section>

        <!-- Protocol -->
        <section id="protocol" class="doc-section">
          <h2>6. 通信与进度同步协议</h2>
          <div class="code-block">
            <div class="code-header">Stdout JSON 包裹协议 [AGENT_STATE_SYNC]</div>
            <pre>
{
  "workspace_id": "ws-778899",
  "task_id": "task-12345",
  "status": "CODING",
  "message": "正在依据 Plan 编写目标模块的单元测试..."
}
            </pre>
          </div>
        </section>

        <!-- Portal -->
        <section id="portal" class="doc-section">
          <h2>7. 门户平台可视化</h2>
          <ul class="check-list">
            <li>现代化对话 UX (类似 ChatGPT/Claude)</li>
            <li>置顶富文本卡片 (HITL, Status, Results)</li>
            <li>资产化数据查询 (Design Docs, Tests, Metrics)</li>
            <li>图表看板 (成功率、耗时、重试分布)</li>
          </ul>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.docs-layout {
  display: flex;
  height: 100vh;
  background: #fff;
  color: #1a1a1a;
  overflow: hidden;
}

/* Sidebar */
.docs-sidebar {
  width: 280px;
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 1.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  color: #0ea5e9;
  cursor: pointer;
  border-bottom: 1px solid #e2e8f0;
}

.sidebar-nav {
  padding: 1rem 0;
  flex: 1;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1.5rem;
  text-decoration: none;
  color: #475569;
  font-size: 0.9375rem;
  transition: all 0.2s;
}

.nav-item:hover {
  background: #f1f5f9;
  color: #0ea5e9;
}

.nav-item.active {
  background: #fff;
  color: #0ea5e9;
  font-weight: 600;
  box-shadow: inset 4px 0 0 #0ea5e9;
}

/* Content */
.docs-content {
  flex: 1;
  overflow-y: auto;
  scroll-behavior: smooth;
  padding: 4rem 2rem;
}

.content-container {
  max-width: 800px;
  margin: 0 auto;
}

.doc-section {
  padding: 2rem 0 4rem;
}

h1 { font-size: 2.5rem; font-weight: 800; margin-bottom: 1.5rem; color: #020617; }
h2 { font-size: 1.75rem; font-weight: 700; margin-bottom: 1.5rem; color: #0f172a; border-bottom: 2px solid #f1f5f9; padding-bottom: 0.5rem; }
h3 { font-size: 1.25rem; font-weight: 600; margin-bottom: 1rem; color: #1e293b; }
h4 { font-size: 1rem; font-weight: 600; margin-bottom: 0.5rem; color: #334155; }

.lead { font-size: 1.125rem; color: #475569; line-height: 1.6; margin-bottom: 2rem; }

.info-card {
  display: flex;
  gap: 1rem;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 1rem;
  border-radius: 12px;
  margin: 2rem 0;
}

.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
.feature-box { background: #f8fafc; padding: 1.5rem; border-radius: 12px; }
.feature-box ul { padding-left: 1.25rem; color: #475569; font-size: 0.875rem; margin-top: 0.5rem; }

.stack-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; margin-top: 1rem; }
.stack-item { background: #fff; border: 1px solid #e2e8f0; padding: 1rem; border-radius: 8px; }
.stack-label { font-size: 0.75rem; color: #64748b; margin-bottom: 0.25rem; text-transform: uppercase; letter-spacing: 0.05em; }
.stack-value { font-weight: 600; color: #0f172a; }

.workflow-steps { display: flex; flex-direction: column; gap: 2rem; }
.step { display: flex; gap: 1.5rem; }
.step-num { 
  background: #0ea5e9; color: #fff; width: 32px; height: 32px; 
  border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-weight: 700; flex-shrink: 0;
}

.loop-container { display: flex; align-items: center; gap: 1rem; margin: 2rem 0; }
.loop-box { flex: 1; padding: 1.5rem; border-radius: 12px; display: flex; align-items: center; gap: 1rem; font-weight: 600; }
.loop-box.green { background: #ecfdf5; color: #059669; border: 1px solid #a7f3d0; }
.loop-box.blue { background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; }

.mcp-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }
.mcp-card { background: #fff; border: 1px solid #e2e8f0; padding: 1.25rem; border-radius: 12px; }

.hitl-illustration { 
  background: #0f172a; padding: 2rem; border-radius: 16px; 
  display: flex; flex-direction: column; align-items: center; gap: 0.5rem;
  color: #fff; font-family: monospace;
}
.hitl-box { border: 1px solid #334155; padding: 0.5rem 1rem; border-radius: 4px; }
.hitl-box.highlight { background: #1e293b; border-color: #0ea5e9; color: #0ea5e9; }
.hitl-line { font-size: 0.75rem; }
.hitl-line.danger { color: #f43f5e; }
.hitl-line.success { color: #10b981; }

.code-block { background: #1e293b; border-radius: 8px; overflow: hidden; }
.code-header { background: #334155; padding: 0.5rem 1rem; font-size: 0.75rem; color: #94a3b8; font-family: monospace; }
.code-block pre { padding: 1rem; color: #e2e8f0; font-family: monospace; font-size: 0.875rem; }

.check-list { list-style: none; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.check-list li { display: flex; align-items: center; gap: 0.5rem; color: #475569; }
.check-list li::before { content: '✓'; color: #10b981; font-weight: bold; }

hr { border: 0; border-top: 1px solid #f1f5f9; margin: 3rem 0; }
code { background: #f1f5f9; padding: 0.2rem 0.4rem; border-radius: 4px; font-family: monospace; color: #db2777; }
</style>
