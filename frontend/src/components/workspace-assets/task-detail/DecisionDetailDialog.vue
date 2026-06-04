<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTaskDetailSections } from '@/composables/useTaskDetailSections'
import type { Decision } from '@/types/workspaceAssets'
import DecisionSourceLink from './DecisionSourceLink.vue'

const props = defineProps<{
  visible: boolean
  decisionId: string | null
  workspaceId: string
  taskId: string
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

const { t } = useI18n()
const sections = useTaskDetailSections()

const loading = ref(false)
const decision = ref<Decision | null>(null)

watch(() => props.visible, async (isOpen) => {
  if (isOpen && props.decisionId) {
    loading.value = true
    decision.value = null
    try {
      decision.value = await sections.loadDecisionDetail(props.workspaceId, props.taskId, props.decisionId)
    } catch {
      decision.value = null
    } finally {
      loading.value = false
    }
  }
})

function close() {
  emit('update:visible', false)
}

const statusTagType = (status?: string | null) => {
  const s = (status || '').toUpperCase()
  if (s === 'ACCEPTED') return 'success'
  if (s === 'PROPOSED') return ''
  if (s === 'REJECTED') return 'danger'
  if (s === 'SUPERSEDED') return 'info'
  return 'info'
}

const statusLabel = (status?: string | null) => {
  const s = (status || '').toUpperCase()
  const key = `workspace_assets.task_detail.workbench.status.${s.toLowerCase()}`
  const translated = t(key)
  return translated === key ? (status || '—') : translated
}

const sourceTypeLabel = (st?: string | null) => {
  const map: Record<string, string> = {
    CHAT_MESSAGE: 'Chat',
    SPEC_PLAN_CHANGE: 'Spec',
    TASK_CLOSEOUT: 'Closeout',
    TASK_DETAIL_BACKFILL: 'Backfill',
  }
  const u = (st || '').toUpperCase()
  return map[u] || st || '—'
}

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleString()
}

function hasRelatedLinks(d: Decision): boolean {
  return !!(d.requirement_id || d.human_delta_id || d.source_evidence_id)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="t('workspace_assets.task_detail.workbench.decision_detail.title')"
    width="600px"
    append-to-body
    destroy-on-close
    @close="close"
  >
    <div v-if="loading" class="detail-loading">
      <el-skeleton :rows="5" animated />
    </div>

    <div v-else-if="decision" class="detail-content">
      <div class="detail-header">
        <el-tag :type="statusTagType(decision.status)" size="small" effect="dark">
          {{ statusLabel(decision.status) }}
        </el-tag>
        <el-tag v-if="decision.promote_candidate" type="success" size="small" effect="plain">
          {{ t('workspace_assets.task_detail.workbench.decision_detail.promote_candidate') }}
        </el-tag>
      </div>

      <h3 class="detail-title">{{ decision.title }}</h3>

      <div v-if="decision.body" class="detail-section">
        <label>{{ t('workspace_assets.task_detail.workbench.decision_detail.body_label') }}</label>
        <p class="detail-summary">{{ decision.body }}</p>
      </div>

      <div v-if="decision.rationale" class="detail-section">
        <label>{{ t('workspace_assets.task_detail.workbench.decision_detail.rationale_label') }}</label>
        <p class="detail-summary">{{ decision.rationale }}</p>
      </div>

      <div v-if="decision.impact_scope" class="detail-section">
        <label>{{ t('workspace_assets.task_detail.workbench.decision_detail.impact_scope_label') }}</label>
        <p class="detail-summary">{{ decision.impact_scope }}</p>
      </div>

      <div v-if="decision.source" class="detail-section">
        <label>{{ t('workspace_assets.task_detail.workbench.decision_detail.source_info') }}</label>
        <div class="source-detail-grid">
          <div class="source-detail-row">
            <span class="source-label">{{ sourceTypeLabel(decision.source.source_type) }}</span>
            <DecisionSourceLink
              :source="decision.source"
              :workspace-id="props.workspaceId"
              :task-id="props.taskId"
            />
          </div>
        </div>
      </div>

      <div v-if="hasRelatedLinks(decision)" class="detail-section">
        <label>{{ t('workspace_assets.task_detail.workbench.decision_detail.related_links') }}</label>
        <div class="related-grid">
          <div v-if="decision.requirement_id" class="source-detail-row">
            <span class="source-label">{{ t('workspace_assets.task_detail.workbench.decision_detail.requirement') }}</span>
            <span class="source-value mono">{{ decision.requirement_id }}</span>
          </div>
          <div v-if="decision.human_delta_id" class="source-detail-row">
            <span class="source-label">{{ t('workspace_assets.task_detail.workbench.decision_detail.human_delta') }}</span>
            <span class="source-value mono">{{ decision.human_delta_id }}</span>
          </div>
          <div v-if="decision.source_evidence_id" class="source-detail-row">
            <span class="source-label">{{ t('workspace_assets.task_detail.workbench.decision_detail.source_evidence') }}</span>
            <span class="source-value mono">{{ decision.source_evidence_id }}</span>
          </div>
        </div>
      </div>

      <div v-if="decision.delta_line_refs?.length" class="detail-section">
        <label>{{ t('workspace_assets.task_detail.workbench.decision_detail.line_refs') }}</label>
        <div class="line-refs-list">
          <span
            v-for="(ref, idx) in decision.delta_line_refs"
            :key="idx"
            class="line-ref-tag"
          >
            {{ ref.file_path }}#L{{ ref.line_start }}-L{{ ref.line_end }}
          </span>
        </div>
      </div>

      <div class="detail-section detail-meta">
        <div class="meta-grid">
          <div v-if="decision.decided_by_id" class="meta-item">
            <span class="meta-label">{{ t('workspace_assets.task_detail.workbench.decision_detail.decided_by') }}</span>
            <span class="meta-value">{{ decision.decided_by_id }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">{{ t('workspace_assets.task_detail.workbench.decision_detail.created_at') }}</span>
            <span class="meta-value">{{ formatDate(decision.created_at) }}</span>
          </div>
          <div v-if="decision.updated_at" class="meta-item">
            <span class="meta-label">{{ t('workspace_assets.task_detail.workbench.decision_detail.updated_at') }}</span>
            <span class="meta-value">{{ formatDate(decision.updated_at) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="detail-empty">
      {{ t('workspace_assets.task_detail.workbench.decision_detail.load_failed') }}
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

.source-detail-grid {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.625rem 0.75rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.related-grid {
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

.line-refs-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.line-ref-tag {
  display: inline-block;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.125rem 0.5rem;
  background: #dbeafe;
  color: #1d4ed8;
  border-radius: 4px;
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
