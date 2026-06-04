<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Minus, ArrowRightLeft, Sparkles } from 'lucide-vue-next'
import type { DeltaRegion } from '@/types/workspaceAssets'

const props = defineProps<{
  region: DeltaRegion | null
  deltaId?: string
  humanPatchSource?: {
    source_type: string
    source_ref?: string | null
    source_uri?: string | null
    source_label?: string | null
  } | null
  promoteCandidate?: boolean
}>()

const emit = defineEmits<{
  'create-decision': [payload: { region: DeltaRegion; deltaId: string }]
  'update-promote': [deltaId: string, value: boolean]
}>()

const { t } = useI18n()

const regionSourceLabel = computed(() => {
  if (!props.region) return ''
  switch (props.region.region_source) {
    case 'AI_ONLY': return 'AI Only'
    case 'HUMAN_ONLY': return 'Human Only'
    case 'BOTH_SAME': return 'Both (Same)'
    case 'DIVERGED': return 'Diverged'
    default: return props.region.region_source
  }
})

const regionSourceColor = computed(() => {
  if (!props.region) return '#6b7280'
  switch (props.region.region_source) {
    case 'AI_ONLY': return '#f97316'
    case 'HUMAN_ONLY': return '#10b981'
    case 'BOTH_SAME': return '#6366f1'
    case 'DIVERGED': return '#dc2626'
    default: return '#6b7280'
  }
})

const regionTypeLabel = computed(() => {
  if (!props.region) return ''
  switch (props.region.region_type) {
    case 'FILE_ADDED': return 'File Added'
    case 'FILE_DELETED': return 'File Deleted'
    case 'FILE_RENAMED': return 'File Renamed'
    case 'FILE_REWRITTEN': return 'File Rewritten'
    case 'HUNK_MODIFIED': return 'Hunk Modified'
    case 'LINE_DIVERGED': return 'Line Diverged'
    default: return props.region.region_type
  }
})

function fileName(path: string): string {
  return path.split('/').pop() ?? path
}
</script>

<template>
  <div class="delta-region-panel">
    <div v-if="!region" class="empty-state">
      <ArrowRightLeft :size="32" class="empty-icon" />
      <p class="empty-text">{{ t('workspace_assets.task_detail.workbench.region_panel.select_hint') }}</p>
    </div>

    <template v-else>
      <div class="region-header">
        <span class="region-source-badge" :style="{ color: regionSourceColor, borderColor: regionSourceColor }">
          {{ regionSourceLabel }}
        </span>
        <span class="region-type-badge">{{ regionTypeLabel }}</span>
      </div>

      <div class="region-file">
        <span class="file-path" :title="region.file_path">{{ fileName(region.file_path) }}</span>
      </div>

      <div class="region-stats">
        <div v-if="region.ai_insertions || region.ai_deletions" class="stat-group">
          <span class="stat-label">AI</span>
          <span v-if="region.ai_insertions" class="stat-add"><Plus :size="12" />{{ region.ai_insertions }}</span>
          <span v-if="region.ai_deletions" class="stat-del"><Minus :size="12" />{{ region.ai_deletions }}</span>
        </div>
        <div v-if="region.human_insertions || region.human_deletions" class="stat-group">
          <span class="stat-label">Human</span>
          <span v-if="region.human_insertions" class="stat-add"><Plus :size="12" />{{ region.human_insertions }}</span>
          <span v-if="region.human_deletions" class="stat-del"><Minus :size="12" />{{ region.human_deletions }}</span>
        </div>
      </div>

      <div class="evidence-source-section">
        <h4 class="section-title">{{ t('workspace_assets.task_detail.workbench.region_panel.evidence_source') }}</h4>
        <div v-if="humanPatchSource" class="evidence-info">
          <div class="evidence-row">
            <span class="evidence-label">Type</span>
            <span class="evidence-value">{{ humanPatchSource.source_type }}</span>
          </div>
          <div v-if="humanPatchSource.source_ref" class="evidence-row">
            <span class="evidence-label">Ref</span>
            <span class="evidence-value evidence-mono">{{ humanPatchSource.source_ref }}</span>
          </div>
          <div v-if="humanPatchSource.source_uri" class="evidence-row">
            <span class="evidence-label">URI</span>
            <a class="evidence-value evidence-link" :href="humanPatchSource.source_uri" target="_blank">{{ humanPatchSource.source_uri }}</a>
          </div>
        </div>
        <div v-else class="no-evidence">
          {{ t('workspace_assets.task_detail.workbench.region_panel.no_evidence') }}
        </div>
      </div>

      <div v-if="region.summary" class="region-summary">
        <p>{{ region.summary }}</p>
      </div>

      <div v-if="region.ai_line_start || region.human_line_start" class="region-lines">
        <div v-if="region.ai_line_start" class="line-range">
          <span class="line-label">AI Lines:</span>
          <span class="line-value">{{ region.ai_line_start }}–{{ region.ai_line_end }}</span>
        </div>
        <div v-if="region.human_line_start" class="line-range">
          <span class="line-label">Human Lines:</span>
          <span class="line-value">{{ region.human_line_start }}–{{ region.human_line_end }}</span>
        </div>
      </div>

      <div class="region-decisions" v-if="region.decisions.length > 0">
        <h4 class="section-title">{{ t('workspace_assets.task_detail.workbench.region_panel.decisions') }}</h4>
        <div v-for="d in region.decisions" :key="d.id" class="decision-item">
          <span class="decision-status" :class="`status-${d.status.toLowerCase()}`">{{ d.status }}</span>
          <span class="decision-title">{{ d.title }}</span>
          <span v-if="d.promote_candidate" class="promote-icon" title="Promoted">
            <Sparkles :size="12" />
          </span>
        </div>
      </div>

      <div class="region-actions">
        <button class="action-btn" @click="emit('create-decision', { region, deltaId: deltaId ?? '' })">
          <Plus :size="14" />
          {{ t('workspace_assets.task_detail.workbench.region_panel.add_decision') }}
        </button>
        <button
          class="action-btn"
          :class="{ 'action-promote-active': promoteCandidate }"
          @click="emit('update-promote', deltaId ?? '', !promoteCandidate)"
        >
          <Sparkles :size="14" />
          {{ promoteCandidate
            ? t('workspace_assets.task_detail.workbench.region_panel.promote_active')
            : t('workspace_assets.task_detail.workbench.region_panel.promote') }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.delta-region-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
  font-size: 13px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: var(--color-text-secondary, #9ca3af);
}

.empty-icon {
  opacity: 0.4;
}

.empty-text {
  font-size: 13px;
  text-align: center;
  max-width: 200px;
}

.region-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 12px 8px;
}

