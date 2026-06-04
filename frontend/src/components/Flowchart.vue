<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  User,
  Bot,
  Settings,
  Repeat,
  Plug,
  Pencil,
  Search,
  CheckCircle,
  GitBranch,
  FilePlus,
  MessageCircle,
  Database,
  ListChecks,
  PlugZap,
  Monitor,
  Archive,
  GitPullRequest,
  Target,
  Eye,
  ListOrdered,
  Rocket,
  AlertCircle,
  Bug,
  Video,
  Wrench,
  Lightbulb,
  Brain,
  ClipboardList,
  GitMerge
} from 'lucide-vue-next'

const canvas = ref<HTMLElement | null>(null)

onMounted(() => {
  if (!canvas.value) return
  
  let isDragging = false
  let startX: number, startY: number, scrollLeft: number, scrollTop: number

  // Initial center position
  canvas.value.scrollLeft = (canvas.value.scrollWidth - canvas.value.clientWidth) / 2

  canvas.value.addEventListener('mousedown', (e: MouseEvent) => {
    isDragging = true
    if (canvas.value) {
      canvas.value.style.cursor = 'grabbing'
      startX = e.pageX - canvas.value.offsetLeft
      startY = e.pageY - canvas.value.offsetTop
      scrollLeft = canvas.value.scrollLeft
      scrollTop = canvas.value.scrollTop
    }
  })

  canvas.value.addEventListener('mouseleave', () => {
    isDragging = false
    if (canvas.value) canvas.value.style.cursor = 'grab'
  })

  canvas.value.addEventListener('mouseup', () => {
    isDragging = false
    if (canvas.value) canvas.value.style.cursor = 'grab'
  })

  canvas.value.addEventListener('mousemove', (e: MouseEvent) => {
    if (!isDragging || !canvas.value) return
    e.preventDefault()
    const x = e.pageX - canvas.value.offsetLeft
    const y = e.pageY - canvas.value.offsetTop
    const walkX = (x - startX) * 1.5
    const walkY = (y - startY) * 1.5
    canvas.value.scrollLeft = scrollLeft - walkX
    canvas.value.scrollTop = scrollTop - walkY
  })
})
</script>

