<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Copy, GitCommitHorizontal, GitPullRequest, FileText, CheckCircle2, XCircle, Clock, AlertTriangle } from 'lucide-vue-next'
import { useTaskDetailSections } from '@/composables/useTaskDetailSections'
import type { Evidence, TaskFinalSummary } from '@/types/workspaceAssets'

const props = defineProps<{
  visible: boolean
  evidenceId: string | null
  workspaceId: string
  taskId: string
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

const { t } = useI18n()
const sections = useTaskDetailSections()

const loading = ref(false)
const evidence = ref<Evidence | null>(null)
const finalSummary = ref<TaskFinalSummary | null>(null)

watch(() => props.visible, async (isOpen) => {
  if (isOpen && props.evidenceId) {
    loading.value = true
    evidence.value = null
    finalSummary.value = null
    try {
      const [ev, summary] = await Promise.all([
        sections.loadEvidenceDetail(props.workspaceId, props.taskId, props.evidenceId),
        sections.loadFinalSummary(props.workspaceId, props.taskId).catch(() => null),
      ])
      evidence.value = ev
      finalSummary.value = summary
    } catch {
      evidence.value = null
    } finally {
      loading.value = false
    }
  }
})

function close() {
  emit('update:visible', false)
}

const statusColor = (status?: string | null) => {
  const s = (status || '').toUpperCase()
  if (s === 'CONFIRMED') return '#10b981'
  if (s === 'REJECTED') return '#ef4444'
  return '#f59e0b'
}

const typeColor = (et?: string | null) => {
  const u = (et || '').toUpperCase()
  if (u === 'CODE') return '#3b82f6'
  if (u === 'FAILURE') return '#ef4444'
  if (u === 'HUMAN_CONFIRMATION') return '#10b981'
  if (u === 'TEST') return '#8b5cf6'
  if (u === 'RUNTIME') return '#f59e0b'
  return '#64748b'
}

const sourceTypeLabel = (st?: string | null) => {
  const map: Record<string, string> = {
    COMMIT: 'Commit',
    MR: 'MR/PR',
    DIFF: 'Diff',
    FILE_PATH: 'File',
    TEST_REPORT: 'Test',
    REVIEW_RECORD: 'Review',
    RUN_LOG: 'Log',
    HUMAN_CONFIRMATION: 'Confirm',
    OTHER: 'Other',
  }
  const u = (st || '').toUpperCase()
  return map[u] || st || '—'
}

const closeoutMeta = computed(() => {
  const meta = evidence.value?.source?.source_metadata
  if (!meta || !meta.kind || !(meta.kind as string).startsWith('closeout_')) return null
  return meta as { kind: string; landing_method?: string }
})

const landingMethodLabel = computed(() => {
  const method = closeoutMeta.value?.landing_method
  if (!method) return null
  const map: Record<string, string> = {
    AI_IMPLEMENTED: t('chat.closeout.landing.ai_implemented'),
    HUMAN_ADJUSTED: t('chat.closeout.landing.human_adjusted'),
    AI_REWRITTEN: t('chat.closeout.landing.ai_rewritten'),
    AI_REFERENCE_ONLY: t('chat.closeout.landing.ai_reference_only'),
  }
  return map[method] || method
})

const failureInfo = computed(() => {
  const risk = finalSummary.value?.remaining_risk
  if (!risk) return null
  const stageMatch = risk.match(/Failure stage:\s*([^;]+)/)
  const reasonMatch = risk.match(/reason:\s*([^.]+)/)
  if (!stageMatch && !reasonMatch) return null
  const stage = stageMatch?.[1]?.trim()
  const reason = reasonMatch?.[1]?.trim()
  const stageMap: Record<string, string> = {
    AI_SOLUTION: t('chat.closeout.failure_stage_options.ai_solution'),
    CODING: t('chat.closeout.failure_stage_options.coding'),
    COMPILE: t('chat.closeout.failure_stage_options.compile'),
    PACKAGE: t('chat.closeout.failure_stage_options.package'),
    DEVICE_TEST: t('chat.closeout.failure_stage_options.device_test'),
    INTEGRATION: t('chat.closeout.failure_stage_options.integration'),
    REQUIREMENT_CLARIFICATION: t('chat.closeout.failure_stage_options.requirement_clarification'),
    OTHER: t('chat.closeout.failure_stage_options.other'),
  }
  const reasonMap: Record<string, string> = {
    AI_DIRECTION_WRONG: t('chat.closeout.failure_reason_options.ai_direction_wrong'),
    PROJECT_CONTEXT_INSUFFICIENT: t('chat.closeout.failure_reason_options.project_context_insufficient'),
    COMPILE_ERROR: t('chat.closeout.failure_reason_options.compile_error'),
    PACKAGE_ERROR: t('chat.closeout.failure_reason_options.package_error'),
    DEVICE_TEST_FAILED: t('chat.closeout.failure_reason_options.device_test_failed'),
    API_UNCLEAR: t('chat.closeout.failure_reason_options.api_unclear'),
    REQUIREMENT_UNCLEAR: t('chat.closeout.failure_reason_options.requirement_unclear'),
    ENVIRONMENT_ISSUE: t('chat.closeout.failure_reason_options.environment_issue'),
    OTHER: t('chat.closeout.failure_reason_options.other'),
  }
  return {
    stage: stage ? (stageMap[stage] || stage) : null,
    reason: reason ? (reasonMap[reason] || reason) : null,
  }
})

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(t('workspace_assets.task_detail.workbench.evidence_card.copied'))
  } catch {
    ElMessage.error(t('workspace_assets.task_detail.workbench.evidence_card.copy_failed'))
  }
}

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleString()
}

