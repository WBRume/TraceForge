<script setup lang="ts">
import { computed } from 'vue'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import type { GuideSession } from '@/types/diagnosisPlaybook'
import GuideHypothesisReview from './GuideHypothesisReview.vue'
import { isSupportedHypothesis } from './guideHypothesis'

const props = defineProps<{ state: GuideSession; phase: string; hypothesisId: string; busy: boolean; running: boolean }>()
const emit = defineEmits<{ command: [action: string, hypothesisId?: string]; investigate: [text: string] }>()
const titles: Record<string, string> = { PROBE: '探针采证', HYPOTHESIZE: '假说与实验', REPRODUCE: '症状复现', PATCH: '补丁与回归' }
const subTitles: Record<string, string> = {
  PROBE: 'SOP 第一阶段 · 代码与运行环境只读一致性勘验',
  HYPOTHESIZE: 'SOP 第二阶段 · 假说树证伪与可信根因判定',
  REPRODUCE: 'SOP 第三阶段 · 最小复现脚本与跨租户串单验证',
  PATCH: 'SOP 第四阶段 · 缺陷代码修复与全量回归验收'
}

const report = computed(() => props.state.reports[props.phase])
const hypothesis = computed(() => props.state.hypotheses.find(h => h.id === props.hypothesisId))
const visibleHypotheses = computed(() => hypothesis.value ? [hypothesis.value] : props.state.hypotheses)
const needsRootConfirmation = computed(() => props.phase === 'HYPOTHESIZE' && active.value &&
  !props.state.hypotheses.some(h => h.state === 'APPROVED' && isSupportedHypothesis(h)))
const hasCandidate = computed(() => props.state.hypotheses.some(h => h.state !== 'EXCLUDED' && isSupportedHypothesis(h)))
const active = computed(() => props.phase === props.state.active_phase && !props.state.completed)
const canAdvance = computed(() => active.value && !props.state.error && report.value?.ready_for_review && !!report.value.evidence.length &&
  (props.phase !== 'HYPOTHESIZE' || props.state.hypotheses.some(h => h.state === 'APPROVED' && isSupportedHypothesis(h))) &&
  report.value.outcome !== 'FAILED' && (!['REPRODUCE', 'PATCH'].includes(props.phase) || report.value.outcome === 'OBSERVED'))
const locked = computed(() => props.busy || props.running || !active.value)
const chain = computed(() => Array.isArray(props.state.guide.context.call_chain) ? props.state.guide.context.call_chain as Record<string, unknown>[] : [])

// 智能切分与归类 findings 中的结构化段落
interface ParsedSection {
  tag: string
  content: string
  type: 'phenomenon' | 'paired' | 'danger' | 'success' | 'normal'
}

const parsedFindings = computed<ParsedSection[]>(() => {
  const text = report.value?.findings
  if (!text) return []
  const regex = /(【[^】]+】)/g
  const parts = text.split(regex)
  if (parts.length <= 1) {
    return [{ tag: '', content: text, type: 'normal' }]
  }
  const sections: ParsedSection[] = []
  let currentTag = ''
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i].trim()
    if (!part) continue
    if (part.startsWith('【') && part.endsWith('】')) {
      currentTag = part
    } else {
      let type: ParsedSection['type'] = 'normal'
      if (currentTag.includes('现象')) type = 'phenomenon'
      else if (currentTag.includes('双票') || currentTag.includes('观察') || currentTag.includes('调用链')) type = 'paired'
      else if (currentTag.includes('代码') || currentTag.includes('差异') || currentTag.includes('缺陷')) type = 'danger'
      else if (currentTag.includes('回归') || currentTag.includes('成功')) type = 'success'

      sections.push({ tag: currentTag, content: part, type })
      currentTag = ''
    }
  }
  return sections
})

// 并排显示的配对小节（如 双票/观察 与 调用链）
const pairedSections = computed(() => parsedFindings.value.filter(s => s.type === 'paired'))
// 独立单行展示的小节
const nonPairedSections = computed(() => parsedFindings.value.filter(s => s.type !== 'paired'))

