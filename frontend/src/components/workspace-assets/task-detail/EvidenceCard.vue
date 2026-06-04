<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Copy, GitCommitHorizontal, GitPullRequest, FileText, Info } from 'lucide-vue-next'
import type { EvidenceLight } from '@/types/workspaceAssets'

const props = defineProps<{
  evidence: EvidenceLight
  readonly?: boolean
}>()

const emit = defineEmits<{
  mutated: []
  'view-detail': [evidenceId: string]
}>()

const { t } = useI18n()

const statusColor = computed(() => {
  const s = props.evidence.status?.toUpperCase()
  if (s === 'CONFIRMED') return '#10b981'
  if (s === 'REJECTED') return '#ef4444'
  return '#f59e0b'
})

const typeColor = computed(() => {
  const et = props.evidence.evidence_type?.toUpperCase()
  if (et === 'CODE') return '#3b82f6'
  if (et === 'FAILURE') return '#ef4444'
  if (et === 'HUMAN_CONFIRMATION') return '#10b981'
  if (et === 'TEST') return '#8b5cf6'
  if (et === 'RUNTIME') return '#f59e0b'
  return '#64748b'
})

const sourceTypeLabel = computed(() => {
  const st = props.evidence.source_type?.toUpperCase()
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
  return map[st] || st || '—'
})

const sourceSummary = computed(() => {
  const e = props.evidence
  return e.source_ref || e.source_uri || e.source_path || e.source_label || null
})

const canCompare = computed(() => {
  const st = props.evidence.source_type?.toUpperCase()
  return st === 'COMMIT' || st === 'MR' || st === 'DIFF' || st === 'FILE_PATH'
})

const keyInfo = computed(() => {
  const st = props.evidence.source_type?.toUpperCase()
  const e = props.evidence
  if (st === 'COMMIT' && e.source_ref) {
    return { type: 'commit' as const, text: e.source_ref, copyable: true }
  }
  if (st === 'MR' && e.source_uri) {
    const match = e.source_uri.match(/\/(pull|merge_requests)\/(\d+)/)
    const label = match ? `#${match[2]}` : e.source_uri
    return { type: 'mr' as const, text: label, fullText: e.source_uri, copyable: true }
  }
  if ((st === 'FILE_PATH' || st === 'OTHER') && e.source_path) {
    return { type: 'path' as const, text: e.source_path, copyable: true }
  }
  if (st === 'RUN_LOG' && e.source_path) {
    return { type: 'path' as const, text: e.source_path, copyable: true }
  }
  return null
})

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(t('workspace_assets.task_detail.workbench.evidence_card.copied'))
  } catch {
    ElMessage.error(t('workspace_assets.task_detail.workbench.evidence_card.copy_failed'))
  }
}
</script>

<template>
  <div class="evidence-card" :class="{ readonly }">
    <div class="card-header">
      <span class="type-badge" :style="{ background: typeColor }">{{ evidence.evidence_type }}</span>
      <span class="status-dot" :style="{ background: statusColor }" />
      <span class="title-text">{{ evidence.title || t('workspace_assets.task_detail.workbench.evidence_card.untitled') }}</span>
    </div>
    <div class="card-body">
      <div class="meta-row">
        <span class="source-type-tag">{{ sourceTypeLabel }}</span>
        <span v-if="sourceSummary && !keyInfo" class="source-ref" :title="sourceSummary">{{ sourceSummary }}</span>
      </div>
      <div v-if="keyInfo" class="key-info-row">
        <component
          :is="keyInfo.type === 'commit' ? GitCommitHorizontal : keyInfo.type === 'mr' ? GitPullRequest : FileText"
          class="key-info-icon"
          :size="14"
        />
        <span class="key-info-text" :title="keyInfo.fullText || keyInfo.text">{{ keyInfo.text }}</span>
        <button class="icon-btn" :title="t('workspace_assets.task_detail.workbench.evidence_card.copy')" @click.stop="copyText(keyInfo.fullText || keyInfo.text)">
          <Copy :size="13" />
        </button>
      </div>
      <p v-if="evidence.summary" class="summary-text">{{ evidence.summary }}</p>
    </div>
    <div class="card-footer">
      <span v-if="evidence.created_at" class="created-at">{{ new Date(evidence.created_at).toLocaleDateString() }}</span>
      <div class="footer-actions">
        <span v-if="canCompare && evidence.status === 'CONFIRMED'" class="compare-hint">
          {{ t('workspace_assets.task_detail.workbench.evidence_card.can_compare') }}
        </span>
        <button class="detail-btn" @click.stop="emit('view-detail', evidence.id)">
          <Info :size="13" />
          {{ t('workspace_assets.task_detail.workbench.evidence_card.view_detail') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.evidence-card {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 0.875rem 1rem;
  background: #ffffff;
  transition: box-shadow 0.2s;
}

.evidence-card:hover:not(.readonly) {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.evidence-card.readonly {
  opacity: 0.8;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
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

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.title-text {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-body {
  margin-bottom: 0.375rem;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.source-type-tag {
  font-size: 0.6875rem;
  font-weight: 600;
  color: #64748b;
  background: #f1f5f9;
  padding: 0.0625rem 0.375rem;
  border-radius: 4px;
}

.source-ref {
  font-size: 0.75rem;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 280px;
}

.key-info-row {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.3125rem 0.5rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  margin-bottom: 0.25rem;
}

.key-info-icon {
  color: #64748b;
  flex-shrink: 0;
}

.key-info-text {
  font-size: 0.8125rem;
  font-weight: 600;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.icon-btn {
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

.icon-btn:hover {
  background: #e2e8f0;
  color: #475569;
}

.summary-text {
  font-size: 0.75rem;
  color: #64748b;
  line-height: 1.4;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.created-at {
  font-size: 0.6875rem;
  color: #94a3b8;
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.compare-hint {
  font-size: 0.6875rem;
  color: #3b82f6;
  font-weight: 600;
}

.detail-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.1875rem 0.5rem;
  font-size: 0.6875rem;
  font-weight: 600;
  color: #3b82f6;
  background: transparent;
  border: 1px solid #bfdbfe;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s;
}

.detail-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
}
</style>
