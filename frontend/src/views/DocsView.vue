<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { 
  ChevronLeft, Book, Shield, Code, Terminal,
  ArrowRight, Info,
  Settings, ServerCog, Verified, Layers,
  Network, Database, Eye, LibraryBig, GitBranch, Cpu, Stethoscope
} from '@/components/icons'
import Flowchart from '@/components/Flowchart.vue'

const router = useRouter()
const activeTab = ref('text') // 'text' or 'graph'
const activeSection = ref('intro')

const sections = [
  { id: 'intro', title: '平台定位与四大核心资产', icon: Book },
  { id: 'stage-1', title: '阶段一：工作区与需求资产建模', icon: Layers },
  { id: 'stage-2', title: '阶段二：契约先行与 API Mock 隔离', icon: ServerCog },
  { id: 'stage-3', title: '阶段三：技能装配与运行时插件', icon: Settings },
  { id: 'stage-4', title: '阶段四：终端协作与人在回路 (HITL)', icon: Terminal },
  { id: 'stage-5', title: '阶段五：人机差异分析 (Delta Workbench)', icon: GitBranch },
  { id: 'stage-6', title: '阶段六：任务收尾与追溯审计', icon: Verified },
  { id: 'troubleshoot', title: '故障诊断与排障剧本闭环 (Playbook)', icon: Stethoscope },
  { id: 'stack', title: '系统底座架构与混合检索', icon: Shield },
  { id: 'protocol', title: '状态机流转与通信协议', icon: Code }
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
      if (entry.isIntersecting && entry.intersectionRatio > 0.4) {
        activeSection.value = entry.target.id
      }
    })
  }, { threshold: 0.4 })

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
        <span>返回首页</span>
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
            <p class="lead">
              TraceForge 旨在彻底改变传统“把需求丢给 AI 然后开盲盒”的不可控模式。
              平台将软件研发全生命周期中的需求、规范、决策、人机差异与执行证据转化为结构化数字资产，
              构建从<strong>需求建模 → 契约隔离 → 终端协作 → 差异归因 → 过程收尾 → 知识晋升</strong>的确定性工程闭环。
            </p>

            <div class="info-card">
              <Info class="w-5 h-5 text-blue-500" />
              <div class="info-body">
                <strong>平台核心理念：</strong>代码仅是最终产物，开发过程中的思考、推导、修改动机与合规证据才是团队沉淀的核心资产。AI 不代替开发者，而是作为受控副驾协同推进。
              </div>
            </div>

            <div class="grid-2 mt-8">
              <div class="feature-box">
                <h3 class="flex items-center gap-2"><Database class="w-4 h-4 text-sky-600" /> 四大核心资产支柱</h3>
                <ul>
                  <li><strong>需求资产 (Requirements)</strong>：树状拆分分解、块级规格定义与验收准则。</li>
                  <li><strong>决策资产 (Decisions)</strong>：架构决策记录 (ADR)、方案权衡与修改归因。</li>
                  <li><strong>执行证据 (Evidences)</strong>：终端执行输出、单测报告、快照与审查记录。</li>
                  <li><strong>组织知识 (Knowledge)</strong>：业务概念、架构规范、运维排障剧本 (Playbook)。</li>
                </ul>
              </div>
              <div class="feature-box">
                <h3 class="flex items-center gap-2"><Eye class="w-4 h-4 text-emerald-600" /> 全链路可追溯体系</h3>
                <ul>
                  <li><strong>覆盖度矩阵</strong>：贯穿 Requirement → Task → Spec → Plan → AI Run → Review → Delta → Evidence。</li>
                  <li><strong>人在回路 (HITL)</strong>：关键与高风险决策强制人工介入授权。</li>
                  <li><strong>人机差异归因 (Delta)</strong>：AI 提议与人工最终代码精确对比。</li>
                  <li><strong>全流程审计</strong>：任务收尾生成不可篡改证据链与复盘报告。</li>
                </ul>
              </div>
            </div>
          </section>

          <hr />

          <!-- Stage 1 -->
          <section id="stage-1" class="doc-section">
            <h2>1. 阶段一：工作区与需求资产建模 (Workspace & Assets)</h2>
            <div class="workflow-steps">
              <div class="step">
                <div class="step-num">1.1</div>
                <div class="step-content">
                  <h3>多租户工作区与安全边界</h3>
                  <p>工作区 (Workspace) 是资源与权限的最高物理隔离边界。各工作区独立配置团队成员角色 (RBAC)、产品线关联、项目空间绑定以及本地沙箱项目路径，确保不同业务间的数据绝不交叉泄漏。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">1.2</div>
                <div class="step-content">
                  <h3>需求结构化导入与树状拆分 (Split Review)</h3>
                  <p>原生支持 Markdown 需求导入。通过需求工作台将粗粒度需求层级拆分为原子化需求项，并绑定块级验收标准 (Acceptance Criteria)。每个需求项可一键创建关联的工程 Task，并在拆分评审台 (Split Review Workbench) 中开展人工审核。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">1.3</div>
                <div class="step-content">
                  <h3>全链路覆盖度矩阵初检</h3>
                  <p>系统自动扫描需求覆盖度矩阵，若存在未拆分、未关联任务或未完成规格审阅的需求项，即时标红警示，杜绝“无需求编码”与“无验收交付”。</p>
                </div>
              </div>
            </div>
          </section>

          <!-- Stage 2 -->
          <section id="stage-2" class="doc-section">
            <h2>2. 阶段二：契约先行与 API Mock 隔离 (API Mock Workbench)</h2>
            <div class="feature-box mt-4">
              <h3 class="flex items-center gap-2">
                <ServerCog class="w-5 h-5 text-blue-500" />
                虚拟契约网关与多用例推导 (Dynamic Virtual Gateway)
              </h3>
              <p class="mt-2 text-slate-600">
                在编写实际业务代码前，首要建立严密的接口契约边界，彻底解耦前后端开发进度，避免接口未上线导致的项目阻塞。
              </p>
              <ul class="mt-4">
                <li><strong>OpenAPI / Swagger 导入与推导</strong>：一键解析接口文档，自动提取 Endpoint 端点与 Entity 数据实体模型。</li>
                <li><strong>多分支 Mock Case 管理</strong>：为同一接口配置多种业务场景响应（标准成功、参数非法 400、权限越界 403、业务熔断 500、空数据边界）。</li>
                <li><strong>动态代理网关 (Proxy Routing)</strong>：前端工程连接虚拟网关，可按需针对单接口无缝切换 <code>MOCK</code> 仿真数据或 <code>PROXY</code> 真实后端穿透，并支持混沌异常注入联调。</li>
              </ul>
            </div>
          </section>

          <!-- Stage 3 -->
          <section id="stage-3" class="doc-section">
            <h2>3. 阶段三：技能装配与运行时插件 (Skills & Runtime Plugins)</h2>
            <div class="workflow-steps">
              <div class="step">
                <div class="step-num">3.1</div>
                <div class="step-content">
                  <h3>团队目录化技能包 (Skills Hub)</h3>
                  <p>告别零散混乱的单句 Prompt。技能库采用标准化目录包组织（包含 <code>SKILL.md</code> 规范指令、测试脚本与参考样例），支持 Git 工作树集成、行级版本 Diff 对比与专家评分评审，沉淀企业标准开发规范（如 Vue3 Composition 规范、Spring Boot REST 规范）。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">3.2</div>
                <div class="step-content">
                  <h3>任务级运行时临时微调 (Runtime Skill Editor)</h3>
                  <p>在具体任务启动前，开发者可在任务上下文内调整当前生效的技能配置，针对特定业务定制补充指令，不污染全局基准技能库。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">3.3</div>
                <div class="step-content">
                  <h3>可插拔供应商插件适配</h3>
                  <p>底层提供插拔式协议插件支持，大语言模型、语音识别 ASR（Web Speech 直连与桌面离线 Whisper/FunASR）、文本向量 Embedding 服务均可在系统配置中心实现即插即用与在线探针检测。</p>
                </div>
              </div>
            </div>
          </section>

          <!-- Stage 4 -->
          <section id="stage-4" class="doc-section">
            <h2>4. 阶段四：终端协作与人在回路 (Chat, Speech & HITL)</h2>
            <div class="loop-container">
              <div class="loop-box green">
                <Terminal class="w-6 h-6" />
                <span>终端协同与多模态输入</span>
              </div>
              <ArrowRight class="w-6 h-6 text-slate-300" />
              <div class="loop-box blue">
                <Shield class="w-6 h-6" />
                <span>HITL 决策拦截与双向澄清</span>
              </div>
            </div>
            <p class="mt-4 text-slate-600">在任务执行核心阶段，平台提供高透明度的人机协作环境，杜绝黑盒盲跑：</p>
            <ul class="mt-2 space-y-2 text-slate-600">
              <li><strong>终端级会话协同 (Agent Bridge)</strong>：基于 Claude CLI 与 PTY 桥接，实时展示 AI 推理过程、文件操作、工具调用、Token 归因与执行耗时。</li>
              <li><strong>多模态语音输入</strong>：输入框原生集成语音识别，桌面端支持离线高精度转录，解放双手，大幅加速交互反馈。</li>
              <li><strong>人在回路 (HITL - Human-In-The-Loop)</strong>：遇到文件覆盖、核心逻辑改动、多方案选型时自动挂起 (Suspended)，必须人工授权确认后继续推进。</li>
              <li><strong>双向需求澄清 (Clarification)</strong>：AI 识别上下文模糊点后主动发起交互式澄清，问答历史与确认结论自动补全到会话上下文。</li>
              <li><strong>计划文档快照高亮 (Plan Docs Drawer)</strong>：以任务创建时刻为基准快照，侧边抽屉精准高亮本次任务执行期间新增或修改的计划文件，杜绝存量噪音。</li>
            </ul>
          </section>

          <!-- Stage 5 -->
          <section id="stage-5" class="doc-section">
            <h2>5. 阶段五：人机差异分析 (Delta Workbench)</h2>
            <div class="feature-box mt-4">
              <h3 class="flex items-center gap-2">
                <GitBranch class="w-5 h-5 text-indigo-600" />
                代码提议与人工最终修改归因对比 (Human-AI Delta Analysis)
              </h3>
              <p class="mt-2 text-slate-600">
                开发完成并不意味着流程结束。平台自动捕获 AI 提议 (ChangeProposal) 与开发者最终提交代码 (Final Patch) 之间的每一处细微差异：
              </p>
              <div class="stack-grid mt-4">
                <div class="stack-item">
                  <div class="stack-label">修改原因归因分类</div>
                  <div class="stack-value">逻辑缺陷修复 / 边界条件补充 / 架构规范微调 / 视觉样式优化</div>
                </div>
                <div class="stack-item">
                  <div class="stack-label">风险聚合度量看板</div>
                  <div class="stack-value">差异影响面统计 / 幻觉率分析 / 协作效能评分</div>
                </div>
              </div>
              <p class="mt-4 text-slate-500 text-sm">
                通过差异归因，团队能够直观审视“AI 在哪些地方想漏了、人做了哪些关键兜底”，为优化提示词、升级规范和风险把控提供一手客观依据。
              </p>
            </div>
          </section>

          <!-- Stage 6 -->
          <section id="stage-6" class="doc-section">
            <h2>6. 阶段六：任务收尾与追溯审计 (Closeout & Audit)</h2>
            <div class="mcp-grid">
              <div class="mcp-card">
                <h4 class="flex items-center gap-1.5"><Verified class="w-4 h-4 text-sky-600" /> 三步收尾工作流</h4>
                <p><strong>基准对比 (Baseline)</strong>：核验实际改动与规范计划的一致性。<br><strong>专家审查 (Review)</strong>：多人在线复核重点变更。<br><strong>最终摘要 (Summary)</strong>：生成结构化收尾交付结论。</p>
              </div>
              <div class="mcp-card">
                <h4 class="flex items-center gap-1.5"><Eye class="w-4 h-4 text-emerald-600" /> 全链路追溯审计</h4>
                <p>自动在证据注册表中固化执行日志、单测结果与人工审查意见，计算最终覆盖度矩阵，生成具备不可篡改证据链的复盘审计报告。</p>
              </div>
              <div class="mcp-card">
                <h4 class="flex items-center gap-1.5"><LibraryBig class="w-4 h-4 text-purple-600" /> 知识沉淀与晋升</h4>
                <p>将任务中的优秀决策、关键差异归因与修复方案沉淀为<strong>四维知识资产</strong>，支持后续项目一键检索复用。</p>
              </div>
            </div>
          </section>

          <!-- Stage 7: Troubleshooting & Playbook -->
          <section id="troubleshoot" class="doc-section">
            <h2>7. 故障定位与排障剧本闭环 (Incident Diagnosis & Playbook)</h2>
            <p class="lead">
              软件工程不仅包含正向交付，面对突发线上故障与 CI 爆红，TraceForge 提供了结构化的问题定位与经验沉淀闭环：
            </p>
            <div class="workflow-steps">
              <div class="step">
                <div class="step-num">7.1</div>
                <div class="step-content">
                  <h3>异常感知与现场立卷 (Incident Capture)</h3>
                  <p>监控告警或 CI 测试失败触发异常捕获，自动提取报错堆栈、入参 Payload、失败用例及环境快照，在故障案例中心立卷归档并关联基准版本。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">7.2</div>
                <div class="step-content">
                  <h3>剧本检索与 SOP 激活 (Playbook Match)</h3>
                  <p>基于混合检索与 RAG 语义匹配历史相似故障，精准激活标准排障剧本 (Playbook SOP)，自动装配排查清单、诊断命令与根因检验模板。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">7.3</div>
                <div class="step-content">
                  <h3>多维溯源诊断与沙箱修复 (Root Cause & Hotfix)</h3>
                  <p>全链路比对需求规格、API 契约与代码 Delta，定位根因（规格漏项 / 契约破损 / 逻辑盲区），开发者在 Git 隔离沙箱中依 SOP 引导热修补并验证绿灯。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">7.4</div>
                <div class="step-content">
                  <h3>案例报告归档与剧本晋升反哺 (Promotion)</h3>
                  <p>生成不可篡改的故障诊断报告；经专家评审将排障方案晋升为团队通用 Playbook，反哺需求规格与研发规则，彻底阻断同类故障复发。</p>
                </div>
              </div>
            </div>
          </section>

          <!-- Stack -->
          <section id="stack" class="doc-section">
            <h2>8. 系统底座架构与混合检索 (Architecture & Search)</h2>
            <div class="stack-grid">
              <div class="stack-item">
                <div class="stack-label">前端视图与交互层</div>
                <div class="stack-value">Vue 3 + Vite + TypeScript + Pinia + Monaco Editor</div>
              </div>
              <div class="stack-item">
                <div class="stack-label">中枢调度与业务核心</div>
                <div class="stack-value">Python FastAPI + SQLAlchemy + Alembic + PTY Agent Bridge</div>
              </div>
              <div class="stack-item">
                <div class="stack-label">异步作业与运营调度</div>
                <div class="stack-value">Ops 任务队列 + RAG 向量回填 Worker + 计划快照扫描引擎</div>
              </div>
              <div class="stack-item">
                <div class="stack-label">持久化存储与基础设施</div>
                <div class="stack-value">MySQL 8.0 (业务资产) + Redis (快照/锁) + Git Worktree 沙箱</div>
              </div>
            </div>

            <div class="feature-box mt-6">
              <h3 class="flex items-center gap-2"><Cpu class="w-4 h-4 text-blue-600" /> 企业级全局混合检索 (Hybrid RRF Search)</h3>
              <p class="mt-2 text-slate-600 text-sm">
                平台集成自研混合搜索链路：<strong>BM25 词法全文检索 + nested kNN 语义向量检索 + Python RRF 互惠排名融合</strong>。
                两路召回共用短期 PIT，以 <code>1/(60+rank)</code> 等权融合；分页仅读 Redis 隔离快照，保障高并发下的超低延迟与权限隔离；全局支持双击 Shift 极速唤起。
              </p>
            </div>
          </section>

          <!-- Protocol -->
          <section id="protocol" class="doc-section">
            <h2>9. 状态机流转与通信协议 (Protocols)</h2>
            <p class="text-slate-600 mb-4">平台通过 Stdout 结构化封装协议与 WebSocket 广播机制，实现任务状态、日志与协同事件的高保真同步：</p>
            <div class="code-block">
              <div class="code-header">Agent 运行态同步协议标准 [AGENT_STATE_SYNC]</div>
              <pre>
{
  "workspace_id": "ws-778899",
  "task_id": "task-12345",
  "status": "SUSPENDED_CONFIRMATION", // 状态：RUNNING | SUSPENDED_CONFIRMATION | COMPLETED
  "stage": "STAGE_4_COLLABORATION",
  "skill_context": "vue-best-practices@v1.2",
  "hitl_payload": {
    "action_type": "HIGH_RISK_FILE_MODIFICATION",
    "target_files": ["src/router/index.ts"],
    "requires_user_approval": true
  },
  "message": "AI 提议调整全局路由守卫，触发 HITL 人在回路安全拦截，等待开发者授权..."
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
