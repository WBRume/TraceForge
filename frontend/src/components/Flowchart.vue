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

        <!-- ================= 阶段 1：需求建模、资产白板与原文审阅 ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 1: 需求建模、资产白板与原文审阅 (正向研发)</div>
          
          <div class="node-card node-ext external-floating" style="top: 8px; left: -300px; width: 192px;">
            <div class="node-header txt-ext" style="font-size: 0.75rem;"><GitBranch class="w-4 h-4" /> 需求源、白板与工作区</div>
            <div class="node-desc" style="font-size: 10px;">多仓绑定 · 链接邀请 · 列表/白板模式切换</div>
          </div>
          <div class="loop-path path-ext" style="top: 32px; left: -100px; width: 100px; z-index: 10;">
            <div class="loop-arrow-up-right ext-connector"></div>
          </div>

          <div class="loop-path local-left path-decision" style="top: 30px; bottom: 30px; left: -40px; width: 60px;">
            <div class="loop-arrow-up-right"></div>
            <div class="loop-label decision" style="top: 50%; left: -12px; transform: translate(-100%, -50%);">打回重构</div>
          </div>

          <div class="node-card node-human">
            <div class="node-header txt-human"><FilePlus class="w-5 h-5" /> 用户：导入需求与白板关系编排</div>
            <div class="node-desc">支持多仓/无仓工作区，按季度与分支图谱组织资产并指派负责人</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>
          
          <div class="node-card node-ai bg-ai-half glow-ai">
            <div class="node-header txt-ai"><Brain class="w-5 h-5" /> AI & 用户：拆分评审与 DOCX/MD 原文联合修订</div>
            <div class="node-desc">精确选区同位置讨论、后台生成联合修订提案并逐项采纳发布</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><CheckCircle class="w-5 h-5" /> 系统：覆盖度基准、工作负载投影与沙盘映射</div>
            <div class="node-subtext">2.5D 代码沙盘 / 3D 任务剧场实时呈现，跨工作区负载自动核验</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 2：契约先行、可视化构图与 Mock 隔离 ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 2: 契约先行、架构绘图与 API Mock 隔离 (正向研发)</div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><ClipboardList class="w-5 h-5" /> 系统：解析 OpenAPI 契约与独立绘图板设计</div>
            <div class="node-desc">提取 Endpoint/Entity；Ctrl+Alt+D 呼出绘图板，手绘格式化快速绘制架构/时序图</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai bg-ai-half">
            <div class="node-header txt-ai"><Bot class="w-5 h-5" /> AI：统一作业队列推导多场景 Mock Case</div>
            <div class="node-desc">经 MCP 强类型领域工具生成正常、400/403/500 与空边界用例</div>
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

        <!-- ================= 阶段 3：多引擎协同、桌面浮窗与人在回路 ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 3: 多引擎协同、桌面便捷交互与 HITL (正向研发)</div>

          <div class="node-card node-human">
            <div class="node-header txt-human"><User class="w-5 h-5" /> 用户：多模态录入、图片附件与消息/Diff 批注</div>
            <div class="node-desc">支持在线/离线语音、草稿自动保存、选中引用批注及桌面多标签/置顶浮窗漫游</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai bg-ai-half glow-ai">
            <div class="node-header txt-ai"><Terminal class="w-5 h-5" /> 多引擎 AI (Claude / OpenCode / DSH)：受控协作编码</div>
            <div class="node-desc">MCP 2026 强类型工具 · 运行中追加引导 · 思考胶囊、CLI 悬浮卡与计划快照高亮</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-decision">
            <div class="node-header txt-decision"><PlugZap class="w-5 h-5" /> HITL 拦截：持久化问答回执与免登录会话分享</div>
            <div class="node-subtext">高危改动挂起等待确认；支持只读/邀请输入分享，外部建议由发起人编辑采纳</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 4：双端并行开发与本地协同同步 ================= -->
        <div class="phase-group">
          <div class="phase-badge blue">Phase 4: 云端并行开发、桌面本地协同与基线同步 (正向研发)</div>

          <div class="node-card node-sys bg-sys-third">
            <div class="node-header txt-sys"><PlugZap class="w-5 h-5" /> 系统：注入唯一 Mock 基座 & 多仓 Worktree 并行准备</div>
            <div class="node-subtext">统一契约上下文与持久化作业回执；桌面内置本地资源服务零端口 IPC 就绪</div>
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
            <!-- 左侧：桌面本地协同 -->
            <div class="node-card node-ai bg-white relative">
              <div class="node-header txt-blue branch-header"><Monitor class="w-5 h-5 text-blue-600" /> 桌面本地协同 & 前端流</div>
              <div class="node-desc" style="color: #334155;">💻 本机 IDE 编辑与云端 Agent 并行推进</div>
              <div class="node-subtext">事件自动刷新、按轮次备份、VS Code/IDEA 直达定位</div>
            </div>

            <!-- 右侧：云端 TDD 与基线合并 -->
            <div class="node-card node-ai bg-white relative">
              <!-- TDD 内部红绿循环 -->
              <div class="loop-path local-right path-decision" style="top: 40px; bottom: 30px; right: -24px; width: 32px;">
                <div class="loop-arrow-down-left"></div>
                <div class="loop-label decision side-loop">红绿重写</div>
              </div>

              <div class="node-header txt-green branch-header"><Database class="w-5 h-5 text-green-600" /> 业务后端流 (TDD & 基线更新)</div>
              <div class="node-desc" style="color: #334155;">🤖 自动对照契约并完成单测验证</div>
              <div class="node-desc" style="color: #334155;">🔀 支持远端基线三方合并更新与 Agent 冲突适配</div>
              <div class="node-subtext">所有变更收敛直至<strong>单测与累计评审绿灯通过</strong></div>
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
            <div class="node-header txt-sys"><CheckCircle class="w-5 h-5" /> 系统：任务产物筛选、在线预览与流式 ZIP 导出</div>
            <div class="node-subtext">支持多仓累计差异与无仓工作区差异对比，懒加载预览 PDF/Office/HTML/Diff</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 5：差异归因、Webhook 联动与收尾交付 ================= -->
        <div class="phase-group">
          <div class="phase-badge">Phase 5: 差异归因、验收核查与收尾交付 (正向研发)</div>

          <div class="node-card node-ai bg-red-third">
            <div class="node-header text-red-600"><Target class="w-5 h-5" /> AI & 系统：Delta 工作台与本地交接四维归因</div>
            <div class="node-desc">自动汇总 AI 提议、本地手改交接与终稿：逻辑纠偏 / 边界补充 / 规范对齐 / 视觉美化</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-decision">
            <div class="node-header txt-decision"><ListChecks class="w-5 h-5" /> 用户与系统：三步收尾、需求验收与 Webhook 广播</div>
            <div class="node-subtext">基准比对 → 专家复核 → 最终摘要，支持公网机器人及桌面回环代理实时触达</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><CheckCircle class="w-5 h-5" /> 系统：固化受控证据附件与 100% 全链路追溯</div>
            <div class="node-subtext">任务内上传受控下载，生成不可篡改复盘审计报告，需求与代码双向闭环</div>
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
            <div class="node-desc">现场立卷：提取错误堆栈、失败用例及环境快照进案例中心（支持诊断守卫）</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-ai bg-ai-half glow-ai">
            <div class="node-header txt-ai"><Search class="w-5 h-5" /> AI：PostgreSQL 18 混合检索（双击 Shift 秒搜）</div>
            <div class="node-desc">pg_jieba 全文 + pgvector 向量 RRF 融合，多语料分区秒级命中相似历史故障 Case</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-decision">
            <div class="node-header txt-decision"><ClipboardList class="w-5 h-5" /> 专家 / AI：命中并激活标准排障剧本 (Playbook SOP)</div>
            <div class="node-subtext">自动装配排查清单、逐条证据链行动板与根因检验模板</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-human">
            <div class="node-header txt-human"><Pencil class="w-5 h-5" /> 开发者 & AI：多维溯源诊断与沙箱热修复</div>
            <div class="node-desc">溯源根因：① 需求规格漏项 ② API 契约破损 ③ 编码 Delta 盲区</div>
            <div class="node-subtext">分阶段验证假说或自动推进，Git 隔离沙箱内依 SOP 热修复并验证绿灯</div>
          </div>
        </div>

        <div class="flow-line separator"></div>
        <div class="flow-arrow separator-arrow"></div>

        <!-- ================= 阶段 7：案例沉淀与剧本反哺闭环 ================= -->
        <div class="phase-group" style="margin-bottom: 0;">
          <div class="phase-badge purple">Phase 7: 案例沉淀与后台并行提炼闭环 (经验资产化)</div>

          <div class="node-card node-sys">
            <div class="node-header txt-sys"><Archive class="w-5 h-5" /> 系统：生成结构化诊断报告与统一队列后台提炼</div>
            <div class="node-desc">记录逐条证据链、修复建议与验证耗时；规程晋升并入 sdd_ai_jobs 队列并支持浮窗并行</div>
          </div>
          <div class="flow-line" style="height: 40px;"></div><div class="flow-arrow"></div>

          <div class="node-card node-decision">
            <div class="node-header txt-decision"><GitMerge class="w-5 h-5 text-orange-500" /> 专家评审：案例经验晋升为标准化排障剧本</div>
            <div class="node-subtext">支持持久草案与放弃重写，经评审沉淀入知识中心，反哺后续研发阻断故障复发</div>
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
