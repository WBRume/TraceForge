<script setup lang="ts">
import { computed, proxyRefs } from 'vue'
import { AlertTriangle, CheckCircle2, FileSearch, FileText, Loader2, RefreshCw, Shield, Zap, BarChart3, Clock, AlertCircle } from 'lucide-vue-next'
import SkillAnalysisRiskDetail from '@/components/skill-editor/SkillAnalysisRiskDetail.vue'
import SkillAnalysisRiskList from '@/components/skill-editor/SkillAnalysisRiskList.vue'
import type { SkillEditorViewModel } from '@/composables/useSkillEditorViewModel'
import type { SkillAnalysisLevel } from '@/types/skillAnalysis'

const props = defineProps<{ vm: SkillEditorViewModel }>()
const vm = proxyRefs(props.vm)

const analysis = computed(() => vm.latestAnalysis)
const fileStats = computed(() => analysis.value?.file_stats || {})
const distribution = computed(() => (
  Object.entries(analysis.value?.file_type_distribution || {})
    .sort(([, a], [, b]) => Number(b) - Number(a))
))
const keyFiles = computed(() => analysis.value?.key_files || [])
const riskItems = computed(() => analysis.value?.risk_items || [])
const suggestions = computed(() => analysis.value?.review_suggestions || [])
const activeRiskKey = computed(() => vm.activeAnalysisRiskKey || '')
const highRiskCount = computed(() => (
  riskItems.value.filter(item => item.risk_level === 'HIGH').length
))
const scriptCount = computed(() => Number(fileStats.value.script_files || 0))
const totalFiles = computed(() => Number(fileStats.value.total_files || 0))

const overviewItems = computed(() => [
  { label: '风险等级', value: analysis.value?.risk_level || '-', tone: analysis.value?.risk_level || 'LOW', icon: Shield },
  { label: '复杂度', value: analysis.value?.complexity || '-', tone: analysis.value?.complexity || 'LOW', icon: Zap },
  { label: '审阅优先级', value: analysis.value?.review_priority || '-', tone: analysis.value?.review_priority || 'LOW', icon: Clock },
  { label: '文件总数', value: String(totalFiles.value), tone: 'LOW', icon: FileText },
  { label: '脚本数量', value: String(scriptCount.value), tone: scriptCount.value > 0 ? 'MEDIUM' : 'LOW', icon: BarChart3 },
  { label: '高风险项', value: String(highRiskCount.value), tone: highRiskCount.value > 0 ? 'HIGH' : 'LOW', icon: AlertCircle },
])

const levelClass = (level?: SkillAnalysisLevel | string | null) => {
  const normalized = String(level || 'LOW').toLowerCase()
  return ['low', 'medium', 'high'].includes(normalized) ? normalized : 'low'
}

const statusText = computed(() => {
  const status = analysis.value?.status
  if (!status) return '尚未分析'
  if (status === 'PENDING') return '排队中'
  if (status === 'RUNNING') return '分析中'
  if (status === 'SUCCESS') return '已完成'
  return '分析失败'
})

const statusClass = computed(() => {
  const status = analysis.value?.status
  if (status === 'SUCCESS') return 'success'
  if (status === 'FAILED') return 'failed'
  if (status === 'PENDING' || status === 'RUNNING') return 'running'
  return 'idle'
})

const runButtonText = computed(() => {
  if (vm.analysisRunning) return '分析中'
  return analysis.value ? '重新分析' : '开始分析'
})

const openFile = async (path?: string | null) => {
  const target = String(path || '').trim()
  if (!target) return
  await vm.openAnalysisFile(target)
}

const openRisk = async (riskKey: string) => {
  await vm.goAnalysisRiskDetail(riskKey)
}
</script>