.region-source-badge {
  display: inline-block;
  padding: 2px 8px;
  border: 1px solid;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.region-type-badge {
  display: inline-block;
  padding: 2px 8px;
  background: var(--color-background-muted, #f3f4f6);
  border-radius: 4px;
  font-size: 11px;
  color: var(--color-text-secondary, #6b7280);
}

.region-file {
  padding: 0 12px 8px;
}

.file-path {
  font-family: monospace;
  font-size: 12px;
  color: var(--color-text-primary, #374151);
  word-break: break-all;
}

.region-stats {
  display: flex;
  gap: 16px;
  padding: 8px 12px;
  border-top: 1px solid var(--color-border-light, #f3f4f6);
  border-bottom: 1px solid var(--color-border-light, #f3f4f6);
}

.stat-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.stat-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-secondary, #9ca3af);
  text-transform: uppercase;
}

.stat-add {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: #16a34a;
  font-size: 12px;
  font-weight: 500;
}

.stat-del {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: #dc2626;
  font-size: 12px;
  font-weight: 500;
}

.region-summary {
  padding: 8px 12px;
  font-size: 12px;
  color: var(--color-text-secondary, #6b7280);
}

.region-lines {
  padding: 4px 12px 8px;
}

.line-range {
  display: flex;
  gap: 6px;
  font-size: 12px;
}

.line-label {
  color: var(--color-text-secondary, #9ca3af);
  font-weight: 500;
}

.line-value {
  font-family: monospace;
  color: var(--color-text-primary, #374151);
}

.region-decisions {
  padding: 8px 12px;
}

.section-title {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--color-text-secondary, #9ca3af);
  margin: 0 0 6px;
}

.decision-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  font-size: 12px;
}

.decision-status {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
}

.status-proposed {
  background: #dbeafe;
  color: #1e40af;
}

.status-accepted {
  background: #dcfce7;
  color: #166534;
}

.status-rejected {
  background: #fee2e2;
  color: #991b1b;
}

.decision-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.region-actions {
  margin-top: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  border: 1px solid var(--color-border, #d1d5db);
  border-radius: 6px;
  background: var(--color-background, #fff);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  color: var(--color-text-primary, #374151);
}

.action-btn:hover {
  background: var(--color-background-hover, #f9fafb);
}

.evidence-source-section {
  padding: 8px 12px;
  border-top: 1px solid var(--color-border-light, #f3f4f6);
}

.evidence-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.evidence-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.evidence-label {
  color: var(--color-text-secondary, #9ca3af);
  font-weight: 500;
  min-width: 40px;
}

.evidence-value {
  color: var(--color-text-primary, #374151);
  word-break: break-all;
}

.evidence-mono {
  font-family: monospace;
  font-size: 11px;
}

.evidence-link {
  color: var(--color-primary, #2563eb);
  text-decoration: underline;
}

.no-evidence {
  font-size: 12px;
  color: var(--color-text-secondary, #9ca3af);
  font-style: italic;
}

.promote-icon {
  color: #8b5cf6;
  display: inline-flex;
  align-items: center;
}

.action-promote-active {
  background: #f5f3ff;
  border-color: #8b5cf6;
  color: #7c3aed;
}
</style>
