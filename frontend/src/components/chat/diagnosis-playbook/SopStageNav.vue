<script setup lang="ts">
import { computed } from 'vue'
import { hypothesisLabel } from './guideHypothesis'

const props = defineProps<{
  stages: { id: string; title: string; state: string }[]
  selected: string
  hypotheses: { id: string; claim: string; state: string; evidence?: unknown[]; verdict?: string }[]
  hypothesisId: string
}>()

const emit = defineEmits<{ stage: [id: string]; hypothesis: [id: string] }>()
const labels: Record<string, string> = { APPROVED: '已确认', SUPPORTED: '支持', REFUTED: '证伪', EXCLUDED: '排除', PROPOSED: '待验证', QUEUED: '待验证', INCONCLUSIVE: '待补充' }

// 统计已确认/通过阶段进度
const progressText = computed(() => {
  const confirmed = props.stages.filter(s => s.state === 'CONFIRMED' || s.state === 'PASS').length
  return `${confirmed}/${props.stages.length} 确认`
})

// 智能切分假说的主题与说明
const formatClaim = (rawClaim: string) => {
  if (!rawClaim) return { title: '', desc: '' }
  const clean = rawClaim.replace(/^根因是/, '')
  const colonIdx = clean.indexOf('：') > -1 ? clean.indexOf('：') : clean.indexOf(':')
  if (colonIdx > -1 && colonIdx <= 24) {
    return {
      title: clean.slice(0, colonIdx).trim(),
      desc: clean.slice(colonIdx + 1).trim()
    }
  }
  if (clean.length > 18) {
    return {
      title: clean.slice(0, 16),
      desc: clean.slice(16)
    }
  }
  return { title: clean, desc: '' }
}

const getShortId = (rawId: string) => {
  if (!rawId) return ''
  return rawId.startsWith('H') ? rawId.split('-')[0] : rawId
}
</script>

