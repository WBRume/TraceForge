<script setup lang="ts">
import { computed } from 'vue'
import { ArrowLeft, ArrowRight, ExternalLink, ShieldAlert, Target, Info, FileCode2, Lightbulb, ClipboardList } from 'lucide-vue-next'
import type { SkillAnalysisLevel, SkillAnalysisRiskItem } from '@/types/skillAnalysis'
import {
  fallbackRiskKey,
  formatConfidence,
  riskDetail,
  riskLocation,
  riskRecommendation,
  riskSummary,
  riskTitle,
} from '@/utils/skillAnalysisRisk'

const props = defineProps<{
  risks: SkillAnalysisRiskItem[]
  riskKey: string
}>()

const emit = defineEmits<{
  back: []
  openFile: [path: string]
  openRisk: [riskKey: string]
}>()

const rows = computed(() => props.risks.map((risk, index) => ({
  risk,
  key: fallbackRiskKey(risk, index),
})))

const activeIndex = computed(() => rows.value.findIndex(row => row.key === props.riskKey))
const activeRow = computed(() => rows.value[activeIndex.value] || null)
const activeRisk = computed(() => activeRow.value?.risk || null)
const previousRow = computed(() => activeIndex.value > 0 ? rows.value[activeIndex.value - 1] : null)
const nextRow = computed(() => activeIndex.value >= 0 && activeIndex.value < rows.value.length - 1 ? rows.value[activeIndex.value + 1] : null)

const levelClass = (level?: SkillAnalysisLevel | string | null) => {
  const normalized = String(level || 'LOW').toLowerCase()
  return ['low', 'medium', 'high'].includes(normalized) ? normalized : 'low'
}
</script>

<template>
  <section class="risk-detail-wrapper">
    <nav class="detail-nav-bar glass-panel">
      <button class="btn-back" type="button" @click="emit('back')">
        <ArrowLeft class="w-4 h-4" />
        <span>返回列表</span>
      </button>
      
      <div class="nav-pagination">
        <button
          class="nav-step-btn"
          :disabled="!previousRow"
          @click="previousRow && emit('openRisk', previousRow.key)"
        >
          <ArrowLeft class="w-4 h-4" />
        </button>
        <span class="pagination-info">{{ activeIndex + 1 }} / {{ rows.length }}</span>
        <button
          class="nav-step-btn"
          :disabled="!nextRow"
          @click="nextRow && emit('openRisk', nextRow.key)"
        >
          <ArrowRight class="w-4 h-4" />
        </button>
      </div>

      <button class="btn-locate-file" type="button" @click="activeRisk && emit('openFile', activeRisk.file_path)">
        <ExternalLink class="w-4 h-4" />
        <span>定位代码</span>
      </button>
    </nav>

    <template v-if="activeRisk">
      <header class="detail-hero">
        <div class="hero-main">
          <span :class="['risk-glow-pill lg', levelClass(activeRisk.risk_level)]">
            <span class="dot"></span>
            {{ activeRisk.risk_level }} RISK
          </span>
          <h2 class="detail-title">{{ riskTitle(activeRisk) }}</h2>
        </div>
      </header>

      <div class="detail-content-layout">
        <!-- Sidebar Column -->
        <aside class="detail-sidebar">
          <section class="content-card metadata-card">
            <div class="card-head">
              <Info class="w-5 h-5 text-blue-500" />
              <h3>风险概览</h3>
            </div>
            <div class="meta-stack">
              <div class="meta-item">
                <span class="meta-label">文件位置</span>
                <strong class="meta-value">{{ riskLocation(activeRisk) }}</strong>
              </div>
              <div class="meta-item">
                <span class="meta-label">风险类型</span>
                <strong class="meta-value">{{ activeRisk.risk_type }}</strong>
              </div>
              <div class="meta-item">
                <span class="meta-label">分析置信度</span>
                <strong class="meta-value">{{ formatConfidence(activeRisk.confidence) }}</strong>
              </div>
              <div class="meta-item">
                <span class="meta-label">来源库</span>
                <strong class="meta-value">{{ activeRisk.source || '-' }}</strong>
              </div>
            </div>
          </section>

          <section class="content-card info-card">
            <div class="card-head">
              <ShieldAlert class="w-5 h-5 text-indigo-500" />
              <h3>风险说明</h3>
            </div>
            <p class="card-text">{{ activeRisk.description || riskSummary(activeRisk) }}</p>
          </section>

          <section class="content-card suggestion-card">
            <div class="card-head">
              <Lightbulb class="w-5 h-5 text-amber-500" />
              <h3>审阅建议</h3>
            </div>
            <div class="suggestion-box">
              <p class="card-text">{{ riskRecommendation(activeRisk) }}</p>
            </div>
          </section>
        </aside>

        <!-- Main Column -->
        <main class="detail-main-content">
          <section class="content-card evidence-summary-card">
            <div class="card-head">
              <ClipboardList class="w-5 h-5 text-emerald-500" />
              <h3>证据摘要</h3>
            </div>
            <p class="card-text evidence-summary">{{ riskSummary(activeRisk) }}</p>
          </section>

          <section class="content-card dark-code-card">
            <div class="card-head">
              <FileCode2 class="w-5 h-5 text-slate-400" />
              <h3>详细证据</h3>
            </div>
            <div class="code-container custom-scrollbar">
              <pre><code>{{ riskDetail(activeRisk) }}</code></pre>
            </div>
          </section>

          <section v-if="activeRisk.matched_text || activeRisk.evidence" class="content-card dark-code-card">
            <div class="card-head">
              <Target class="w-5 h-5 text-red-400" />
              <h3>命中代码片段</h3>
            </div>
            <div class="code-container custom-scrollbar highlight">
              <pre><code>{{ activeRisk.matched_text || activeRisk.evidence }}</code></pre>
            </div>
          </section>
        </main>
      </div>
    </template>

    <div v-else class="not-found-state glass-panel">
      <ShieldAlert class="w-12 h-12 text-slate-300" />
      <p>未找到该风险项，可能分析结果已刷新。</p>
      <button class="btn-outline-sm" @click="emit('back')">返回风险列表</button>
    </div>
  </section>
