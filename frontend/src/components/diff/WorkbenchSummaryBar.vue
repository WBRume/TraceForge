<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bot, User, FileDiff, Plus, Minus } from 'lucide-vue-next'
import type { WorkbenchDelta } from '@/types/workspaceAssets'

const props = defineProps<{
  delta: WorkbenchDelta
}>()

const { t } = useI18n()

const statusColor = computed(() => {
  switch (props.delta.status) {
    case 'READY': return 'success'
    case 'COMPARING': return 'warning'
    case 'PENDING': return 'info'
    case 'SUPERSEDED': return 'secondary'
    default: return 'info'
  }
})

const divergenceStats = computed(() => {
  const regions = props.delta.delta_regions ?? []
  let insertions = 0
  let deletions = 0
  let files = new Set<string>()
  
  for (const r of regions) {
    if (r.region_source === 'DIVERGED' || r.region_source === 'BOTH_SAME') {
      insertions += r.human_insertions
      deletions += r.human_deletions
      files.add(r.file_path)
    } else if (r.region_source === 'HUMAN_ONLY') {
      insertions += r.human_insertions
      deletions += r.human_deletions
      files.add(r.file_path)
    } else if (r.region_source === 'AI_ONLY') {
      deletions += r.ai_insertions + r.ai_deletions
      files.add(r.file_path)
    }
  }
  return { files: files.size, insertions, deletions }
})
</script>

<template>
  <div class="workbench-summary-bar">
    <div class="summary-section summary-source">
      <div class="source-badge source-ai">
        <Bot :size="14" />
        <span class="source-label">{{ delta.ai_patch?.source_label ?? 'AI Patch' }}</span>
      </div>
      <span class="vs-text">vs</span>
      <div class="source-badge source-human">
        <User :size="14" />
        <span class="source-label">{{ delta.human_patch?.source_label ?? 'Human Patch' }}</span>
      </div>
    </div>

    <div class="summary-section summary-stats">
      <div class="stat-item">
        <FileDiff :size="14" />
        <span class="stat-value">{{ divergenceStats.files }}</span>
        <span class="stat-label">{{ t('workspace_assets.task_detail.workbench.summary.files') }}</span>
      </div>
      <div class="stat-item stat-add">
        <Plus :size="14" />
        <span class="stat-value">{{ divergenceStats.insertions }}</span>
      </div>
      <div class="stat-item stat-del">
        <Minus :size="14" />
        <span class="stat-value">{{ divergenceStats.deletions }}</span>
      </div>
    </div>

    <div class="summary-section summary-meta">
      <span v-if="delta.decision_count" class="decision-count">
        {{ delta.decision_count }} {{ t('workspace_assets.task_detail.workbench.summary.decisions') }}
      </span>
      <span class="status-badge" :class="`status-${statusColor}`">
        {{ delta.status }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.workbench-summary-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  background: var(--color-background, #fff);
  border-bottom: 1px solid var(--color-border, #e5e7eb);
  flex-wrap: wrap;
}

.summary-section {
  display: flex;
  align-items: center;
  gap: 8px;
}

.summary-source {
  gap: 6px;
}

.source-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.source-ai {
  background: #fff7ed;
  color: #c2410c;
  border: 1px solid #fed7aa;
}

.source-human {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.vs-text {
  font-size: 11px;
  color: var(--color-text-secondary, #9ca3af);
  font-weight: 500;
}

.source-label {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.summary-stats {
  gap: 12px;
}

.stat-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--color-text-secondary, #6b7280);
}

.stat-value {
  font-weight: 600;
  color: var(--color-text-primary, #111827);
}

.stat-add .stat-value {
  color: #16a34a;
}

.stat-del .stat-value {
  color: #dc2626;
}

.summary-meta {
  margin-left: auto;
  gap: 10px;
}

.decision-count {
  font-size: 12px;
  color: var(--color-text-secondary, #6b7280);
}

.status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.status-success {
  background: #dcfce7;
  color: #166534;
}

.status-warning {
  background: #fef9c3;
  color: #854d0e;
}

.status-info {
  background: #dbeafe;
  color: #1e40af;
}

.status-secondary {
  background: #f3f4f6;
  color: #6b7280;
}
</style>