<template>
  <section class="analysis-container">
    <header class="analysis-hero">
      <div class="hero-left">
        <div class="badge-tag sm pulse-on-hover">
          <span class="pulse-dot"></span>
          STATIC ANALYSIS
        </div>
        <h2 class="hero-title">静态包摘要与审阅重点</h2>
        <p class="hero-desc">智能识别核心风险与审阅建议，优化工作流效率。</p>
      </div>
      <div class="hero-right">
        <button
          class="btn-run-analysis"
          :class="{ 'is-running': vm.analysisRunning }"
          :disabled="vm.analysisRunning || !vm.canManage"
          @click="vm.runAnalysis()"
        >
          <div class="btn-content">
            <Loader2 v-if="vm.analysisRunning" class="w-5 h-5 animate-spin" />
            <RefreshCw v-else class="w-5 h-5" />
            <span>{{ runButtonText }}</span>
          </div>
          <div class="btn-glow"></div>
        </button>
      </div>
    </header>

    <div class="status-banner" :class="statusClass">
      <div class="status-info">
        <Loader2 v-if="vm.analysisLoading || vm.analysisRunning" class="w-4 h-4 animate-spin" />
        <CheckCircle2 v-else-if="analysis?.status === 'SUCCESS'" class="w-4 h-4" />
        <AlertTriangle v-else-if="analysis?.status === 'FAILED'" class="w-4 h-4" />
        <FileSearch v-else class="w-4 h-4" />
        <span class="status-label">{{ statusText }}</span>
        <span v-if="analysis?.progress !== undefined" class="progress-val">{{ analysis.progress }}%</span>
      </div>
      <div v-if="analysis?.progress !== undefined" class="progress-track">
        <div class="progress-fill" :style="{ width: `${analysis.progress}%` }"></div>
      </div>
    </div>

    <div v-if="analysis?.error_message" class="error-panel">
      <AlertTriangle class="w-5 h-5" />
      <p>{{ analysis.error_message }}</p>
    </div>

    <div v-if="!analysis && !vm.analysisLoading" class="empty-state-panel glass-card">
      <FileSearch class="w-12 h-12 text-slate-300" />
      <h3>暂无分析数据</h3>
      <p>手动运行分析以获取包摘要信息。</p>
    </div>

    <template v-if="analysis">
      <!-- Bento Grid for Metrics - Optimized for Density -->
      <div class="bento-grid">
        <div v-for="item in overviewItems" :key="item.label" class="bento-card" :class="levelClass(item.tone)">
          <div class="card-top">
            <div class="card-icon">
              <component :is="item.icon" class="w-4 h-4" />
            </div>
            <span class="card-label">{{ item.label }}</span>
          </div>
          <div class="card-body">
            <strong class="card-value">{{ item.value }}</strong>
          </div>
          <div class="card-bg-glow"></div>
        </div>
      </div>

      <div class="analysis-main-layout">
        <div class="layout-side">
          <section class="glass-section compact">
            <div class="section-head">
              <FileText class="w-4 h-4" />
              <h3>文件类型分布</h3>
            </div>
            <div v-if="distribution.length" class="type-pills">
              <div v-for="[type, count] in distribution" :key="type" class="type-pill">
                <span class="type-ext">{{ type }}</span>
                <span class="type-count">{{ count }}</span>
              </div>
            </div>
            <p v-else class="empty-hint">暂无统计。</p>
          </section>

          <section class="glass-section compact">
            <div class="section-head">
              <CheckCircle2 class="w-4 h-4" />
              <h3>核心审阅建议</h3>
            </div>
            <ul v-if="suggestions.length" class="modern-suggestion-list">
              <li v-for="item in suggestions" :key="item">
                <div class="suggestion-bullet"></div>
                <span>{{ item }}</span>
              </li>
            </ul>
            <p v-else class="empty-hint">暂无建议。</p>
          </section>
        </div>

        <div class="layout-main">
          <section class="glass-section">
            <div class="section-head">
              <FileSearch class="w-4 h-4" />
              <h3>关键文件列表</h3>
            </div>
            <div v-if="keyFiles.length" class="premium-table-wrapper">
              <table class="premium-table">
                <thead>
                  <tr>
                    <th>文件路径</th>
                    <th>角色</th>
                    <th>风险</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="file in keyFiles"
                    :key="String(file.path)"
                    class="clickable-row"
                    @click="openFile(String(file.path || ''))"
                  >
                    <td class="path-cell">{{ file.path }}</td>
                    <td><span class="role-badge">{{ file.role || 'KEY_FILE' }}</span></td>
                    <td>
                      <span :class="['level-tag', levelClass(file.risk_level)]">
                        {{ file.risk_level || 'LOW' }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="empty-hint">未识别到关键文件。</p>
          </section>
        </div>
      </div>

      <div class="analysis-footer-note">
        <Shield class="w-3.5 h-3.5" />
        <span>分析结果仅供审阅参考，不代表完整安全结论。</span>
      </div>

      <!-- Risk Sub-panels -->
      <div class="risk-integration-zone">
        <SkillAnalysisRiskDetail
          v-if="activeRiskKey"
          :risks="riskItems"
          :risk-key="activeRiskKey"
          @back="vm.goEditorAnalysisTab()"
          @open-file="openFile"
          @open-risk="openRisk"
        />
        <SkillAnalysisRiskList
          v-else
          :risks="riskItems"
          @open-risk="openRisk"
        />
      </div>
    </template>
  </section>
</template>

<style scoped src="@/styles/skill-editor/skill-editor-shared.css"></style>
<style scoped>
.analysis-container {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  width: 100%;
  animation: fade-in 0.5s ease-out;
  padding-bottom: 2rem;
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Hero Section */
.analysis-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.25rem 0;
}

.hero-left {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.hero-title {
  margin: 0;
  font-family: 'Poppins', 'Outfit', sans-serif;
  font-size: 1.5rem;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.015em;
}

.hero-desc {
  margin: 0;
  color: #64748b;
  font-size: 0.85rem;
}

/* Run Button */
.btn-run-analysis {
  position: relative;
  padding: 2px;
  background: linear-gradient(135deg, #0ea5e9, #3b82f6);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.btn-content {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 1.25rem;
  background: #0ea5e9;
  color: white;
  border-radius: 10px;
  font-weight: 700;
  font-size: 0.9rem;
}

.btn-run-analysis:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 15px -4px rgba(14, 165, 233, 0.3);
}

/* Status Banner */
.status-banner {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 0.75rem 1rem;
  border-radius: 12px;
  background: white;
  border: 1px solid #e2e8f0;
}

.status-info {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-weight: 700;
  font-size: 0.85rem;
}

/* Bento Grid - Optimized */
.bento-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
}

.bento-card {
  position: relative;
  padding: 1rem;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  overflow: hidden;
  transition: all 0.25s ease;
}

.bento-card:hover {
  transform: translateY(-2px);
  border-color: #bae6fd;
  box-shadow: 0 10px 15px -3px rgba(15, 23, 42, 0.05);
}

.card-top {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.card-icon {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #f8fafc;
  color: #64748b;
}

.card-label {
  font-size: 0.7rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.025em;
}

.card-value {
  font-size: 1.15rem;
  font-weight: 800;
  color: #0f172a;
}

.bento-card.high .card-value { color: #ef4444; }
.bento-card.medium .card-value { color: #f59e0b; }

/* Main Layout - Better Spacing */
.analysis-main-layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 1.25rem;
}

.glass-section {
  padding: 1.25rem;
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(226, 232, 240, 0.7);
  border-radius: 20px;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  min-height: 0;
}

.glass-section.compact {
  padding: 1rem;
}

.section-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: #334155;
  border-bottom: 1px solid rgba(226, 232, 240, 0.5);
  padding-bottom: 0.5rem;
  margin-bottom: 0.25rem;
}

.section-head h3 {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 800;
}

/* Premium Table Compact */
.premium-table-wrapper {
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  overflow: hidden;
}

.premium-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.premium-table th {
  padding: 0.75rem 1rem;
  background: #f8fafc;
  color: #64748b;
  font-weight: 700;
  text-align: left;
}

.premium-table td {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #f1f5f9;
}

.path-cell {
  font-weight: 600;
  color: #1e293b;
  word-break: break-all;
}

.analysis-footer-note {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  padding: 0.5rem;
  color: #94a3b8;
  font-size: 0.75rem;
}

@media (max-width: 1024px) {
  .analysis-main-layout { grid-template-columns: 1fr; }
}
</style>