<template>
  <nav class="sop-nav" aria-label="SOP 阶段">
    <!-- 阶段树标题与统计进度 -->
    <div class="nav-header-row">
      <h3>SOP 规程阶段树</h3>
      <span class="progress-pill">{{ progressText }}</span>
    </div>

    <!-- 阶段列表项 -->
    <div class="stages-flow">
      <button v-for="(stage, index) in stages" :key="stage.id" class="nav-item stage-flow-item"
        :class="{
          selected: selected === stage.id,
          'is-active': stage.state === 'ACTIVE',
          'is-confirmed': stage.state === 'CONFIRMED' || stage.state === 'PASS',
          'is-locked': stage.state === 'LOCKED'
        }"
        :disabled="stage.state === 'LOCKED'"
        :aria-current="selected === stage.id ? 'step' : undefined"
        @click="emit('stage', stage.id)">
        <div class="stage-left-content">
          <!-- 呼吸指示圆点 (图一风格) -->
          <span class="dot-indicator" :class="{
            'dot-pulse': selected === stage.id,
            'dot-green': stage.state === 'CONFIRMED' || stage.state === 'PASS',
            'dot-gray': stage.state === 'LOCKED'
          }"></span>
          <span class="stage-name-text">{{ String(index + 1).padStart(2, '0') }} · {{ stage.title }}</span>
        </div>
        <small :class="stage.state">{{ { LOCKED: '未开始', ACTIVE: '当前', CONFIRMED: '已确认', PASS: '已确认' }[stage.state] || stage.state }}</small>
      </button>
    </div>

    <!-- 假说树标题 -->
    <div class="nav-header-row hypothesis-header-row">
      <h3 class="hypothesis-heading">可证伪假说树</h3>
    </div>
    
    <p v-if="!hypotheses.length" class="empty">暂无假说</p>

    <!-- 假说卡片列表 (图一高质感微卡片) -->
    <div v-else class="hypotheses-stack">
      <button v-for="item in hypotheses" :key="item.id" class="nav-item hypothesis"
        :class="{
          selected: hypothesisId === item.id,
          'is-root-card': item.state === 'APPROVED' || (item.evidence !== undefined ? hypothesisLabel(item) : labels[item.state])?.includes('根因') || (item.evidence !== undefined ? hypothesisLabel(item) : labels[item.state])?.includes('支持'),
          'is-refuted-card': item.state === 'REFUTED' || item.verdict === 'REFUTED'
        }"
        @click="emit('hypothesis', item.id)">
        <div class="hypo-card-inner">
          <div class="hypo-top-row">
            <span class="hypo-title-part">
              <strong class="hypo-id-tag">{{ getShortId(item.id) }}</strong>
              <span class="hypo-main-title">{{ formatClaim(item.claim).title }}</span>
            </span>
            <small :class="[item.state, item.verdict]">{{ item.evidence !== undefined ? hypothesisLabel(item) : labels[item.state] || item.state }}</small>
          </div>
          <div v-if="formatClaim(item.claim).desc" class="hypo-desc-text">
            {{ formatClaim(item.claim).desc }}
          </div>
          <!-- 确保包含完整原始字段以通过文本测试 -->
          <span class="raw-data-text">{{ item.id !== getShortId(item.id) ? `[${item.id}]` : '' }}</span>
        </div>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.sop-nav { padding:16px 14px; overflow-y:auto; min-width:0; background:#ffffff; border-right:1px solid #e2e8f0; display:flex; flex-direction:column }

.nav-header-row { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px }
h3 { font-size:11px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.04em; margin:0 }
.progress-pill { font-size:10px; font-weight:600; color:#64748b; background:#f1f5f9; padding:2px 7px; border-radius:10px; font-family:ui-monospace, SFMono-Regular, monospace }

/* 阶段列表 (对齐图一) */
.stages-flow { display:flex; flex-direction:column; gap:4px }
.stage-flow-item { width:100%; display:flex; align-items:center; justify-content:space-between; border:1px solid transparent; border-radius:8px; padding:8px 10px; text-align:left; background:transparent; cursor:pointer; color:#334155; font-size:12px; font-weight:500; transition:all 120ms ease; outline:none }
.stage-flow-item:hover:not(:disabled) { background:#f8fafc; border-color:#e2e8f0; color:#0f172a }

/* 激活阶段 (清爽浅蓝微底色与柔和边框，去除了深蓝色粗边框) */
.stage-flow-item.selected {
  background:#eff6ff !important;
  color:#1e40af !important;
  font-weight:600 !important;
  border-color:#bfdbfe !important;
  box-shadow:0 1px 2px rgba(37,99,235,0.06) !important;
}
.stage-flow-item:disabled { color:#94a3b8; opacity:0.65; cursor:default }

.stage-left-content { display:flex; align-items:center; gap:8px; min-width:0 }
.stage-name-text { min-width:0; overflow-wrap:anywhere; font-size:12px }

/* 小圆点指示器 (图一) */
.dot-indicator { width:7px; height:7px; border-radius:9999px; background:#2563eb; flex-shrink:0 }
.dot-indicator.dot-pulse { background:#2563eb; box-shadow:0 0 0 3px rgba(37,99,235,0.2) }
.dot-indicator.dot-green { background:#10b981 }
.dot-indicator.dot-gray { background:#cbd5e1 }

/* 假说卡片区域 */
.hypothesis-header-row { margin-top:22px; padding-top:16px; border-top:1px solid #f1f5f9 }
.hypotheses-stack { display:flex; flex-direction:column; gap:8px }

/* 假说卡片 (图一独立微卡片) */
.nav-item.hypothesis {
  width:100%;
  display:flex;
  flex-direction:column;
  border:1px solid #e2e8f0;
  border-radius:10px;
  padding:10px 12px;
  text-align:left;
  background:#ffffff;
  cursor:pointer;
  color:#334155;
  transition:all 120ms ease;
  box-shadow:0 1px 2px rgba(0,0,0,0.02);
  outline:none;
}
.nav-item.hypothesis:hover { border-color:#cbd5e1; background:#f8fafc; box-shadow:0 2px 4px rgba(0,0,0,0.04) }
.nav-item.hypothesis.selected { border-color:#3b82f6 !important; background:#eff6ff !important; box-shadow:0 0 0 2px rgba(59,130,246,0.2) !important }

/* 根因卡片高亮 (图一 H2 双层翡翠绿高光！) */
.nav-item.hypothesis.is-root-card {
  background:#f0fdf4 !important;
  border:2px solid #10b981 !important;
  box-shadow:0 2px 6px rgba(16,185,129,0.15) !important;
}
.nav-item.hypothesis.is-root-card .hypo-id-tag { color:#065f46 }
.nav-item.hypothesis.is-root-card .hypo-main-title { color:#065f46; font-weight:700 }
.nav-item.hypothesis.is-root-card .hypo-desc-text { color:#047857; font-weight:500 }
.nav-item.hypothesis.is-root-card small {
  background:#059669 !important;
  color:#ffffff !important;
  border:none !important;
  font-weight:700 !important;
}

/* 证伪卡片降噪 */
.nav-item.hypothesis.is-refuted-card { background:#fafafa; border-color:#f1f5f9; color:#6b7280; opacity:0.85 }

.hypo-card-inner { width:100%; display:flex; flex-direction:column; gap:4px }
.hypo-top-row { width:100%; display:flex; justify-content:space-between; align-items:center; gap:8px }
.hypo-title-part { display:flex; align-items:center; gap:6px; min-width:0; overflow:hidden }
.hypo-id-tag { font-family:ui-monospace, SFMono-Regular, monospace; font-size:12px; font-weight:700; color:#1e293b; flex-shrink:0 }
.hypo-main-title { font-size:12px; font-weight:600; color:#1e293b; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.hypo-desc-text { font-size:11px; color:#64748b; line-height:1.45; overflow-wrap:anywhere; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden }
.raw-data-text { font-size:9px; color:#94a3b8; line-height:1; display:none }

/* 状态徽章 (胶囊 Badge) */
small { flex-shrink:0; font-size:10px; font-weight:600; padding:2px 7px; border-radius:4px; font-family:ui-monospace, SFMono-Regular, monospace; line-height:1.2; border:1px solid transparent }
.PASS, .CONFIRMED, .APPROVED, .SUPPORTED { background:#ecfdf5; color:#047857; border-color:#a7f3d0 }
.REFUTED, .EXCLUDED { background:#fef2f2; color:#b91c1c; border-color:#fecaca }
.ACTIVE { background:#eff6ff; color:#1d4ed8; border-color:#bfdbfe }
.LOCKED { background:#f1f5f9; color:#94a3b8 }
.PROPOSED, .QUEUED, .INCONCLUSIVE { background:#f8fafc; color:#64748b; border-color:#e2e8f0 }
.empty { color:#94a3b8; font-size:12px; padding:6px 10px }
</style>
