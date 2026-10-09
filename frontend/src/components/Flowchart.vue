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
  Database,
  ListChecks,
  PlugZap,
  Monitor,
  Archive,
  Target,
  Rocket,
  AlertCircle,
  Bug,
  Lightbulb,
  Brain,
  ClipboardList,
  GitMerge,
  Terminal
} from '@/components/icons'

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
        <!-- ================= 全局巨型循环 7 -> 1 (右侧经验反哺闭环) ================= -->
        <div class="loop-path right-loop path-ai" style="top: 60px; bottom: 120px; right: -120px; width: 180px;">
          <div class="loop-arrow-up-left"></div>
          <div class="loop-label ai glow-ai" style="top: 50%; right: -24px; transform: translate(100%, -50%);">
            <Lightbulb class="w-5 h-5 text-yellow-500" /> 排障剧本反哺更新全局规则库与新研发需求
          </div>
        </div>

        <!-- ================= 嵌套循环 5 -> 2 (左侧需求重塑闭环) ================= -->
        <div class="loop-path left-loop path-decision" style="top: 480px; bottom: 780px; left: -80px; width: 120px;">
          <div class="loop-arrow-up-right"></div>
          <div class="loop-label decision" style="top: 50%; left: -16px; transform: translate(-100%, -50%);">
            <GitMerge class="w-4 h-4 text-orange-500" /> 作为新需求，重塑闭环
          </div>
        </div>

        <!-- ================= 阶段 1：需求建模与资产拆分 ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 1: 需求建模与资产拆分 (正向研发)</div>
          
          <div class="node-card node-ext external-floating" style="top: 8px; left: -300px; width: 192px;">
            <div class="node-header txt-ext" style="font-size: 0.75rem;"><GitBranch class="w-4 h-4" /> 需求源与规范包</div>
            <div class="node-desc" style="font-size: 10px;">Markdown 规范包与工作区隔离沙箱</div>
          </div>
          <div class="loop-path path-ext" style="top: 32px; left: -100px; width: 100px; z-index: 10;">
            <div class="loop-arrow-up-right ext-connector"></div>
          </div>

          <div class="loop-path local-left path-decision" style="top: 30px; bottom: 30px; left: -40px; width: 60px;">
            <div class="loop-arrow-up-right"></div>
            <div class="loop-label decision" style="top: 50%; left: -12px; transform: translate(-100%, -50%);">打回重构</div>
          </div>

          <div class="node-card node-human">
            <div class="node-header txt-human"><FilePlus class="w-5 h-5" /> 用户：导入 Markdown 需求</div>
            <div class="node-desc">划定租户空间与安全沙箱基准</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>
          
          <div class="node-card node-ai bg-ai-half glow-ai">
            <div class="node-header txt-ai"><Brain class="w-5 h-5" /> AI & 用户：树状拆分与块级评审 (Split Review)</div>
            <div class="node-desc">粗粒度需求分解为原子需求项，绑定验收准则并关联 Task</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><CheckCircle class="w-5 h-5" /> 系统：建立全链路覆盖度基准矩阵</div>
            <div class="node-subtext">Requirement → Task 严格挂载，杜绝无需求编码</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 2：契约先行与 API Mock 隔离 ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 2: 契约先行与 API Mock 隔离 (正向研发)</div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><ClipboardList class="w-5 h-5" /> 系统：解析 OpenAPI / Swagger 契约</div>
            <div class="node-desc">自动提取 Endpoint 端点定义与 Entity 数据实体结构</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai bg-ai-half">
            <div class="node-header txt-ai"><Bot class="w-5 h-5" /> AI：自动推导多场景 Mock Case</div>
            <div class="node-desc">生成正常响应、参数校验 400、权限 403、熔断 500 与空边界用例</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <!-- Gateway -->
          <div class="node-card node-sys gateway">
            <div class="gateway-content">
              <div class="gateway-icon">
                <Plug class="w-6 h-6 text-blue-300" />
              </div>
              <div>
                <div class="gateway-title">系统：动态切流虚拟网关 (Dynamic Gateway)</div>
                <div class="gateway-sub">单接口 MOCK 仿真 / PROXY 真实后端透传<br>混沌工程异常注入 · 彻底解耦前后端联调</div>
              </div>
            </div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 3：终端协同与人在回路 (HITL) ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 3: 终端协同与人在回路 (正向研发)</div>

          <div class="node-card node-human">
            <div class="node-header txt-human"><User class="w-5 h-5" /> 用户：多模态录入 (键盘 / 离线 Whisper 语音)</div>
            <div class="node-desc">高精度输入提示词与业务约束，解放双手</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai bg-ai-half glow-ai">
            <div class="node-header txt-ai"><Terminal class="w-5 h-5" /> AI (Claude CLI / PTY)：协作编码与计划比对</div>
            <div class="node-desc">流式展示推理过程、工具调用与计划文档高亮快照</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-decision">
            <div class="node-header txt-decision"><PlugZap class="w-5 h-5" /> HITL 拦截：高危变更授权与双向澄清</div>
            <div class="node-subtext">高危文件操作强制挂起等待人工授权；主动发起问答消除歧义</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 4：TDD 并行开发与单测绿灯 ================= -->
        <div class="phase-group">
          <div class="phase-badge blue">Phase 4: TDD 并行开发与单测绿灯 (正向研发)</div>

          <div class="node-card node-sys bg-sys-third">
            <div class="node-header txt-sys"><PlugZap class="w-5 h-5" /> 系统：注入唯一 Mock Base URL</div>
            <div class="node-subtext">统一稳定的全局契约上下文基座</div>
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
              <div class="node-desc" style="color: #334155;">🤖 独立对接 Mock 网关，不被阻塞</div>
              <div class="node-subtext">自动编写页面组件、Pinia 状态与交互逻辑</div>
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

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><CheckCircle class="w-5 h-5" /> 系统：生成基准代码快照 (Git Worktree)</div>
            <div class="node-subtext">为变更归因与验收准备稳定的初始版本</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 5：差异归因与三步收尾交付 ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 5: 差异归因与三步收尾交付 (正向研发)</div>

          <div class="node-card node-ai bg-red-third">
            <div class="node-header text-red-600"><Target class="w-5 h-5" /> AI & 系统：Delta 工作台四维差异归因</div>
            <div class="node-desc">逐行分类：逻辑纠偏 / 边界补充 / 规范对齐 / 视觉美化</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-decision">
            <div class="node-header txt-decision"><ListChecks class="w-5 h-5" /> 用户与系统：三步收尾工作流 (Closeout)</div>
            <div class="node-subtext">基准对比 (Baseline) → 专家审查 (Review) → 最终摘要 (Summary)</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><CheckCircle class="w-5 h-5" /> 系统：固化交付证据链与 100% 全链路追溯覆盖</div>
            <div class="node-subtext">生成不可篡改复盘审计报告，需求与代码双向闭环</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 6：异常阻断与问题定位路径 ================= -->
        <div class="phase-group">
          <div class="phase-badge red">Phase 6: 异常阻断与问题定位路径 (故障定位闭环)</div>

          <!-- 左侧监控与自动化外部告警源 -->
          <div class="external-stack">
            <div class="node-card node-ext p-3 w-full">
              <div class="node-header txt-ext text-[0.75rem] mb-1"><Rocket class="w-4 h-4" /> 自动化流水线</div>
              <div class="node-desc text-[0.625rem]">以 Mock 契约跑回归单测</div>
            </div>
            <div class="node-card node-ext p-3 w-full">
              <div class="node-header txt-ext text-[0.75rem] mb-1"><AlertCircle class="w-4 h-4" /> 线上监控告警</div>
              <div class="node-desc text-[0.625rem]">APM 捕获异常堆栈与 Payload</div>
            </div>
          </div>
          <div class="loop-path path-error" style="top: 60px; left: -100px; width: 100px; z-index: 10;">
            <div class="loop-arrow-up-right ext-connector"></div>
          </div>

          <!-- 局部排障重试循环 -->
          <div class="loop-path local-left path-decision" style="top: 190px; bottom: 30px; left: -40px; width: 60px;">
            <div class="loop-arrow-up-right"></div>
            <div class="loop-label decision" style="top: 50%; left: -12px; transform: translate(-100%, -50%);">重测未过</div>
          </div>

          <div class="node-card node-decision border-red-400 bg-red-white">
            <div class="node-header text-red-700"><Bug class="w-5 h-5 text-red-500 animate-pulse" /> 异常阻断：CI 爆红 / 线上抛出告警</div>
            <div class="node-desc">现场立卷：提取错误堆栈、失败用例及环境快照进案例中心</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai bg-ai-half glow-ai">
            <div class="node-header txt-ai"><Search class="w-5 h-5" /> AI：基于 RAG 检索知识库与排障剧本</div>
            <div class="node-desc">以异常特征在向量库中秒级检索历史相似故障 Case</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-decision">
            <div class="node-header txt-decision"><ClipboardList class="w-5 h-5" /> 专家 / AI：命中并激活标准排障剧本 (Playbook SOP)</div>
            <div class="node-subtext">自动装配排查清单、诊断命令与根因检验模板</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-human">
            <div class="node-header txt-human"><Pencil class="w-5 h-5" /> 开发者 & AI：多维溯源诊断与沙箱热修复</div>
            <div class="node-desc">溯源根因：① 需求规格漏项 ② API 契约破损 ③ 编码 Delta 盲区</div>
            <div class="node-subtext">Git 隔离沙箱内依剧本 SOP 热修复并验证单测绿灯通过</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 7：案例沉淀与剧本反哺闭环 ================= -->
        <div class="phase-group" style="margin-bottom: 0;">
          <div class="phase-badge purple">Phase 7: 案例沉淀与剧本反哺闭环 (经验资产化)</div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><Archive class="w-5 h-5" /> 系统：生成故障诊断报告 (Case Report)</div>
            <div class="node-desc">记录完整根因链、修复 Patch、单测验证证据与排障耗时</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-decision">
            <div class="node-header txt-decision"><GitMerge class="w-5 h-5 text-orange-500" /> 专家评审：案例经验晋升为标准化排障剧本</div>
            <div class="node-subtext">沉淀入四维知识库，反哺后续研发，彻底杜绝同类故障复发</div>
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
.phase-badge.red { background-color: #dc2626; }
.phase-badge.purple { background-color: #7c3aed; }

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
