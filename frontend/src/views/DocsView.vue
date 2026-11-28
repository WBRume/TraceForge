<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { 
  ChevronLeft, Book, Shield, Code, Terminal,
  ArrowRight, Info,
  Settings, ServerCog, Verified, Layers,
  Network, Database, Eye, LibraryBig, GitBranch, Cpu, Stethoscope,
  Laptop
} from '@/components/icons'
import Flowchart from '@/components/Flowchart.vue'

const router = useRouter()
const activeTab = ref('text') // 'text' or 'graph'
const activeSection = ref('intro')

const sections = [
  { id: 'intro', title: '平台定位与四大核心资产', icon: Book },
  { id: 'stage-1', title: '阶段一：工作区、资产白板与原文审阅', icon: Layers },
  { id: 'stage-2', title: '阶段二：契约先行与 API Mock 隔离', icon: ServerCog },
  { id: 'stage-3', title: '阶段三：技能装配与多引擎运行时', icon: Settings },
  { id: 'stage-4', title: '阶段四：终端协同、本地协作与 HITL', icon: Terminal },
  { id: 'stage-5', title: '阶段五：人机差异分析 (Delta Workbench)', icon: GitBranch },
  { id: 'stage-6', title: '阶段六：任务收尾、Webhook 与追溯审计', icon: Verified },
  { id: 'convenience', title: '专题：桌面漫游、代码沙盘与绘图板', icon: Laptop },
  { id: 'troubleshoot', title: '阶段七：故障诊断与排障剧本闭环', icon: Stethoscope },
  { id: 'stack', title: '系统底座架构与混合检索', icon: Shield },
  { id: 'protocol', title: '协作状态机流转与通信协议', icon: Code }
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
              平台以同一套前端能力贯通 <strong>Web、Electron 与 Tauri 2 双桌面端</strong>，统一调度 <strong>Claude Code、OpenCode 与 DSH</strong> 多引擎协作，
              将需求白板、原文审阅、代码沙盘、本地协同、人机差异与执行证据转化为结构化数字资产，
              构建从<strong>需求建模 → 契约隔离 → 多引擎协同 → 差异归因 → 过程收尾 → 知识晋升</strong>的确定性工程闭环。
            </p>

            <div class="info-card">
              <Info class="w-5 h-5 text-blue-500" />
              <div class="info-body">
                <strong>平台核心理念：</strong>代码仅是最终产物，开发过程中的思考、讨论、修改动机、本地交接与合规证据才是团队沉淀的核心资产。AI 不代替开发者，而是作为受控副驾全端协同推进。
              </div>
            </div>

            <div class="grid-2 mt-8">
              <div class="feature-box">
                <h3 class="flex items-center gap-2"><Database class="w-4 h-4 text-sky-600" /> 四大核心资产支柱</h3>
                <ul>
                  <li><strong>需求与文档资产 (Requirements & Docs)</strong>：无限白板关系图谱、树状拆分、DOCX/MD 原文画布版本与验收准则。</li>
                  <li><strong>决策资产 (Decisions)</strong>：架构决策记录 (ADR)、会话关键方案打标、联合修订依据与修改归因。</li>
                  <li><strong>执行证据 (Evidences)</strong>：终端工具流、受控证据附件、多格式产物在线预览、单测报告与审查记录。</li>
                  <li><strong>组织知识 (Knowledge)</strong>：业务知识、框架规范、运维百科与标准化排障剧本 (Playbook)。</li>
                </ul>
              </div>
              <div class="feature-box">
                <h3 class="flex items-center gap-2"><Eye class="w-4 h-4 text-emerald-600" /> 全端协同与可追溯体系</h3>
                <ul>
                  <li><strong>可视与便携体验</strong>：2.5D 多仓代码沙盘、3D 近期任务剧场、桌面多标签漫游、置顶会话浮窗与独立手绘识别绘图板。</li>
                  <li><strong>人在回路 (HITL)</strong>：高危改动挂起拦截、持久化问答回执、运行中追加引导及免登录访客邀请输入。</li>
                  <li><strong>本地与云端融合</strong>：桌面纯 IPC 本地协同、IDE 行级直达、远端基线三方合并与 Delta 差异归因。</li>
                  <li><strong>全流程审计</strong>：三步收尾固化不可篡改证据链，并通过 Webhook 联动公网机器人或本地外设。</li>
                </ul>
              </div>
            </div>
          </section>

          <hr />

          <!-- Stage 1 -->
          <section id="stage-1" class="doc-section">
            <h2>1. 阶段一：工作区、资产白板与原文审阅 (Workspace & Assets)</h2>
            <div class="workflow-steps">
              <div class="step">
                <div class="step-num">1.1</div>
                <div class="step-content">
                  <h3>多租户工作区、多仓绑定与便捷邀请</h3>
                  <p>工作区 (Workspace) 是资源、多仓库绑定与成员权限的物理隔离边界，支持工作区自定义头像（支持图片、矢量与动图无损上传）与高级多维过滤。管理员可通过批量邮箱或<strong>有效期可控的邀请链接 (<code>/join</code>)</strong> 一键邀请成员按预设角色与精细权限加入，同时兼容无代码仓库工作区的轻量协作场景。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">1.2</div>
                <div class="step-content">
                  <h3>需求拆分评审与责任验收闭环</h3>
                  <p>支持直接导入及规范化归档 <code>.docx</code>、<code>.md</code>、<code>.txt</code> 需求文档。在拆分评审台 (Split Review) 开展人工审核与前置依赖绑定，并为需求指定<strong>负责人、复核人与验收人</strong>；支持按全部、可领取、我的、待澄清筛选范围，由负责人提交、复核人检查、验收人通过或驳回。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">1.3</div>
                <div class="step-content">
                  <h3>工作区资产白板与实时关系图谱</h3>
                  <p>支持在个人设置或视图间切换<strong>「列表工作台」与「无限画布白板」</strong>两种显示模式。白板按财年季度分页并增量展开业务分支，实时投影需求层级、前置依赖、需求文档、任务、故障案例与诊断规程的关联关系；内置便签、分组框与在线成员状态感知，所有增删改操作通过 WebSocket 实时同步。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">1.4</div>
                <div class="step-content">
                  <h3>DOCX / Markdown 原文画布审阅与联合修订</h3>
                  <p>需求规格审阅直接渲染<strong>原版 Word 页面或原生 Markdown 画布</strong>，支持跨段与表格单元格精确选区、作者头像栏与同位置讨论弹窗。针对多条已解决讨论，可在后台队列生成<strong>文档级联合修订提案</strong>，对 DOCX 片段与文本进行逐项采纳、原位改写段落及私有草稿发布新版本，完整保留原文档格式。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">1.5</div>
                <div class="step-content">
                  <h3>跨工作区成员工作负载与覆盖度初检</h3>
                  <p>工作区内置一级<strong>成员工作负载视图</strong>，聚合跨工作区的运行中、待回复、待验收、结果检查与逾期槽位并支持成员并发限额设置；系统同步扫描需求覆盖度矩阵，自动警示未拆分、未关联或未完成复核的需求，杜绝无需求编码与盲目交付。</p>
                </div>
              </div>
            </div>
          </section>

          <!-- Stage 2 -->
          <section id="stage-2" class="doc-section">
            <h2>2. 阶段二：契约先行、构图设计与 API Mock 隔离 (API Mock & Diagram)</h2>
            <div class="feature-box mt-4">
              <h3 class="flex items-center gap-2">
                <ServerCog class="w-5 h-5 text-blue-500" />
                虚拟契约网关与多用例推导 (Dynamic Virtual Gateway)
              </h3>
              <p class="mt-2 text-slate-600">
                在编写实际业务代码前，先建立严密的接口契约边界与架构设计图谱，彻底解耦前后端开发进度，避免接口未上线导致的项目阻塞。
              </p>
              <ul class="mt-4">
                <li><strong>OpenAPI / Swagger 导入与队列生成</strong>：一键解析接口文档并提取 Endpoint 端点与 Entity 数据实体；AI 多场景 Mock Case 生成任务并入统一持久化作业队列，通过 MCP 领域工具校验 Mock.js 模板合法性后落库。</li>
                <li><strong>多分支 Mock Case 管理</strong>：为同一接口维护标准成功、参数非法 400、权限越界 403、业务熔断 500 与空数据边界等用例并实时预览响应。</li>
                <li><strong>动态代理网关 (Proxy Routing)</strong>：前端工程连接虚拟网关，可按需针对单接口无缝切换 <code>MOCK</code> 仿真数据或 <code>PROXY</code> 真实后端穿透，并支持混沌异常注入联调。</li>
                <li><strong>独立绘图板前期设计</strong>：桌面端可随时通过全局快捷键（默认 <code>Ctrl+Alt+D</code>）呼出独立绘图板，借助流程/UML/架构图形库、11 类模板及<strong>手绘草图格式化识别</strong>快速绘制时序图、实体关系图与架构草图。</li>
              </ul>
            </div>
          </section>

          <!-- Stage 3 -->
          <section id="stage-3" class="doc-section">
            <h2>3. 阶段三：技能装配、多引擎与运行时插件 (Skills & Multi-Agent)</h2>
            <div class="workflow-steps">
              <div class="step">
                <div class="step-num">3.1</div>
                <div class="step-content">
                  <h3>配置中心技能库与静态分析 (Skills Hub)</h3>
                  <p>技能管理收敛于配置中心 (<code>/config/skills</code>)，采用标准化目录包组织（包含 <code>SKILL.md</code>、参考脚本与测试用例），支持 GitHub 仓库导入、行级版本 Diff 对比与专家评审。技能静态风险分析由统一作业队列驱动并通过 MCP 强类型领域工具输出可定位证据。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">3.2</div>
                <div class="step-content">
                  <h3>任务级运行时微调与调用追踪 (Runtime Skill Editor)</h3>
                  <p>在任务上下文中可通过<strong>可调宽度的运行时 Skills 抽屉</strong>临时微调生效指令，支持二进制只读保护与文件树快速编辑，不污染全局基准技能库，并实时统计技能调用次数与运行证据。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">3.3</div>
                <div class="step-content">
                  <h3>多 Agent 引擎注册表与可插拔插件适配</h3>
                  <p>底层通过统一 Agent 注册表支持 <strong>Claude Code CLI、OpenCode Server 与 DSH (DeepSeek Harness)</strong>，可按工作区独立覆写默认引擎并验证服务版本与会话代次；语音 ASR 支持百炼流式 WebSocket、OpenAI 兼容 HTTP 与桌面端离线 <strong>SenseVoice-Small INT8</strong>；Embedding 向量协议支持可插拔扩展与在线探针检测。</p>
                </div>
              </div>
            </div>
          </section>

          <!-- Stage 4 -->
          <section id="stage-4" class="doc-section">
            <h2>4. 阶段四：终端协同、本地协作与人在回路 (Chat, Local Collab & HITL)</h2>
            <div class="loop-container">
              <div class="loop-box green">
                <Terminal class="w-6 h-6" />
                <span>多引擎富交互与本地协同</span>
              </div>
              <ArrowRight class="w-6 h-6 text-slate-300" />
              <div class="loop-box blue">
                <Shield class="w-6 h-6" />
                <span>HITL 持久化回执与分享协作</span>
              </div>
            </div>
            <p class="mt-4 text-slate-600">在任务执行核心阶段，平台在云端与桌面端提供高透明度、高便携性的人机协作环境，杜绝黑盒盲跑：</p>
            <ul class="mt-2 space-y-2 text-slate-600">
              <li><strong>引导式任务创建与多仓并行准备</strong>：支持按仓库组勾选多仓库、批量设置分支并并行准备 Git Worktree；任务侧栏支持关键词检索、我关注的/提到我的高级筛选，并按任务自动保存未发送草稿。</li>
              <li><strong>多模态、图片附件与上下文批注</strong>：输入框支持多张图片附件（贯通发送、撤销恢复与运行引导）及在线/离线语音输入；支持<strong>直接选中历史消息或代码 Diff 的指定行区间添加批注</strong>，自动携带文件、行号与修改意见随消息发送。</li>
              <li><strong>运行中追加引导与富终端体验</strong>：Agent 执行期间可随时发送<strong>运行中引导 (Steering)</strong> 纠偏；支持平台卡片与悬浮 CLI 终端视图切换、Markdown 渲染、可收起思考过程胶囊、Token 来源归因及增量<strong>计划文档快照抽屉</strong>。</li>
              <li><strong>持久化 HITL 确认与免登录会话分享</strong>：高风险改动与歧义问题触发挂起 (<code>AWAITING_INPUT</code>)，确认回复采用持久化回执保障不丢不乱；支持生成<strong>只读分享或「邀请输入」链接 (<code>/share/session</code>)</strong>，访客提交的建议可由发起人编辑、追加或替换采纳到草稿。</li>
            </ul>

            <div class="feature-box mt-6">
              <h3 class="flex items-center gap-2">
                <Laptop class="w-5 h-5 text-sky-600" />
                桌面本地协同、基线三方合并与产物在线预览导出
              </h3>
              <p class="mt-2 text-slate-600">
                Electron 与 Tauri 2 桌面客户端内置 Node 本地资源运行时，本地协同通过纯 IPC 通道执行、不占用监听端口：
              </p>
              <ul class="mt-3">
                <li><strong>本地协同与 IDE 直达</strong>：服务端跑 AI 任务的同时，开发者可在本机编辑器改代码；本地文件变更自动驱动界面刷新并按对话轮次保留备份；Diff 工具栏与行号旁提供一键跳转 <strong>VS Code、IntelliJ IDEA 或 PyCharm</strong> 精确定位。</li>
                <li><strong>远端基线三方合并与 Agent 适配</strong>：支持一键发现绑定分支新提交并做独立三方合并，冲突支持人工解决或交由 Agent 沿用原会话自动适配后应用。</li>
                <li><strong>产物筛选、在线预览与流式导出</strong>：任务产物支持「全部 / 报告 / 代码」筛选，按扩展名懒加载在线预览 <strong>PDF、Word、Excel、PPT、HTML、图片与 Diff</strong>，并支持流式打包 ZIP 导出（无仓库任务直接展示工作区文件差异）。</li>
              </ul>
            </div>
          </section>

          <!-- Stage 5 -->
          <section id="stage-5" class="doc-section">
            <h2>5. 阶段五：人机差异分析 (Delta Workbench)</h2>
            <div class="feature-box mt-4">
              <h3 class="flex items-center gap-2">
                <GitBranch class="w-5 h-5 text-indigo-600" />
                代码提议、本地交接与人工终稿归因对比 (Human-AI Delta Analysis)
              </h3>
              <p class="mt-2 text-slate-600">
                开发完成并不意味着流程结束。平台自动捕获 AI 提议 (ChangeProposal)、桌面本地协同交接改动与开发者最终提交代码 (Final Patch) 之间的每一处细微差异，支持按对话轮次或累计范围审阅：
              </p>
              <div class="stack-grid mt-4">
                <div class="stack-item">
                  <div class="stack-label">修改原因归因分类</div>
                  <div class="stack-value">逻辑缺陷修复 / 边界条件补充 / 架构规范微调 / 视觉样式优化</div>
                </div>
                <div class="stack-item">
                  <div class="stack-label">风险聚合度量看板</div>
                  <div class="stack-value">差异影响面统计 / 幻觉率分析 / 本地交接追溯 / 协作效能评分</div>
                </div>
              </div>
              <p class="mt-4 text-slate-500 text-sm">
                通过差异归因，团队能够直观审视“AI 在哪些地方想漏了、人做了哪些关键兜底”，为优化提示词、升级 Skills 规范和风险把控提供一手客观依据。
              </p>
            </div>
          </section>

          <!-- Stage 6 -->
          <section id="stage-6" class="doc-section">
            <h2>6. 阶段六：任务收尾、Webhook 联动与追溯审计 (Closeout & Audit)</h2>
            <div class="mcp-grid">
              <div class="mcp-card">
                <h4 class="flex items-center gap-1.5"><Verified class="w-4 h-4 text-sky-600" /> 三步收尾与状态校验</h4>
                <p>收束前自动确认 Agent 空闲与协同主机断开：<br><strong>基准对比 (Baseline)</strong> → <strong>专家审查 (Review)</strong> → <strong>最终摘要 (Summary)</strong>。</p>
              </div>
              <div class="mcp-card">
                <h4 class="flex items-center gap-1.5"><Eye class="w-4 h-4 text-emerald-600" /> 受控证据与全链路审计</h4>
                <p>证据附件在任务内受控上传下载并独立持久化，结合单测与审查意见计算覆盖度矩阵，生成不可篡改复盘报告。</p>
              </div>
              <div class="mcp-card">
                <h4 class="flex items-center gap-1.5"><LibraryBig class="w-4 h-4 text-purple-600" /> 知识沉淀与晋升</h4>
                <p>将优秀技术决策、关键差异归因与修复方案沉淀为知识资产，在<strong>知识中心 (<code>/knowledge</code>)</strong> 支持跨项目检索复用。</p>
              </div>
            </div>

            <div class="feature-box mt-6">
              <h3 class="flex items-center gap-2"><Network class="w-4 h-4 text-blue-600" /> 个人与工作区 Webhook 双通道实时触达</h3>
              <p class="mt-2 text-slate-600 text-sm">
                平台提供站内通知与站外 Webhook 广播：支持<strong>公网 IM/告警机器人</strong>（服务端直接出站，离线可靠）及<strong>桌面客户端本地回环代理</strong>（投递至 <code>127.0.0.1</code> 触发本地脚本或桌宠）。个人 Webhook 支持订阅指定工作区并开启「任务创建者通知」，覆盖卡点等待 (HITL)、长时完成、异常中断与手动标定等全生命周期事件。
              </p>
            </div>
          </section>

          <!-- Convenience Spotlight -->
          <section id="convenience" class="doc-section">
            <h2>专题：桌面便捷工作台、2.5D 代码沙盘与绘图板 (Workspace & Desktop UX)</h2>
            <p class="lead">
              围绕高频研发场景，TraceForge 桌面端与工作区看板提供了一系列开箱即用的可视化与便携提效能力：
            </p>
            <div class="workflow-steps">
              <div class="step">
                <div class="step-num">A</div>
                <div class="step-content">
                  <h3>2.5D 多仓代码沙盘与无仓近期任务剧场</h3>
                  <p>工作区看板内置 <strong>2.5D 等距与俯视代码沙盘</strong>，按真实 Git 提交与源码目录统计模块体量、近期活跃热力与进行中任务影响面；支持 14/30/60 天时间窗口、单日/累计提交回放及成员协作焦点钻取。无代码仓库工作区自动进入 <strong>3D 近期任务剧场</strong>，以透视卡片轮播近期活跃任务并直达会话。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">B</div>
                <div class="step-content">
                  <h3>工作区多标签页与多窗口漫游恢复</h3>
                  <p>桌面标题栏集成工作区选择器、配置/运维/知识中心切换器与多标签页管理，支持 <code>Ctrl+T</code> 新建、<code>Ctrl+W</code> 关闭、<code>Ctrl+Tab</code> 切换及 <code>Ctrl</code>/中键点击链接新开标签；支持拖拽排序、拖出窗口拆分为独立窗口或拖回标签栏合并，并在重启客户端后按账号与服务器完整恢复窗口位置与标签页布局。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">C</div>
                <div class="step-content">
                  <h3>可拖出常驻桌面的置顶会话浮窗</h3>
                  <p>任意置顶或关注的会话监控面板均可直接从标题栏拖出客户端，化身为<strong>无边框置顶桌面浮窗</strong>，在编码或会议期间随时跟踪进度、实时输出与图片附件；关闭或拖回客户端内即平滑归还原位。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">D</div>
                <div class="step-content">
                  <h3>全局快捷键独立绘图板与双击 Shift 秒搜</h3>
                  <p>无论焦点在哪个应用，按下全局快捷键（默认 <code>Ctrl+Alt+D</code>，可在用户设置自定义）即可呼出独立绘图板：包含流程/UML/架构/通用四大图形库、11 类开箱模板、自动排版以及<strong>手绘格式化识别 (<code>P</code>)</strong>（手绘方框、椭圆、菱形、三角形与箭头自动转为标准图元），支持本地草稿实时保存及 <code>.tfdiagram</code> / PNG / SVG 导出。此外，在平台任意位置<strong>双击 Shift</strong> 即可秒级唤起全局混合搜索。</p>
                </div>
              </div>
            </div>
          </section>

          <!-- Stage 7: Troubleshooting & Playbook -->
          <section id="troubleshoot" class="doc-section">
            <h2>7. 阶段七：故障定位与排障剧本闭环 (Incident Diagnosis & Playbook)</h2>
            <p class="lead">
              软件工程不仅包含正向交付，面对突发线上故障与 CI 爆红，TraceForge 提供了结构化的问题定位与经验沉淀闭环：
            </p>
            <div class="workflow-steps">
              <div class="step">
                <div class="step-num">7.1</div>
                <div class="step-content">
                  <h3>异常感知与现场立卷 (Incident Capture)</h3>
                  <p>监控告警或 CI 测试失败触发异常捕获，自动提取报错堆栈、入参 Payload、失败用例及环境快照，在案例中心立卷归档并关联基准版本。专用排查场景还可通过 <code>dsh-playbook</code> 守卫插件限制工具执行边界。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">7.2</div>
                <div class="step-content">
                  <h3>剧本检索与 SOP 激活 (Playbook Match)</h3>
                  <p>基于 PostgreSQL 18 混合检索（或可选 Elasticsearch）精准匹配历史相似故障，激活标准排障剧本 (Playbook SOP)，自动装配排查清单、诊断命令与逐条根因检验模板。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">7.3</div>
                <div class="step-content">
                  <h3>分阶段验证与结构化行动板 (Root Cause & Action Board)</h3>
                  <p>支持逐阶段人工确认或自动推进假说验证；结果卡片以结构化行动板呈现逐条证据链与修复建议，协助开发者在 Git 隔离沙箱内定位规格漏项、契约破损或代码盲区并热修补。</p>
                </div>
              </div>
              <div class="step">
                <div class="step-num">7.4</div>
                <div class="step-content">
                  <h3>后台并行提炼规程与案例晋升反哺 (Promotion)</h3>
                  <p>生成按诊断结构渲染的故障报告；专家发起<strong>案例晋升</strong>后，提炼任务进入统一后台作业队列（支持浮窗并行跟踪、MCP 强类型提交及持久草案保留/放弃），经审核晋升为团队标准 Playbook 并沉淀至知识中心，阻断同类故障复发。</p>
                </div>
              </div>
            </div>
          </section>

          <!-- Stack -->
          <section id="stack" class="doc-section">
            <h2>8. 系统底座架构、功能中心与混合检索 (Architecture & Search)</h2>
            <div class="stack-grid">
              <div class="stack-item">
                <div class="stack-label">前端视图与双桌面端</div>
                <div class="stack-value">Vue 3.5 + Vite + TypeScript + Pinia + Monaco + Electron / Tauri 2</div>
              </div>
              <div class="stack-item">
                <div class="stack-label">中枢调度与跨端契约</div>
                <div class="stack-value">Python FastAPI + SQLAlchemy + Alembic + 强类型协议 (MCP 2026)</div>
              </div>
              <div class="stack-item">
                <div class="stack-label">统一作业与本地运行时</div>
                <div class="stack-value">sdd_ai_jobs 持久化队列 + RAG 回填 Worker + 桌面内置 Node 资源服务</div>
              </div>
              <div class="stack-item">
                <div class="stack-label">持久化存储与基础设施</div>
                <div class="stack-value">PostgreSQL 18 (业务/全文/向量) + Redis (锁/快照) + Git Worktree (+ 可选 ES 9.x)</div>
              </div>
            </div>

            <div class="feature-box mt-6">
              <h3 class="flex items-center gap-2"><Cpu class="w-4 h-4 text-blue-600" /> PostgreSQL 18 混合检索与三大功能中心</h3>
              <p class="mt-2 text-slate-600 text-sm">
                全局搜索默认基于 <strong>PostgreSQL 18（<code>pg_jieba</code> 中文分词 + <code>pgvector</code> 1024 维 HNSW 向量 + RRF 等权融合）</strong>，覆盖任务、消息、案例和诊断规程，支持语料分区检索、纯全文模式与可选 Elasticsearch 9.x 扩展；分页仅读 Redis 隔离快照，任意页面<strong>双击 Shift</strong> 即可唤起。
                平台应用矩阵清晰划分为<strong>配置中心 (<code>/config</code>)</strong>（产品/项目/仓库/Skills/系统配置）、<strong>运维中心 (<code>/ops</code>)</strong>（队列运维与案例同步队列）与<strong>知识中心 (<code>/knowledge</code>)</strong>，并独立拆分了「用户设置」与「工作区设置」。
              </p>
            </div>
          </section>

          <!-- Protocol -->
          <section id="protocol" class="doc-section">
            <h2>9. 协作状态机流转与强类型通信协议 (Protocols)</h2>
            <p class="text-slate-600 mb-4">
              平台全面采用协作状态机驱动（单点写入 + <code>status_seq</code> CAS 串行投递：<code>PROVISIONING → INITIALIZED → RUNNING ⇄ ROUND_COMPLETED / AWAITING_INPUT / INTERRUPTED → COMPLETED / FAILED</code>）。
              前后端通过基于 JSON Schema + Ajv 校验的 <code>RoomEnvelope v2</code> 序列化事件流与 <code>MCP 2026-07-28</code> 领域工具协议进行高保真协同：
            </p>
            <div class="code-block">
              <div class="code-header">RoomEnvelope v2 与协作状态同步协议标准 [contract_version: 2]</div>
              <pre>
{
  "contract_version": 2,
  "type": "event",
  "room": "task:task-12345",
  "epoch": "gen-03",
  "sequence": 42,
  "event_id": "evt-9f8e7d6c",
  "event_type": "status",
  "aggregate_id": "task-12345",
  "aggregate_version": 18,
  "payload": {
    "task_id": "task-12345",
    "status": "AWAITING_INPUT",
    "status_seq": 18,
    "agent_backend": "opencode",
    "mcp_protocol": "2026-07-28",
    "hitl_payload": {
      "action_type": "CONFIRMATION_REQUIRED",
      "target_files": ["src/router/index.ts"],
      "requires_user_approval": true
    },
    "message": "Agent 请求确认关键路由变更并提交持久化回执，等待开发者授权..."
  }
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
