<script setup lang="ts">
import { computed } from 'vue'
import { ChevronRight, ShieldAlert, Target, Info, CheckCircle2 } from 'lucide-vue-next'
import type { SkillAnalysisLevel, SkillAnalysisRiskItem } from '@/types/skillAnalysis'
import { fallbackRiskKey, formatConfidence, riskLocation, riskSummary, riskTitle } from '@/utils/skillAnalysisRisk'

const props = defineProps<{
  risks: SkillAnalysisRiskItem[]
}>()

const emit = defineEmits<{
  openRisk: [riskKey: string]
}>()

const rows = computed(() => props.risks.map((risk, index) => ({
  risk,
  key: fallbackRiskKey(risk, index),
  title: riskTitle(risk),
  location: riskLocation(risk),
  summary: riskSummary(risk),
  confidence: formatConfidence(risk.confidence),
})))

const levelClass = (level?: SkillAnalysisLevel | string | null) => {
  const normalized = String(level || 'LOW').toLowerCase()
  return ['low', 'medium', 'high'].includes(normalized) ? normalized : 'low'
}
</script>

<template>
  <section class="risk-list-container">
    <div class="risk-list-head">
      <div class="head-title">
        <ShieldAlert class="w-5 h-5 text-red-500" />
        <h3>具体风险项</h3>
      </div>
      <span class="risk-count">发现 {{ rows.length }} 个潜在问题</span>
    </div>

    <div v-if="rows.length" class="risk-grid">
      <div
        v-for="row in rows"
        :key="row.key"
        class="risk-card"
        :class="levelClass(row.risk.risk_level)"
        @click="emit('openRisk', row.key)"
      >
        <div class="risk-card-header">
          <span :class="['risk-glow-pill', levelClass(row.risk.risk_level)]">
            <span class="dot"></span>
            {{ row.risk.risk_level }}
          </span>
          <div class="risk-confidence">
            <Target class="w-3 h-3" />
            <span>{{ row.confidence }}</span>
          </div>
        </div>

        <div class="risk-card-body">
          <h4 class="risk-title">{{ row.title }}</h4>
          <p class="risk-summary">{{ row.summary }}</p>
        </div>

        <div class="risk-card-footer">
          <div class="risk-location">
            <Info class="w-3.5 h-3.5" />
            <span>{{ row.location }}</span>
          </div>
          <ChevronRight class="w-5 h-5 risk-nav-icon" />
        </div>
        
        <div class="card-glow-effect"></div>
      </div>
    </div>
    <div v-else class="empty-risk-state">
      <div class="empty-icon-shell">
        <CheckCircle2 class="w-8 h-8 text-green-500" />
      </div>
      <p>未发现显著风险项，代码质量良好。</p>
    </div>
  </section>
</template>

<style scoped src="@/styles/skill-editor/skill-editor-shared.css"></style>
<style scoped>
.risk-list-container {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  margin-top: 0.5rem;
}

.risk-list-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 0.15rem;
}

.head-title {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.head-title h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 800;
  color: #0f172a;
  text-transform: uppercase;
  letter-spacing: 0.025em;
}

.risk-count {
  font-size: 0.8rem;
  color: #64748b;
  font-weight: 600;
}

.risk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1rem;
}

.risk-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.25rem;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.risk-card:hover {
  transform: translateY(-4px);
  border-color: #bae6fd;
  box-shadow: 0 12px 20px -5px rgba(15, 23, 42, 0.06);
}

.risk-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* Glowing Badges */
.risk-glow-pill {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.2rem 0.65rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 800;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.risk-glow-pill .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.risk-glow-pill.high { background: #fee2e2; color: #ef4444; box-shadow: 0 0 10px rgba(239, 68, 68, 0.15); }
.risk-glow-pill.medium { background: #fef3c7; color: #f59e0b; box-shadow: 0 0 10px rgba(245, 158, 11, 0.15); }
.risk-glow-pill.low { background: #f1f5f9; color: #64748b; }

.risk-confidence {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  color: #94a3b8;
  font-size: 0.7rem;
  font-weight: 600;
}

.risk-card-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.risk-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 800;
  color: #0f172a;
  line-height: 1.4;
}

.risk-summary {
  margin: 0;
  font-size: 0.85rem;
  color: #475569;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.risk-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: auto;
  padding-top: 0.75rem;
  border-top: 1px solid #f8fafc;
}

.risk-location {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  color: #64748b;
  font-size: 0.7rem;
  font-weight: 700;
  max-width: 85%;
}

.risk-location span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.risk-nav-icon {
  color: #cbd5e1;
  transition: transform 0.3s;
}

.risk-card:hover .risk-nav-icon {
  color: #0ea5e9;
  transform: translateX(2px);
}

.card-glow-effect {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: radial-gradient(circle at top right, rgba(14, 165, 233, 0.04), transparent 70%);
  pointer-events: none;
}

.empty-risk-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  padding: 3rem;
  background: #f8fafc;
  border-radius: 20px;
  border: 1px dashed #e2e8f0;
}

.empty-icon-shell {
  width: 48px;
  height: 48px;
  background: white;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 6px rgba(0,0,0,0.03);
}

.empty-risk-state p {
  color: #64748b;
  font-weight: 600;
  font-size: 0.9rem;
}

@media (max-width: 768px) {
  .risk-grid { grid-template-columns: 1fr; }
}
</style>