</template>

<style scoped src="@/styles/skill-editor/skill-editor-shared.css"></style>
<style scoped>
.risk-detail-wrapper {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  animation: slide-up 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  min-width: 0; /* Important for grid/flex sizing */
}

@keyframes slide-up {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Nav Bar */
.detail-nav-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1.25rem;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(226, 232, 240, 0.8);
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.nav-pagination {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.25rem 0.5rem;
  background: #f1f5f9;
  border-radius: 999px;
}

.nav-step-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: none;
  background: white;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 1px 2px rgba(0,0,0,0.1);
}

.nav-step-btn:hover:not(:disabled) {
  background: #0ea5e9;
  color: white;
}

.nav-step-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.pagination-info {
  font-size: 0.75rem;
  font-weight: 700;
  color: #475569;
  font-variant-numeric: tabular-nums;
}

.btn-back, .btn-locate-file {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border-radius: 10px;
  font-size: 0.85rem;
  font-weight: 700;
  border: 1px solid #e2e8f0;
  background: white;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-back:hover { background: #f8fafc; border-color: #cbd5e1; }
.btn-locate-file { background: #0ea5e9; color: white; border: none; }
.btn-locate-file:hover { background: #0284c7; transform: translateY(-1px); }

/* Hero Section */
.detail-hero {
  padding: 0.5rem 0.25rem;
}

.hero-main {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.detail-title {
  margin: 0;
  font-size: 1.65rem;
  font-weight: 800;
  color: #0f172a;
  line-height: 1.3;
  letter-spacing: -0.01em;
}

.risk-glow-pill.lg {
  padding: 0.4rem 1.25rem;
  font-size: 0.85rem;
}

/* New Sidebar Layout */
.detail-content-layout {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 1.5rem;
  align-items: start;
}

.detail-sidebar {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  position: sticky;
  top: 80px;
}

.detail-main-content {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  min-width: 0; /* Crucial for overflow handling */
}

/* Content Cards */
.content-card {
  padding: 1.5rem;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 24px;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.02);
  min-width: 0;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 0.75rem;
}

.card-head h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 800;
  color: #1e293b;
  text-transform: uppercase;
  letter-spacing: 0.025em;
}

.card-text {
  margin: 0;
  font-size: 0.925rem;
  line-height: 1.7;
  color: #475569;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
}

/* Metadata Stack */
.meta-stack {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.meta-label {
  font-size: 0.7rem;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.meta-value {
  font-size: 0.9rem;
  font-weight: 700;
  color: #1e293b;
  word-break: break-all;
}

/* Suggestion Box */
.suggestion-box {
  padding: 1.25rem;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 18px;
  box-shadow: inset 0 2px 4px rgba(251, 191, 36, 0.05);
}

.suggestion-box .card-text {
  color: #92400e;
  font-weight: 500;
}

/* Dark Code Card - Improved for overflow */
.dark-code-card {
  background: #0f172a;
  border: 1px solid #1e293b;
}

.dark-code-card .card-head {
  border-color: #1e293b;
}

.dark-code-card .card-head h3 {
  color: #94a3b8;
}

.code-container {
  background: #1e293b;
  border-radius: 16px;
  padding: 1.25rem;
  max-height: 500px;
  overflow: auto;
  border: 1px solid #334155;
}

.code-container pre {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  line-height: 1.6;
  color: #cbd5e1;
  white-space: pre-wrap; /* Crucial fix */
  word-break: break-all; /* Crucial fix */
  overflow-wrap: anywhere;
}

.code-container.highlight {
  border-color: rgba(239, 68, 68, 0.3);
  background: #2a1b1b;
}

.code-container.highlight pre code {
  color: #fda4af;
}

/* Evidence Summary specific */
.evidence-summary {
  font-weight: 500;
  color: #334155;
  border-left: 4px solid #10b981;
  padding-left: 1rem;
}

/* State Handlers */
.not-found-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1.5rem;
  padding: 8rem 2rem;
  text-align: center;
}

.not-found-state p {
  color: #64748b;
  font-weight: 600;
}

/* Risk Badges */
.risk-glow-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.25rem 0.85rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 800;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  width: max-content;
}

.risk-glow-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.risk-glow-pill.high { background: #fee2e2; color: #ef4444; box-shadow: 0 0 12px rgba(239, 68, 68, 0.2); }
.risk-glow-pill.medium { background: #fef3c7; color: #f59e0b; box-shadow: 0 0 12px rgba(245, 158, 11, 0.2); }
.risk-glow-pill.low { background: #f1f5f9; color: #64748b; }

/* Responsive */
@media (max-width: 1100px) {
  .detail-content-layout { grid-template-columns: 1fr; }
  .detail-sidebar { position: static; }
}

@media (max-width: 640px) {
  .detail-nav-bar { flex-direction: column; gap: 1rem; }
  .detail-metrics-grid { grid-template-columns: 1fr; }
}
</style>