// 解析代码行与 diff 检测
const codeLines = computed(() => {
  if (!report.value?.code) return []
  return report.value.code.split('\n')
})
const isDiffCode = computed(() => {
  return codeLines.value.some(line => line.startsWith('+ ') || line.startsWith('- ') || line.startsWith('--- ') || line.startsWith('+++ '))
})
</script>

<template>
  <div class="stage-workspace">
    <!-- 顶部 Toolbar (对齐图一) -->
    <header class="stage-toolbar">
      <div class="toolbar-left">
        <div class="title-status-line">
          <h2>{{ hypothesis && phase === 'HYPOTHESIZE' ? `${hypothesis.id} · ${hypothesis.claim}` : titles[phase] }}</h2>
          <span class="status-pill" :class="{ 'is-confirmed': state.confirmations[phase] || state.completed, 'is-active': running && active }">
            <span class="status-dot"></span>
            {{ state.completed ? '已完成' : state.confirmations[phase] ? '已确认' : running && active ? '执行中' : report ? '待确认' : '待执行' }}
          </span>
        </div>
        <p class="toolbar-subtitle">{{ subTitles[phase] || '代码与运行环境一致性勘验' }}</p>
      </div>

      <div v-if="active" class="toolbar-actions">
        <label class="auto-run-switch" title="开启后关闭页面仍会继续，证据不足或执行失败时暂停；关闭开关后，当前阶段结束即停止自动推进。">
          <ToggleSwitch :model-value="!!state.auto_run" :disabled="busy || state.completed" aria-label="自动执行全流程"
            @update:model-value="emit('command', state.auto_run ? 'disable_auto' : 'enable_auto')" />
          自动执行全流程
        </label>
        <button class="primary" :disabled="locked || !canAdvance" @click="emit('command', 'advance')">
          <span>{{ phase === 'PATCH' ? '确认并完成' : '确认并进入下一阶段' }}</span>
          <span class="btn-arrow">→</span>
        </button>
      </div>
    </header>

    <!-- 暂停与错误提示条 -->
    <p v-if="state.auto_pause_reason" role="status" class="auto-pause">
      <span class="pause-icon">⚠️</span>
      <span>{{ state.auto_pause_reason }}</span>
    </p>
    <p v-if="state.error && active" role="alert" class="error">{{ state.error }}</p>

    <!-- 来源案例调用链 (带蓝色分支图标与节点微卡片) -->
    <section v-if="phase === 'PROBE' && chain.length" class="panel">
      <h3 class="panel-header">
        <span class="panel-title-with-icon">
          <svg class="header-icon icon-blue" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><path d="M6 9v6m12-3a9 9 0 0 0-9-9"/></svg>
          来源案例调用链
        </span>
        <span class="panel-badge-pill">{{ chain.length }} 个关键拓扑节点</span>
      </h3>
      <ol class="chain-list">
        <li v-for="(node, index) in chain" :key="index" class="chain-card" :class="{ 'is-defect-node': (node.file_path || node.file || '').toString().includes('app.py') }">
          <div class="chain-card-top">
            <span class="chain-index-box">{{ index + 1 }}</span>
            <strong class="chain-module-name">{{ [node.module, node.function].filter(Boolean).join('.') || node.file_path || node.file }}</strong>
            <code class="chain-path-pill">{{ node.file_path || node.file }}</code>
            <span v-if="(node.file_path || node.file || '').toString().includes('app.py')" class="defect-badge">疑似缺陷断点</span>
          </div>
          <p v-if="node.description" class="chain-desc">{{ node.description }}</p>
        </li>
      </ol>
    </section>

    <!-- 假说评审 (HYPOTHESIZE 阶段) -->
    <template v-if="phase === 'HYPOTHESIZE'">
      <p v-if="needsRootConfirmation" class="review-hint" role="status">{{ hasCandidate ? '请核对候选根因的判定依据，再点击“确认根因”。已证伪的假说无需逐项确认。' : '暂无有证据支持的候选根因，请补充排查后再继续。已证伪不代表已找到根因。' }}</p>
      <GuideHypothesisReview v-for="item in visibleHypotheses" :key="item.id" :hypothesis="item" :disabled="locked"
        @command="(action, id) => emit('command', action, id)" />
    </template>

    <!-- 补丁与回归代码面板 (Diff 绿红着色) -->
    <section v-if="report?.code" class="panel code-panel">
      <h3 class="panel-header">
        <span class="panel-title-with-icon">
          <svg class="header-icon icon-purple" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
          {{ phase === 'PATCH' ? '补丁与回归代码' : '实验代码' }}
        </span>
        <span class="panel-badge-pill">{{ { NOT_RUN: '未执行', OBSERVED: '已记录结果', FAILED: '执行失败' }[report.outcome] }}</span>
      </h3>
      <pre class="dark-code-viewport"><code v-if="isDiffCode" class="diff-container"><div v-for="(line, lIdx) in codeLines" :key="lIdx" class="diff-row" :class="{ 'diff-add': line.startsWith('+'), 'diff-del': line.startsWith('-') }"><span class="diff-prefix">{{ line.slice(0, 1) }}</span><span class="diff-code-text">{{ line.slice(1) }}</span></div></code><code v-else>{{ report.code }}</code></pre>
    </section>

    <!-- 采证结果 / 阶段结果 (图一神级微卡片排版) -->
    <section class="panel findings-section">
      <h3 class="panel-header">
        <span class="panel-title-with-icon">
          <svg class="header-icon icon-green" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/><path d="m9 14 2 2 4-4"/></svg>
          {{ phase === 'PROBE' ? '采证结果' : '阶段结果' }}
        </span>
        <span class="panel-badge-pill green-pill">只读检查完成</span>
      </h3>

      <p v-if="!report" class="empty">暂无阶段结果</p>
      
      <div v-else class="findings-container">
        <!-- 现象卡片 (图一橙色指示点) -->
        <template v-for="(sec, idx) in nonPairedSections" :key="'single-' + idx">
          <div v-if="sec.type === 'phenomenon'" class="phenomenon-card">
            <div class="card-tag-row">
              <span class="orange-dot"></span>
              <strong class="tag-title">{{ sec.tag || '【现象比对】' }}</strong>
            </div>
            <div class="card-content-body highlight-tokens">{{ sec.content }}</div>
          </div>
        </template>

        <!-- 双列并排 Grid (图一双列布局：本会话双票 vs 调用链核对) -->
        <div v-if="pairedSections.length > 0" class="paired-grid">
          <div v-for="(sec, pIdx) in pairedSections" :key="'paired-' + pIdx" class="paired-subcard">
            <div class="card-tag-row">
              <strong class="subcard-tag">{{ sec.tag }}</strong>
            </div>
            <div class="card-content-body font-code-soft">{{ sec.content }}</div>
          </div>
        </div>

        <!-- 其他单列小节 (如代码核对结论、回归执行等) -->
        <template v-for="(sec, idx) in nonPairedSections" :key="'other-' + idx">
          <div v-if="sec.type !== 'phenomenon' && sec.tag" class="emphasis-subcard" :class="{
            'card-danger': sec.type === 'danger',
            'card-success': sec.type === 'success'
          }">
            <div class="card-tag-row">
              <strong class="emphasis-tag">{{ sec.tag }}</strong>
            </div>
            <div class="card-content-body font-code-soft">{{ sec.content }}</div>
          </div>
        </template>

        <!-- 纯文本兜底 -->
        <p v-if="parsedFindings.length <= 1" class="raw-findings-text">{{ report.findings }}</p>

        <!-- 补充排查按钮 (图一浅蓝胶囊) -->
        <div class="action-footer">
          <button v-if="active" class="text-action-pill" :disabled="locked" @click="emit('investigate', `请继续 SOP 的「${titles[phase]}」阶段，检查当前材料，补充本次证据和阶段结果。`)">
            <span class="btn-icon">↻</span>
            <span>补充排查</span>
          </button>
        </div>
      </div>
    </section>

    <!-- 本次证据 (清爽现代终端输出，彻底去除蓝色大外壳与突兀黑色视窗) -->
    <section v-if="report?.evidence.length" class="panel evidence-section">
      <h3 class="panel-header">
        <span class="panel-title-with-icon">
          <svg class="header-icon icon-indigo" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8Z"/><path d="M12 6a6 6 0 0 0-6 6c0 1.66.67 3.16 1.76 4.24"/><path d="M12 10a2 2 0 0 0-2 2c0 .55.22 1.05.59 1.41"/></svg>
          本次证据
        </span>
        <span class="panel-badge-pill">{{ report.evidence.length }} 项物证</span>
      </h3>

      <div class="evidence-list-wrap">
        <div v-for="(entry, i) in report.evidence" :key="i" class="evidence-item-card">
          <!-- 干净等宽蓝色引用行 (无大蓝壳外框，纯净干练) -->
          <div class="evidence-ref-row">
            <svg class="evidence-ref-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <code class="evidence-ref-code">{{ entry.reference }}</code>
          </div>

          <!-- 统一浅色清爽输出容器 (无割裂黑底，排版统一) -->
          <div class="evidence-output-box">
            <pre class="evidence-output-pre">{{ entry.observation }}</pre>
          </div>
        </div>
      </div>
    </section>

    <!-- 采证清单 (图一绿色圆点对勾) -->
    <section v-if="phase === 'PROBE'" class="panel checklist-section">
      <h3 class="panel-header">
        <span class="panel-title-with-icon">
          <svg class="header-icon icon-gray" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          采证清单
        </span>
      </h3>
      <ol class="checklist-items">
        <li v-for="(step, sIdx) in state.guide.steps.filter(s => !['hypotheses', 'conclusion'].includes(s.id))" :key="step.id" class="checklist-row">
          <span class="check-circle-icon">✓</span>
          <span class="checklist-text">{{ sIdx + 1 }}. {{ step.objective }}</span>
        </li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.stage-workspace { display:flex; flex-direction:column; gap:16px; padding:20px 22px; min-width:0; background:#f8fafc }

/* 顶部 Toolbar (对齐图一) */
.stage-toolbar {
  display:flex;
  gap:16px;
  align-items:center;
  justify-content:space-between;
  padding:16px 20px;
  border:1px solid #e2e8f0;
  border-radius:12px;
  background:#ffffff;
  box-shadow:0 1px 3px 0 rgba(0,0,0,0.03);
}
.toolbar-left { display:flex; flex-direction:column; gap:4px }
.title-status-line { display:flex; align-items:center; gap:10px }
h2 { margin:0; font-size:16px; font-weight:750; color:#0f172a; letter-spacing:-0.02em }

.status-pill {
  display:inline-flex;
  align-items:center;
  gap:5px;
  font-size:11px;
  font-weight:600;
  padding:2px 8px;
  border-radius:9999px;
  background:#f1f5f9;
  color:#64748b;
  border:1px solid #e2e8f0;
}
.status-dot { width:6px; height:6px; border-radius:9999px; background:#94a3b8 }
.status-pill.is-confirmed { background:#ecfdf5; color:#047857; border-color:#a7f3d0 }
.status-pill.is-confirmed .status-dot { background:#10b981 }
.status-pill.is-active { background:#eff6ff; color:#1d4ed8; border-color:#bfdbfe }
.status-pill.is-active .status-dot { background:#3b82f6 }

.toolbar-subtitle { margin:0; font-size:11.5px; color:#64748b }

.toolbar-actions { display:flex; gap:14px; align-items:center; flex-shrink:0 }
.auto-run-switch { --toggle-active:#2563eb; display:flex; align-items:center; gap:8px; font-size:12px; font-weight:600; color:#475569; cursor:pointer; white-space:nowrap }

/* 主流转按钮 (图一实心经典蓝) */
.primary {
  background:#2563eb;
  border:1px solid #1d4ed8;
  color:#ffffff;
  font-weight:600;
  font-size:12px;
  padding:7px 14px;
  border-radius:8px;
  display:inline-flex;
  align-items:center;
  gap:6px;
  box-shadow:0 1px 3px 0 rgba(37,99,235,0.25);
  cursor:pointer;
  transition:all 120ms ease;
}
.primary:hover:not(:disabled) { background:#1d4ed8 }
.primary:disabled { opacity:0.5; cursor:default; box-shadow:none }
.btn-arrow { font-size:11px }

/* 提示条 */
.auto-pause { margin:0; padding:10px 16px; color:#92400e; background:#fffbeb; border:1px solid #fde68a; border-radius:8px; font-size:12px; display:flex; align-items:center; gap:8px; font-weight:500 }
.pause-icon { font-size:13px }
.error { color:#b91c1c; margin:0; font-size:12px; padding:10px 14px; background:#fef2f2; border:1px solid #fecaca; border-radius:8px }
.review-hint { margin:0; padding:12px 16px; color:#1e40af; background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; font-size:12px; line-height:1.6 }

/* 面板卡片基础 (图一独立卡片) */
.panel {
  background:#ffffff;
  border:1px solid #e2e8f0;
  border-radius:12px;
  overflow:hidden;
  min-width:0;
  box-shadow:0 1px 3px 0 rgba(0,0,0,0.03);
}

.panel-header {
  margin:0;
  font-size:13px;
  font-weight:700;
  color:#1e293b;
  padding:12px 18px;
  background:#f8fafc;
  border-bottom:1px solid #e2e8f0;
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:12px;
}
.panel-title-with-icon { display:flex; align-items:center; gap:8px }
.header-icon { flex-shrink:0 }
.icon-blue { color:#2563eb }
.icon-green { color:#10b981 }
.icon-purple { color:#8b5cf6 }
.icon-indigo { color:#6366f1 }
.icon-gray { color:#64748b }

.panel-badge-pill { font-size:11px; font-weight:600; padding:2px 8px; border-radius:9999px; background:#f1f5f9; color:#64748b }
.panel-badge-pill.green-pill { background:#ecfdf5; color:#047857; border:1px solid #a7f3d0 }

/* 来源案例调用链 (图一拓扑卡片) */
.chain-list { list-style:none; margin:0; padding:14px 18px; display:flex; flex-direction:column; gap:10px }
.chain-card { padding:12px 14px; background:#f8fafc; border:1px solid #f1f5f9; border-radius:8px; font-size:12px; transition:border-color 120ms ease }
.chain-card:hover { border-color:#e2e8f0 }
.chain-card.is-defect-node { background:rgba(254, 242, 242, 0.5); border-color:#fecaca }

.chain-card-top { display:flex; align-items:center; gap:8px; flex-wrap:wrap }
.chain-index-box { width:20px; height:20px; border-radius:4px; background:#eff6ff; color:#2563eb; border:1px solid #dbeafe; font-size:11px; font-weight:700; display:inline-flex; align-items:center; justify-content:center; flex-shrink:0 }
.is-defect-node .chain-index-box { background:#f43f5e; color:#ffffff; border-color:#f43f5e }
.chain-module-name { color:#0f172a; font-size:12.5px; font-weight:700 }
.chain-path-pill { font-size:11px; font-family:ui-monospace, SFMono-Regular, monospace; color:#2563eb; background:#eff6ff; padding:2px 7px; border-radius:4px; border:1px solid #dbeafe; font-weight:600 }
.is-defect-node .chain-path-pill { color:#e11d48; background:#ffe4e6; border-color:#fecdd3 }
.defect-badge { font-size:10px; font-weight:700; color:#e11d48; background:#ffe4e6; padding:1px 6px; border-radius:4px }
.chain-desc { margin:6px 0 0; color:#475569; font-size:12px; line-height:1.55 }

/* 采证结果 / 阶段结果 (图一精美排版) */
.findings-container { padding:16px 18px; display:flex; flex-direction:column; gap:12px }

/* 现象卡片 (橙色小点 + 浅灰微底) */
.phenomenon-card {
  padding:12px 14px;
  background:#f8fafc;
  border:1px solid #e2e8f0;
  border-radius:8px;
}
.card-tag-row { display:flex; align-items:center; gap:6px; margin-bottom:6px }
.orange-dot { width:7px; height:7px; border-radius:9999px; background:#f59e0b; flex-shrink:0 }
.tag-title { font-size:12px; font-weight:750; color:#1e293b }
.card-content-body { font-size:12.5px; line-height:1.7; color:#334155; white-space:pre-wrap; overflow-wrap:anywhere }

/* 双列并排 Grid (图一) */
.paired-grid { display:grid; grid-template-columns:1fr; gap:12px }
@media (min-width: 768px) {
  .paired-grid { grid-template-columns:1fr 1fr }
}
.paired-subcard {
  padding:12px 14px;
  background:#f8fafc;
  border:1px solid #f1f5f9;
  border-radius:8px;
}
.subcard-tag { font-size:12px; font-weight:700; color:#334155 }
.font-code-soft { font-size:12px; line-height:1.65 }

/* 强调型子卡片 (代码核对/补丁差异/回归等) */
.emphasis-subcard {
  padding:12px 14px;
  border-radius:8px;
  border:1px solid #e2e8f0;
  background:#f8fafc;
}
.emphasis-subcard.card-danger { background:rgba(254, 242, 242, 0.4); border-color:#fecaca }
.emphasis-subcard.card-danger .emphasis-tag { color:#991b1b }
.emphasis-subcard.card-success { background:rgba(240, 253, 244, 0.4); border-color:#bbf7d0 }
.emphasis-subcard.card-success .emphasis-tag { color:#166534 }
.emphasis-tag { font-size:12px; font-weight:750; color:#1e293b }

.raw-findings-text { margin:0; font-size:12.5px; line-height:1.75; color:#334155; white-space:pre-wrap; overflow-wrap:anywhere }

/* 补充排查胶囊按钮 (图一清爽浅蓝) */
.action-footer { margin-top:4px }
.text-action-pill {
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding:6px 14px;
  border-radius:6px;
  background:#eff6ff;
  border:1px solid #bfdbfe;
  color:#1d4ed8;
  font-size:12px;
  font-weight:600;
  cursor:pointer;
  transition:all 120ms ease;
}
.text-action-pill:hover:not(:disabled) { background:#dbeafe; border-color:#93c5fd }
.text-action-pill:disabled { opacity:0.5; cursor:default }
.btn-icon { font-size:12px }

/* 本次证据 (无臃肿外壳、无割裂黑底、统一清爽现代) */
.evidence-list-wrap { padding:14px 18px; display:flex; flex-direction:column; gap:12px }
.evidence-item-card { display:flex; flex-direction:column; gap:6px }

/* 引用行：干净优雅的等宽蓝字，无臃肿外壳 */
.evidence-ref-row {
  display:inline-flex;
  align-items:center;
  gap:6px;
  max-width:100%;
}
.evidence-ref-icon { color:#2563eb; flex-shrink:0 }
.evidence-ref-code {
  font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size:11.5px;
  font-weight:600;
  color:#2563eb;
  line-height:1.4;
  overflow-wrap:anywhere;
}

/* 证据输出容器：统一浅色专业终端排版，告别割裂的黑底视窗 */
.evidence-output-box {
  padding:10px 14px;
  background:#f8fafc;
  border:1px solid #e2e8f0;
  border-radius:8px;
  overflow-x:auto;
}
.evidence-output-pre {
  margin:0;
  white-space:pre-wrap;
  overflow-wrap:anywhere;
  font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size:11.5px;
  line-height:1.65;
  color:#334155;
}

/* 代码补丁 Diff 视窗 */
.code-panel .dark-code-viewport { margin:0; background:#0f172a; color:#f8fafc; padding:14px 16px; overflow:auto; font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size:12px; line-height:1.65; max-height:440px }
.diff-container { display:flex; flex-direction:column }
.diff-row { display:flex; padding:2px 8px; border-radius:3px; margin-bottom:1px }
.diff-prefix { width:16px; flex-shrink:0; font-weight:700; user-select:none }
.diff-code-text { flex:1; white-space:pre-wrap; overflow-wrap:anywhere }
.diff-row.diff-add { background:rgba(16, 185, 129, 0.16); color:#6ee7b7; border-left:3px solid #10b981 }
.diff-row.diff-del { background:rgba(244, 63, 94, 0.16); color:#fda4af; border-left:3px solid #f43f5e }

/* 采证清单 (图一绿色对勾圆标) */
.checklist-items { list-style:none; margin:0; padding:14px 18px; display:flex; flex-direction:column; gap:8px }
.checklist-row { display:flex; align-items:center; gap:8px; font-size:12.5px; color:#334155 }
.check-circle-icon { width:16px; height:16px; border-radius:9999px; background:#10b981; color:#ffffff; font-size:10px; font-weight:800; display:inline-flex; align-items:center; justify-content:center; flex-shrink:0 }

.empty { color:#94a3b8; padding:16px 18px; margin:0; font-size:12px }
</style>