function hasSourceInfo(e: Evidence): boolean {
  return !!(e.source?.source_ref || e.source?.source_uri || e.source?.source_path || e.source?.source_label)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="t('workspace_assets.task_detail.workbench.evidence_detail.title')"
    width="560px"
    append-to-body
    destroy-on-close
    @close="close"
  >
    <div v-if="loading" class="detail-loading">
      <el-skeleton :rows="4" animated />
    </div>

    <div v-else-if="evidence" class="detail-content">
      <div class="detail-header">
        <span class="type-badge" :style="{ background: typeColor(evidence.evidence_type) }">{{ evidence.evidence_type }}</span>
        <span class="status-chip" :style="{ color: statusColor(evidence.status), borderColor: statusColor(evidence.status) }">
          <CheckCircle2 v-if="evidence.status?.toUpperCase() === 'CONFIRMED'" :size="12" />
          <XCircle v-else-if="evidence.status?.toUpperCase() === 'REJECTED'" :size="12" />
          <Clock v-else :size="12" />
          {{ evidence.status }}
        </span>
      </div>

      <h3 class="detail-title">{{ evidence.title || t('workspace_assets.task_detail.workbench.evidence_card.untitled') }}</h3>

      <div v-if="evidence.summary" class="detail-section">
        <label>{{ t('workspace_assets.task_detail.workbench.evidence_detail.summary') }}</label>
        <p class="detail-summary">{{ evidence.summary }}</p>
      </div>

      <div v-if="landingMethodLabel" class="detail-section">
        <label>{{ t('chat.closeout.landing_method') }}</label>
        <div class="closeout-info-row">
          <span class="closeout-value">{{ landingMethodLabel }}</span>
        </div>
      </div>

      <div v-if="failureInfo" class="detail-section">
        <label>
          <AlertTriangle :size="12" class="failure-icon" />
          {{ t('workspace_assets.task_detail.workbench.evidence_detail.failure_info') }}
        </label>
        <div class="failure-info-grid">
          <div v-if="failureInfo.stage" class="failure-info-item">
            <span class="failure-label">{{ t('chat.closeout.failure_stage') }}</span>
            <span class="failure-value">{{ failureInfo.stage }}</span>
          </div>
          <div v-if="failureInfo.reason" class="failure-info-item">
            <span class="failure-label">{{ t('chat.closeout.failure_reason') }}</span>
            <span class="failure-value">{{ failureInfo.reason }}</span>
          </div>
        </div>
      </div>

      <div v-if="hasSourceInfo(evidence)" class="detail-section">
        <label>{{ t('workspace_assets.task_detail.workbench.evidence_detail.source_info') }}</label>
        <div class="source-detail-grid">
          <div class="source-detail-row">
            <span class="source-label">{{ t('workspace_assets.task_detail.workbench.evidence_detail.source_type') }}</span>
            <span class="source-value">{{ sourceTypeLabel(evidence.source?.source_type) }}</span>
          </div>
          <div v-if="evidence.source?.source_ref" class="source-detail-row">
            <span class="source-label">
              <GitCommitHorizontal :size="12" />
              {{ t('workspace_assets.task_detail.workbench.evidence_detail.source_ref') }}
            </span>
            <span class="source-value mono">{{ evidence.source.source_ref }}</span>
            <button class="copy-btn" @click="copyText(evidence.source!.source_ref!)">
              <Copy :size="12" />
            </button>
          </div>
          <div v-if="evidence.source?.source_uri" class="source-detail-row">
            <span class="source-label">
              <GitPullRequest :size="12" />
              {{ t('workspace_assets.task_detail.workbench.evidence_detail.source_uri') }}
            </span>
            <a class="source-value link" :href="evidence.source.source_uri" target="_blank" rel="noopener">{{ evidence.source.source_uri }}</a>
            <button class="copy-btn" @click="copyText(evidence.source!.source_uri!)">
              <Copy :size="12" />
            </button>
          </div>
          <div v-if="evidence.source?.source_path" class="source-detail-row">
            <span class="source-label">
              <FileText :size="12" />
              {{ t('workspace_assets.task_detail.workbench.evidence_detail.source_path') }}
            </span>
            <span class="source-value mono">{{ evidence.source.source_path }}</span>
            <button class="copy-btn" @click="copyText(evidence.source!.source_path!)">
              <Copy :size="12" />
            </button>
          </div>
          <div v-if="evidence.source?.source_label" class="source-detail-row">
            <span class="source-label">{{ t('workspace_assets.task_detail.workbench.evidence_detail.source_label') }}</span>
            <span class="source-value">{{ evidence.source.source_label }}</span>
          </div>
        </div>
      </div>

      <div class="detail-section detail-meta">
        <div class="meta-grid">
          <div class="meta-item">
            <span class="meta-label">{{ t('workspace_assets.task_detail.workbench.evidence_detail.created_at') }}</span>
            <span class="meta-value">{{ formatDate(evidence.created_at) }}</span>
          </div>
          <div v-if="evidence.confirmed_at" class="meta-item">
            <span class="meta-label">{{ t('workspace_assets.task_detail.workbench.evidence_detail.confirmed_at') }}</span>
            <span class="meta-value">{{ formatDate(evidence.confirmed_at) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="detail-empty">
      {{ t('workspace_assets.task_detail.workbench.evidence_detail.load_failed') }}
    </div>

    <template #footer>
      <el-button @click="close">{{ t('common.close') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.detail-loading {
  padding: 8px 0;
}

.detail-content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.type-badge {
  font-size: 0.6875rem;
  font-weight: 700;
  color: #ffffff;
  padding: 0.125rem 0.5rem;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.6875rem;
  font-weight: 600;
  padding: 0.0625rem 0.5rem;
  border: 1px solid;
  border-radius: 10px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.detail-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: #0f172a;
}

.detail-section {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.detail-section label {
  font-size: 0.75rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.detail-summary {
  margin: 0;
  font-size: 0.875rem;
  color: #334155;
  line-height: 1.6;
  white-space: pre-wrap;
}

.closeout-info-row {
  padding: 0.5rem 0.75rem;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
}

.closeout-value {
  font-size: 0.875rem;
  font-weight: 600;
  color: #1e40af;
}

.failure-icon {
  color: #ef4444;
}

.failure-info-grid {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
}

.failure-info-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.failure-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #991b1b;
  min-width: 70px;
  flex-shrink: 0;
}

.failure-value {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #dc2626;
}

.source-detail-grid {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.625rem 0.75rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.source-detail-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.source-label {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  min-width: 80px;
  flex-shrink: 0;
}

.source-value {
  font-size: 0.8125rem;
  color: #0f172a;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-value.mono {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-weight: 600;
}

.source-value.link {
  color: #3b82f6;
  text-decoration: none;
}

.source-value.link:hover {
  text-decoration: underline;
}

.copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.1875rem;
  border: none;
  background: transparent;
  border-radius: 4px;
  cursor: pointer;
  color: #94a3b8;
  transition: all 0.15s;
  flex-shrink: 0;
}

.copy-btn:hover {
  background: #e2e8f0;
  color: #475569;
}

.detail-meta {
  padding-top: 0.75rem;
  border-top: 1px solid #e2e8f0;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.75rem;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.meta-label {
  font-size: 0.6875rem;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.meta-value {
  font-size: 0.8125rem;
  color: #334155;
}

.detail-empty {
  padding: 2rem;
  text-align: center;
  color: #94a3b8;
  font-style: italic;
}
</style>