<template>
  <div class="flowchart-container">
    <!-- 图例区 -->
    <div class="legend-group">
      <div class="legend-item human"><User class="w-4 h-4" /> 1. 人工操作</div>
      <div class="legend-item ai"><Bot class="w-4 h-4" /> 2. AI 自治/协作</div>
      <div class="legend-item system"><Settings class="w-4 h-4" /> 3. 系统底层动作</div>
      <div class="legend-item decision"><Repeat class="w-4 h-4" /> 4. 关键决策循环</div>
      <div class="legend-item external"><Plug class="w-4 h-4" /> 5. 外部系统接入</div>
    </div>

    <!-- 拖拽画布区域 -->
    <main class="canvas no-scrollbar" ref="canvas">
      <div class="flow-wrapper">
        <!-- ================= 全局巨型循环 6 -> 1 (右侧) ================= -->
        <div class="loop-path right-loop path-ai" style="top: 60px; bottom: 260px; right: -120px; width: 180px;">
          <div class="loop-arrow-up-left"></div>
          <div class="loop-label ai glow-ai" style="top: 50%; right: -24px; transform: translate(100%, -50%);">
            <Lightbulb class="w-5 h-5 text-yellow-500" /> AI 提炼经验，反哺更新全局规则库
          </div>
        </div>

        <!-- ================= 嵌套循环 5 -> 2 (左侧) ================= -->
        <div class="loop-path left-loop path-decision" style="top: 480px; bottom: 480px; left: -80px; width: 120px;">
          <div class="loop-arrow-up-right"></div>
          <div class="loop-label decision" style="top: 50%; left: -16px; transform: translate(-100%, -50%);">
            <GitMerge class="w-4 h-4 text-orange-500" /> 作为新需求，重塑闭环
          </div>
        </div>

        <!-- ================= 阶段 1 ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 1: Skill 管理</div>
          
          <div class="loop-path local-left path-decision" style="top: 30px; bottom: 30px; left: -40px; width: 60px;">
            <div class="loop-arrow-up-right"></div>
            <div class="loop-label decision" style="top: 50%; left: -12px; transform: translate(-100%, -50%);">打回重写</div>
          </div>

          <div class="node-card node-human">
            <div class="node-header txt-human"><Pencil class="w-5 h-5" /> 用户：编写 Markdown</div>
            <div class="node-desc">定制规则规范</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>
          
          <div class="node-card node-decision">
            <div class="node-header txt-decision"><Search class="w-5 h-5" /> 专家：评审 Skill 质量</div>
            <div class="node-subtext">控制 AI 行为的输入源头审查</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys" style="margin-bottom:0;"><CheckCircle class="w-5 h-5" /> 系统：状态变更为已发布</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 2 ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 2: SDD 需求规格与规划</div>

          <div class="node-card node-ext external-floating" style="top: 8px; left: -300px; width: 192px;">
            <div class="node-header txt-ext" style="font-size: 0.75rem;"><GitBranch class="w-4 h-4" /> Gitlab / 知识库</div>
            <div class="node-desc" style="font-size: 10px;">通过 RAG 投喂历史项目上下文</div>
          </div>
          <div class="loop-path path-ext" style="top: 32px; left: -100px; width: 100px; z-index: 10;">
            <div class="loop-arrow-up-right ext-connector"></div>
          </div>

          <div class="loop-path local-left path-decision" style="top: 160px; bottom: 30px; left: -40px; width: 60px;">
            <div class="loop-arrow-up-right"></div>
            <div class="loop-label decision" style="top: 50%; left: -12px; transform: translate(-100%, -50%);">需求不符</div>
          </div>

          <div class="node-card node-human">
            <div class="node-header txt-human"><FilePlus class="w-5 h-5" /> 用户：新建 Task 关联 Skill</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai bg-ai-half glow-ai">
            <div class="node-header txt-ai"><MessageCircle class="w-5 h-5" /> AI & 用户：需求评审、讨论与提案落地</div>
            <div class="node-desc">解析原始 Markdown 需求，通过人机对话消除歧义并冻结业务目标</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai relative">
            <div class="node-header txt-ai"><Brain class="w-5 h-5" /> AI：Brainstorming (基于提案进行架构比选)</div>
            <div class="node-desc">基于上一步确定的提案，探索多种实现路径与组件拆分方案</div>
            <div class="absolute -right-4 top-1/2 -translate-y-1/2 flex flex-col gap-1">
              <span class="inline-badge bg-green-100 text-green-700 text-[10px] shadow-sm">方案 A (推荐)</span>
              <span class="inline-badge bg-slate-100 text-slate-500 text-[10px] scale-90 opacity-70">方案 B</span>
              <span class="inline-badge bg-slate-100 text-slate-500 text-[10px] scale-90 opacity-70">方案 C</span>
            </div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai bg-ai-half">
            <div class="node-header txt-ai"><ClipboardList class="w-5 h-5" /> AI：Writing Plans (含 OpenAPI 契约自动推导)</div>
            <div class="node-desc">书写原子化工程计划，自动推导并嵌出缺失的 Swagger / 实体块</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-decision">
            <div class="node-header txt-decision"><ListChecks class="w-5 h-5" /> 用户：人工确认文档与工程计划</div>
            <div class="node-subtext">通过后锁定文档进入执行阶段</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 3 ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 3: Subagent-Driven Development</div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><Settings class="w-5 h-5" /> 系统：初始化隔离沙箱与 Skill 矩阵</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai bg-ai-half glow-ai">
            <div class="node-header txt-ai"><Bot class="w-5 h-5" /> AI (Subagent)：领用 Plan 任务</div>
            <div class="node-desc">依据工程计划拆分，自动启用子代理并行执行任务</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai">
            <div class="node-header txt-ai"><ListOrdered class="w-5 h-5" /> AI：原子代码实现与 API Mock 补全</div>
            <div class="node-desc">生成的界面、逻辑与 Mock 数据均严格遵循文档契约</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><Archive class="w-5 h-5" /> 系统：生成基准代码快照 (Git Commit)</div>
            <div class="node-subtext">为 TDD 循环准备稳定的初始状态</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 4 ================= -->
        <div class="phase-group">
          <div class="phase-badge blue">Phase 4: TDD 并行开发</div>

          <div class="node-card node-sys bg-sys-third">
            <div class="node-header txt-sys"><PlugZap class="w-5 h-5" /> 系统：注入唯一 Mock Base URL</div>
            <div class="node-subtext">统一稳定的全局上下文基座</div>
          </div>

          <!-- 分叉结构 -->
          <div class="branch-fork">
            <div class="branch-v-top"></div>
            <div class="branch-h"></div>
            <div class="branch-v-left"><div class="flow-arrow"></div></div>
            <div class="branch-v-right"><div class="flow-arrow"></div></div>
          </div>

          <!-- 左右分支并联节点 -->
          <div class="parallel-nodes">
            <!-- 左侧：前端 UI -->
            <div class="node-card node-ai bg-white relative">
              <div class="node-header txt-blue branch-header"><Monitor class="w-5 h-5 text-blue-600" /> UI 前端工程流</div>
              <div class="node-desc" style="color: #334155;">🤖 独立对接 Mock，不被阻塞</div>
              <div class="node-subtext">自动编写页面组件、状态管理与交互代码</div>
            </div>

            <!-- 右侧：后端 TDD -->
            <div class="node-card node-ai bg-white relative">
              <!-- TDD 内部红绿循环 -->
              <div class="loop-path local-right path-decision" style="top: 40px; bottom: 30px; right: -24px; width: 32px;">
                <div class="loop-arrow-down-left"></div>
                <div class="loop-label decision side-loop">红绿重写</div>
              </div>

              <div class="node-header txt-green branch-header"><Database class="w-5 h-5 text-green-600" /> 业务后端工程流 (TDD)</div>
              <div class="node-desc" style="color: #334155;">🤖 读取实体生成 POJO 模型</div>
              <div class="node-desc" style="color: #334155;">🤖 Mock 用例转为 Controller 单测</div>
              <div class="node-subtext">底层 Service 实现直至<strong>单测绿灯通过</strong></div>
            </div>
          </div>

          <!-- 汇聚结构 -->
          <div class="branch-merge">
            <div class="branch-v-left-top"></div>
            <div class="branch-v-right-top"></div>
            <div class="branch-h-bottom"></div>
            <div class="branch-v-bottom"><div class="flow-arrow"></div></div>
          </div>

          <!-- Gateway -->
          <div class="node-card node-sys gateway">
            <div class="gateway-content">
              <div class="gateway-icon">
                <Plug class="w-6 h-6 text-blue-300" />
              </div>
              <div>
                <div class="gateway-title">系统：动态代理网关联调</div>
                <div class="gateway-sub">MOCK/PROXY 按需混合路由<br>混沌工程前端异常注入测试</div>
              </div>
            </div>
          </div>

          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <!-- HITL -->
          <div class="node-card node-decision">
            <div class="node-header txt-decision"><PlugZap class="w-5 h-5" /> 用户：最终人机协同验收 (HITL)</div>
            <div class="node-subtext">审阅变更 Diff，确认代码合并至 master</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 5 ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 5: 资产管理</div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><Archive class="w-5 h-5" /> 系统：代码与契约结转为数字资产归档</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="loop-path local-left path-decision" style="top: 110px; bottom: 110px; left: -40px; width: 60px;">
            <div class="loop-arrow-up-right"></div>
            <div class="loop-label decision" style="top: 50%; left: -12px; transform: translate(-100%, -50%);">影响过大</div>
          </div>

          <div class="node-card node-human">
            <div class="node-header txt-human"><GitPullRequest class="w-5 h-5" /> 产品/架构师：发起规范或需求变更</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai bg-red-third">
            <div class="node-header text-red-600"><Target class="w-5 h-5" /> AI：跨库执行「爆炸半径」影响面计算</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-decision">
            <div class="node-header txt-decision"><Eye class="w-5 h-5" /> 用户：可视化审阅受影响的页面与单测</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><ListOrdered class="w-5 h-5" /> 系统：生成并确认变更拆分计划</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 6 ================= -->
        <div class="phase-group" style="margin-bottom: 0;">
          <div class="phase-badge">Phase 6: CI/CD 反哺</div>

          <div class="external-stack">
            <div class="node-card node-ext p-3 w-full">
              <div class="node-header txt-ext text-[0.75rem] mb-1"><Rocket class="w-4 h-4" /> 自动化流水线</div>
              <div class="node-desc text-[0.625rem]">以 Mock 契约跑回归测试</div>
            </div>
            <div class="node-card node-ext p-3 w-full">
              <div class="node-header txt-ext text-[0.75rem] mb-1"><AlertCircle class="w-4 h-4" /> 线上监控告警</div>
              <div class="node-desc text-[0.625rem]">捕获 Bug 并推送错误堆栈</div>
            </div>
          </div>
          <div class="loop-path path-error" style="top: 60px; left: -100px; width: 100px; z-index: 10;">
            <div class="loop-arrow-up-right ext-connector"></div>
          </div>

          <div class="loop-path local-left path-decision" style="top: 30px; bottom: 30px; left: -40px; width: 60px;">
            <div class="loop-arrow-up-right"></div>
            <div class="loop-label decision" style="top: 50%; left: -12px; transform: translate(-100%, -50%);">修复后重测</div>
          </div>

          <div class="node-card node-decision border-red-400 bg-red-white">
            <div class="node-header text-red-700"><Bug class="w-5 h-5 text-red-500 animate-pulse" /> 异常阻断：CI 爆红 / 线上抛出报错</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai">
            <div class="node-header txt-ai"><Video class="w-5 h-5" /> AI：流水线可视化诊断与录像回放</div>
            <div class="node-subtext">溯源缺陷属需求设计、契约漏批还是编码幻觉</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-human">
            <div class="node-header txt-human"><Wrench class="w-5 h-5" /> 用户/AI：溯源修复缺陷与完善单测</div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.flowchart-container {
  display: flex;
  flex-direction: column;
  height: 100%; /* Fill parent container in Graphical mode */
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  overflow: hidden;
  position: relative;
  /* Net grid background */
  background-image: 
    linear-gradient(to right, #e2e8f0 1px, transparent 1px),
    linear-gradient(to bottom, #e2e8f0 1px, transparent 1px);
  background-size: 32px 32px;
}

.no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
.no-scrollbar::-webkit-scrollbar { display: none; }

.legend-group {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.5rem;
  padding: 1rem;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(226, 232, 240, 0.8);
  z-index: 50;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  border-radius: 0.5rem;
  border: 1px solid transparent;
  font-size: 0.75rem;
  font-weight: 700;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}

.legend-item.human { background: #eff6ff; border-color: #93c5fd; color: #1e40af; }
.legend-item.ai { background: #faf5ff; border-color: #d8b4fe; color: #6b21a8; }
.legend-item.system { background: #f0fdf4; border-color: #86efac; color: #166534; }
.legend-item.decision { background: #fff7ed; border-color: #fdba74; color: #9a3412; }
.legend-item.external { background: #f8fafc; border-color: #94a3b8; color: #334155; border-style: dashed; }

.canvas { 
  flex: 1; 
  width: 100%; 
  position: relative; 
  overflow: auto; 
  cursor: grab; 
}
.canvas:active { cursor: grabbing; }

.flow-wrapper { 
  width: 800px; 
  margin: 0 auto; 
  position: relative; 
  padding-top: 4rem; 
  padding-bottom: 8rem; 
  display: flex; 
  flex-direction: column; 
  align-items: center; 
}

/* Nodes */
.phase-group { 
  width: 100%; 
  position: relative; 
  display: flex; 
  flex-direction: column; 
  align-items: center; 
  margin-bottom: 2rem; 
}

.phase-badge {
    margin-bottom: 24px;
    z-index: 30;
    background-color: #1e293b; color: #fff;
    font-weight: 700; font-size: 0.75rem; padding: 0.375rem 0.75rem;
    border-radius: 9999px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
}
.phase-badge.blue { background-color: #3b82f6; }

.node-card {
    width: 340px; background: white; border-radius: 16px; padding: 16px 20px;
    position: relative; z-index: 20; border: 2px solid transparent;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05), 0 10px 15px -3px rgba(0,0,0,0.02);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.node-card:hover { transform: translateY(-4px); box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1); }

.node-header { display: flex; align-items: center; gap: 0.5rem; font-weight: 700; font-size: 1rem; margin-bottom: 0.5rem; }
.node-desc { font-size: 0.875rem; color: #475569; font-weight: 500; }
.node-subtext { font-size: 0.75rem; color: #64748b; margin-top: 0.25rem; }

.node-human { border-color: #93c5fd; }
.node-ai { border-color: #d8b4fe; }
.node-sys { border-color: #86efac; }
.node-decision { border-color: #fdba74; }
.node-ext { border-color: #94a3b8; border-style: dashed; background-color: #f8fafc; }

.txt-human { color: #1e40af; }
.txt-ai { color: #6b21a8; }
.txt-sys { color: #166534; }
.txt-decision { color: #9a3412; }
.txt-ext { color: #334155; }
.txt-blue { color: #3b82f6; }
.txt-green { color: #10b981; }

.inline-badge { font-size: 0.75rem; padding: 2px 4px; border-radius: 4px; font-weight: 500; }
.inline-badge.human { background-color: #eff6ff; color: #1e40af; }

.bg-ai-half { background-color: rgba(250, 245, 255, 0.5); }
.glow-ai { box-shadow: 0 0 20px -5px rgba(168,85,247,0.4); }
.bg-sys-third { background-color: rgba(240, 253, 244, 0.3); }
.bg-red-third { background-color: rgba(254, 242, 242, 0.3); }
.bg-red-white { background-color: rgba(254, 242, 242, 0.5); }

/* Lines */
.flow-line { width: 2px; background-color: #cbd5e1; margin: 0 auto; z-index: 10; position: relative; }
.flow-arrow {
    width: 12px; height: 12px;
    border-right: 2px solid #cbd5e1; border-bottom: 2px solid #cbd5e1;
    transform: rotate(45deg); margin: -7px auto 0 auto;
    z-index: 10; position: relative; background: #fff;
}

.separator { height: 64px; width: 4px; background-color: #94a3b8; }
.separator-arrow { width: 14px; height: 14px; border-color: #94a3b8; margin-top: -8px; }

/* Loops */
.loop-path { position: absolute; border-style: dashed; border-width: 2px; z-index: 0; pointer-events: none; }
.right-loop { border-left: none; border-radius: 0 3rem 3rem 0; font-size: 0.75rem; }
.left-loop { border-right: none; border-radius: 3rem 0 0 3rem; }
.local-left { border-right: none; border-radius: 1rem 0 0 1rem; }
.local-right { border-left: none; border-radius: 0 0.75rem 0.75rem 0; }

.path-ai { border-color: #c084fc; }
.path-decision { border-color: #fb923c; }
.path-ext { border-color: #94a3b8; border-bottom: none; border-left: none; border-right: none; }
.path-error { border-color: #f87171; border-bottom: none; border-left: none; border-right: none; }

.loop-arrow-up-left, .loop-arrow-up-right, .loop-arrow-down-left { 
  position: absolute; width: 12px; height: 12px; transform: rotate(45deg); background-color: inherit; 
}
.loop-arrow-up-left { top: -7px; left: -2px; border-left: 2px solid; border-bottom: 2px solid; background: #f8fafc; }
.loop-arrow-up-right { top: -7px; right: -2px; border-top: 2px solid; border-right: 2px solid; background: #f8fafc; }
.loop-arrow-down-left { bottom: -6px; left: -2px; width: 10px; height: 10px; border-left: 2px solid; border-bottom: 2px solid; background-color: white; }

.path-ai .loop-arrow-up-left { border-color: #c084fc; }
.path-decision .loop-arrow-up-right, .path-decision .loop-arrow-up-left, .path-decision .loop-arrow-down-left { border-color: #fb923c; }

.loop-label { position: absolute; font-weight: 700; display: flex; align-items: center; gap: 0.25rem; white-space: nowrap; border: 1px solid; }
.loop-label.ai { background-color: white; color: #6b21a8; border-color: #d8b4fe; padding: 0.5rem 1rem; border-radius: 0.75rem; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); }
.loop-label.decision { background-color: #fff7ed; color: #9a3412; border-color: #fdba74; padding: 0.375rem 0.75rem; border-radius: 0.5rem; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); font-size: 0.625rem; }

/* Parallel */
.parallel-nodes { display: flex; justify-content: space-between; width: 100%; padding: 0 1.5rem; position: relative; z-index: 10; gap: 2rem; }
.parallel-nodes > .node-card { flex: 1; width: auto; }

.branch-fork, .branch-merge { position: relative; width: 100%; height: 60px; }
.branch-v-top { position: absolute; top: 0; left: 50%; width: 2px; height: 30px; background-color: #cbd5e1; transform: translateX(-50%); }
.branch-h { position: absolute; top: 30px; left: 170px; right: 170px; border-top: 2px solid #cbd5e1; }
.branch-v-left, .branch-v-right { position: absolute; top: 30px; width: 2px; height: 30px; background-color: #cbd5e1; }
.branch-v-left { left: 170px; } .branch-v-right { right: 170px; }
.branch-v-left .flow-arrow, .branch-v-right .flow-arrow, .branch-v-bottom .flow-arrow { position: absolute; bottom: -2px; left: 50%; transform: translateX(-50%) rotate(45deg); margin: 0; }

.branch-v-left-top, .branch-v-right-top { position: absolute; top: 0; width: 2px; height: 30px; background-color: #cbd5e1; }
.branch-v-left-top { left: 170px; } .branch-v-right-top { right: 170px; }
.branch-h-bottom { position: absolute; top: 30px; left: 170px; right: 170px; border-bottom: 2px solid #cbd5e1; }
.branch-v-bottom { position: absolute; top: 30px; left: 50%; width: 2px; height: 30px; background-color: #cbd5e1; transform: translateX(-50%); }

/* Specialized */
.external-floating { position: absolute; padding: 12px; z-index: 20; }
.ext-connector { right: 0; top: -6px; background-color: #f8fafc; border-color: #94a3b8; }
.branch-header { border-bottom: 1px solid #f1f5f9; padding-bottom: 0.5rem; margin-bottom: 0.75rem; }
.side-loop { top: 50%; right: -8px; transform: translate(100%, -50%); padding: 0.25rem 0.5rem; font-size: 0.625rem; }
.gateway { background-color: #1e293b; color: white; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1); border-color: #334155; }
.gateway-content { display: flex; align-items: center; gap: 0.75rem; }
.gateway-icon { width: 40px; height: 40px; border-radius: 0.75rem; background: rgba(255,255,255,0.1); display: flex; align-items: center; justify-content: center; border: 1px solid rgba(255,255,255,0.2); }
.gateway-title { font-weight: 700; font-size: 0.875rem; margin-bottom: 0.25rem; }
.gateway-sub { font-size: 11px; color: #cbd5e1; line-height: 1.25; }
.external-stack { position: absolute; top: 8px; left: -300px; display: flex; flex-direction: column; gap: 0.75rem; width: 192px; }
</style>
