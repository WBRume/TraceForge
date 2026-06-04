<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { 
  ChevronLeft, Book, Shield, Code, Terminal,
  CheckCircle, ArrowRight, Info,
  Settings, MessageSquareDiff, ServerCog, Verified, Layers,
  Network
} from 'lucide-vue-next'
import Flowchart from '@/components/Flowchart.vue'

const router = useRouter()
const activeTab = ref('text') // 'text' or 'graph'
const activeSection = ref('intro')

const sections = [
  { id: 'intro', title: '平台简介', icon: Book },
  { id: 'workflow-1', title: '第一阶段：环境与能力组装', icon: Settings },
  { id: 'workflow-2', title: '第二阶段：需求资产与澄清', icon: MessageSquareDiff },
  { id: 'workflow-3', title: '第三阶段：契约隔离与 Mock', icon: ServerCog },
  { id: 'workflow-4', title: '第四阶段：AI 协作编码', icon: Code },
  { id: 'workflow-5', title: '第五阶段：验收、差异归因与知识沉淀', icon: Verified },
  { id: 'stack', title: '技术栈与约束', icon: Shield },
  { id: 'protocol', title: '通信协议', icon: Terminal }
]

const scrollToSection = (id: string) => {
  activeSection.value = id
  const el = document.getElementById(id)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

const setupObserver = () => {
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
  return observer
}

let currentObserver: IntersectionObserver | null = null

onMounted(() => {
  currentObserver = setupObserver()
})

watch(activeTab, async (newTab) => {
  if (newTab === 'text') {
    if (currentObserver) currentObserver.disconnect()
    await nextTick()
    currentObserver = setupObserver()
  }
})
</script>

<template>
  <div class="docs-viewport">
    <!-- Top Header / Tab Switcher -->
    <header class="docs-header">
      <div class="header-left" @click="router.push('/')">
        <ChevronLeft class="w-5 h-5" />
        <span>返回门户</span>
      </div>
      
      <div class="tab-switcher">
        <button 
          type="button"
          class="tab-btn" 
          :class="{ active: activeTab === 'text' }"
          @click="activeTab = 'text'"
        >
          <Book class="w-4 h-4" />
          文字版说明
        </button>
        <button 
          type="button"
          class="tab-btn" 
          :class="{ active: activeTab === 'graph' }"
          @click="activeTab = 'graph'"
        >
          <Network class="w-4 h-4" />
          图形版拓扑
        </button>
      </div>

      <div class="header-right">
        <!-- Placeholder for symmetry -->
      </div>
    </header>

    <div class="docs-main-area">
      <!-- Sidebar (Only for text mode) -->
      <aside v-if="activeTab === 'text'" class="docs-sidebar">
        <nav class="sidebar-nav">
          <a 
            v-for="s in sections" 
            :key="s.id"
            href="javascript:void(0)"
            class="nav-item"
            :class="{ active: activeSection === s.id }"
            @click="scrollToSection(s.id)"
          >
            <component :is="s.icon" class="w-4 h-4 text-slate-400" />
            <span class="nav-label">{{ s.title }}</span>
          </a>
        </nav>
      </aside>

      <!-- Main Content Area -->
      <main v-if="activeTab === 'text'" class="docs-content">
        <div class="content-container">
          <!-- Intro -->
          <section id="intro" class="doc-section">
            <h1>TraceForge — 开发态资产管理 + AI 可追溯协作平台</h1>
            <p class="lead">TraceForge 将开发过程中产生的需求、规范、决策、证据等结构化管理为可追溯资产；AI 与开发者全程协同，过程可观测、决策可审查、经验可沉淀。</p>

            <div class="info-card">
              <Info class="w-5 h-5 text-blue-500" />
              <div class="info-body">
                <strong>核心使命：</strong>将开发过程产物资产化，让 AI 协作过程全链路可追溯，让团队知识从实践中沉淀复用。
              </div>
            </div>

            <div class="grid-2 mt-8">
              <div class="feature-box">
                <h3>资产化管理 (Asset)</h3>
                <ul>
                  <li>需求资产库与层级拆分</li>
                  <li>任务决策与证据注册表</li>
                  <li>人机差异 (Human Delta) 记录</li>
                  <li>知识沉淀与晋升</li>
                </ul>
              </div>
              <div class="feature-box">
                <h3>可追溯协作 (Traceable)</h3>
                <ul>
                  <li>覆盖度矩阵贯穿全链路</li>
                  <li>AI 执行过程实时可观测</li>
                  <li>HITL 关键决策人工介入</li>
                  <li>过程审计与证据链自动生成</li>
                </ul>
              </div>
            </div>
          </section>

          <hr />

          <!-- Workflow 1 -->
          <section id="workflow-1" class="doc-section">
            <h2>1. 第一阶段：环境与能力组装 (Skills)</h2>
            <div class="workflow-steps">
              <div class="step">
                <div class="step-num">1.1</div>
                <div class="step-content">
                  <h3>上下文隔离 (Workspaces)</h3>
                  <p>启动独立的工作区边界与 Git Baselines。确保生成过程运行在隔离安全的应用沙盒中，不会影响其它项目代码。工作区承载需求资产、任务、Skills、API Mock 项目和知识库等全部资源。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">1.2</div>
                <div class="step-content">
                  <h3>大模型能力定义 (Skill Runtime Editor)</h3>
                  <p>加载并在当前环境中预声明 AI Agent 的技能矩阵 (Skills)。明确告诉大模型遵循哪种技术架构风格（如：Vue Composition API 范式、Spring Boot Restful 结构、CSS Tailwind 规则）。Skills 支持版本管理、行级评审和团队经验沉淀，确保 AI 执行上下文一致且可复用。</p>
                </div>
              </div>
            </div>
          </section>

          <!-- Workflow 2 -->
          <section id="workflow-2" class="doc-section">
            <h2>2. 第二阶段：需求资产与澄清 (Requirement & Clarification)</h2>
            <div class="loop-container" style="margin: 1rem 0;">
              <div class="loop-box blue">
                <Layers class="w-6 h-6" />
                <span>需求资产结构化管理</span>
              </div>
              <ArrowRight class="w-6 h-6 text-slate-300" />
              <div class="loop-box green">
                <MessageSquareDiff class="w-6 h-6" />
                <span>双向澄清与需求对齐 (Clarification)</span>
              </div>
            </div>
            <p class="mt-4">
              进入<strong>需求资产管理与双向澄清流程</strong>。需求不再是静态文档，而是可拆分、可关联、可追溯的结构化资产。AI 与开发者、产品经理在需求层级进行<strong>协作与对齐</strong>。
              通过 Clarification 机制双向澄清歧义，需求可关联多个 Task，覆盖度矩阵贯穿从需求到证据的完整链路，消除所有阻塞后方可进入执行期。
            </p>
          </section>

          <!-- Workflow 3 -->
          <section id="workflow-3" class="doc-section">
            <h2>3. 第三阶段：契约隔离与预发布 (API Mock Workbench)</h2>
            <div class="feature-box mt-4">
              <h3 class="flex items-center gap-2">
                <ServerCog class="w-5 h-5 text-blue-500" />
                客户端虚拟 Server (Vite Node Mocking)
              </h3>
              <p class="mt-2 text-slate-600">
                根据通过且无歧义的需求文档说明，AI 工具链首先不干预核心业务逻辑代码，而是推导前后端交互边界，<strong>自动创建一份供前端使用的数据 Mock Server 契约</strong>。
              </p>
              <ul class="mt-4">
                <li>此层直接作为基于 Node/Vite 层面的本地插件运行，充当 Virtual Server。</li>
                <li>前端 UI Agent 面对稳定的 Virtual Server 开发，实现无需等待后端的并行解耦。</li>
                <li>后端通过 Mock 契约文档编写核心控制器（Controller）与接口。</li>
              </ul>
            </div>
          </section>

          <!-- Workflow 4 -->
          <section id="workflow-4" class="doc-section">
            <h2>4. 第四阶段：AI 协作编码 (Human-AI Collaboration)</h2>
            <div class="loop-container">
              <div class="loop-box green">
                <CheckCircle class="w-6 h-6" />
                <span>AI 生成代码 (TDD)</span>
              </div>
              <ArrowRight class="w-6 h-6 text-slate-300" />
              <div class="loop-box blue">
                <Code class="w-6 h-6" />
                <span>HITL 人工审查与介入</span>
              </div>
            </div>
            <p class="mt-4">基于锁定的 Mock 契约，AI 与开发者全程协同推进编码。关键决策点通过 HITL 机制人工介入确认，Token 归因与成本全程可观测。AI 不是替代开发者，而是与开发者共同推进——过程可观测、决策可审查。</p>
          </section>

          <!-- Workflow 5 -->
          <section id="workflow-5" class="doc-section">
            <h2>5. 第五阶段：验收、差异归因与知识沉淀</h2>
            <div class="mcp-grid">
              <div class="mcp-card">
                <h4>环境验收 (E2E)</h4>
                <p>脱离 Mock 阶段对接正式环境，实现后端接口穿透并断言返回结构，生成验收证据。</p>
              </div>
              <div class="mcp-card">
                <h4>人机差异归因 (Human Delta)</h4>
                <p>归因 AI 输出与人工最终修改之间的差异，差异看板展示每次修改来源，支撑质量保障与过程审计。</p>
              </div>
              <div class="mcp-card">
                <h4>证据链与知识沉淀</h4>
                <p>任务收尾时自动生成证据链与过程审计。从决策、差异、澄清中晋升知识资产，让经验可积累、可检索、可复用。</p>
              </div>
            </div>
          </section>

          <!-- Stack -->
          <section id="stack" class="doc-section">
            <h2>6. 技术栈与底层引擎边界</h2>
            <div class="stack-grid">
              <div class="stack-item">
                <div class="stack-label">前端层级结构</div>
                <div class="stack-value">Vue3 + Vite + TypeScript + Monaco Editor</div>
              </div>
              <div class="stack-item">
                <div class="stack-label">中介调度者层</div>
                <div class="stack-value">Python FastAPI + JWT + Workflow Engine</div>
              </div>
              <div class="stack-item">
                <div class="stack-label">底层执行引擎</div>
                <div class="stack-value">Claude Code CLI + Skills Runtime</div>
              </div>
              <div class="stack-item">
                <div class="stack-label">数据与持久态</div>
                <div class="stack-value">MySQL + 资产管理 + 知识库</div>
              </div>
            </div>
            <p class="mt-4 text-slate-600">所有数据资产（需求、任务、证据、知识）必须包含 <code>workspace_id</code> 和 <code>creator_id</code>，确保企业级多租户安全与全链路追溯。</p>
          </section>

          <!-- Protocol -->
          <section id="protocol" class="doc-section">
            <h2>7. 通信与进度同步协议 (Protocol)</h2>
            <div class="code-block">
              <div class="code-header">Stdout JSON 包裹协议 [AGENT_STATE_SYNC]</div>
              <pre>
{
  "workspace_id": "ws-778899",
  "task_id": "task-12345",
  "status": "CODING",
  "skill_context": "vue-best-practices",
  "message": "正在依据 Mock 契约编写当前前端组件的渲染..."
}
              </pre>
            </div>
          </section>
        </div>
      </main>

      <main v-else class="docs-content full-width">
        <div class="graph-container">
          <Flowchart />
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.docs-viewport {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #fff;
  color: #1a1a1a;
  overflow: hidden;
}

/* Header */
.docs-header {
  height: 64px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 1.5rem;
  z-index: 100;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  color: #0ea5e9;
  cursor: pointer;
  width: 200px;
}

.tab-switcher {
  display: flex;
  background: #f1f5f9;
  padding: 0.25rem;
  border-radius: 12px;
  gap: 0.25rem;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1.25rem;
  border-radius: 10px;
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s;
  background: transparent;
  user-select: none;
}

.tab-btn:hover {
  color: #0ea5e9;
}

.tab-btn.active {
  background: #fff;
  color: #0ea5e9;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

.header-right {
  width: 200px; /* Symmetry */
}

/* Layout */
.docs-main-area {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* Sidebar */
.docs-sidebar {
  width: 280px;
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
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
  padding: 2rem;
}

.docs-content.full-width {
  padding: 0;
}

.graph-container {
  height: 100%;
  width: 100%;
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
  border: 1px solid #e2e8f0;
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
.loop-box.blue { background: #eff6ff; color: #2563eb; border: 1px solid #e2e8f0; }

.mcp-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }
.mcp-card { background: #fff; border: 1px solid #e2e8f0; padding: 1.25rem; border-radius: 12px; }

.code-block { background: #1e293b; border-radius: 8px; overflow: hidden; }
.code-header { background: #334155; padding: 0.5rem 1rem; font-size: 0.75rem; color: #94a3b8; font-family: monospace; }
.code-block pre { padding: 1rem; color: #e2e8f0; font-family: monospace; font-size: 0.875rem; }

hr { border: 0; border-top: 1px solid #f1f5f9; margin: 3rem 0; }
code { background: #f1f5f9; padding: 0.2rem 0.4rem; border-radius: 4px; font-family: monospace; color: #db2777; }
</style>
