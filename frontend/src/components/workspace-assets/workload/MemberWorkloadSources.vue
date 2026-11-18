<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronRight } from '@/components/icons'
import type { WorkloadLimits, WorkloadSource } from '@/types/workload'
import MemberWorkloadDetails from './MemberWorkloadDetails.vue'
import { countsFromSummary } from './workloadCounts'

const props = defineProps<{
  workspaceId: string
  sources: readonly WorkloadSource[]
  asOf: string
  limits: WorkloadLimits
}>()
const { t } = useI18n()
const prefix = 'workspace_assets.workload.'
const keys = ['pending', 'background', 'interactive', 'ongoing', 'planned'] as const
const rows = computed(() => props.sources.map(source => {
  const local = source.workspace_id === props.workspaceId
  const counts = countsFromSummary(source.counts)
  const metrics = keys.map(key => ({
    key,
    count: counts[key],
    limit: local && (key === 'background' || key === 'interactive' || key === 'ongoing') ? props.limits[key] : null,
  }))
  return { source, local, counts, metrics, hasLimits: metrics.some(metric => metric.limit !== null) }
}))
</script>

<template>
  <section class="workspace-sources">
    <h3>{{ t(prefix + 'sources') }}</h3>
    <details v-for="row in rows" :key="row.source.workspace_id" class="source" :open="rows.length === 1">
      <summary class="source-heading">
        <ChevronRight class="source-chevron" aria-hidden="true" />
        <span class="source-title">
          <strong>{{ row.source.workspace_name }}</strong>
          <small>{{ t(prefix + 'option_summary', row.counts) }}</small>
        </span>
        <el-tag v-if="row.local" size="small" type="info">{{ t(prefix + 'current_workspace') }}</el-tag>
      </summary>
      <div class="source-content">
        <span v-if="row.hasLimits" class="source-note" :title="t(prefix + 'ratio_help')">{{ t(prefix + 'ratio') }}</span>
        <dl class="source-metrics">
          <div v-for="metric in row.metrics" :key="metric.key" class="source-metric">
            <dt>{{ t(prefix + metric.key) }}</dt>
            <dd :class="{ 'over-limit': metric.limit !== null && metric.count > metric.limit }">
              {{ metric.count }}<small v-if="metric.limit !== null"> / {{ metric.limit }}</small>
            </dd>
          </div>
        </dl>
        <div v-if="row.counts.pending || row.counts.expected || row.counts.paused || row.counts.overdue
          || row.counts.incomplete || row.counts.uncertain" class="source-tags">
          <el-tag v-for="item in row.counts.pendingByKind" :key="item.kind" size="small" type="info">
            {{ t(prefix + item.kind) }} {{ item.count }}
          </el-tag>
          <el-tag v-if="row.counts.overdue" size="small" type="warning">
            {{ t(prefix + 'overdue', { count: row.counts.overdue }) }}
          </el-tag>
          <el-tag v-if="row.counts.expected" size="small" type="info">
            {{ t(prefix + 'return_count', { count: row.counts.expected }) }}
          </el-tag>
          <el-tag v-if="row.counts.paused" size="small" type="info">
            {{ t(prefix + 'paused_check') }} {{ row.counts.paused }}
          </el-tag>
          <el-tag v-if="row.counts.incomplete" size="small" type="warning">
            {{ t(prefix + 'incomplete') }} {{ row.counts.incomplete }}
          </el-tag>
          <el-tag v-if="row.counts.uncertain" size="small" type="warning">
            {{ t(prefix + 'uncertain') }} {{ row.counts.uncertain }}
          </el-tag>
        </div>
        <MemberWorkloadDetails
          v-if="row.source.details && (row.source.details.items.length || row.source.details.executions.length)"
          :workspace-id="row.source.workspace_id"
          :as-of="asOf"
          :items="row.source.details.items"
          :executions="row.source.details.executions"
        />
        <span v-else-if="!row.source.details" class="source-note">{{ t(prefix + 'summary_only') }}</span>
      </div>
    </details>
  </section>
</template>

<style scoped>
.workspace-sources {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.workspace-sources h3 {
  margin: 0 0 2px;
  font-size: 14px;
}

.source {
  min-width: 0;
  border: 1px solid var(--el-border-color);
  border-radius: var(--radius-lg);
  background: var(--color-surface-white);
}

.source-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  cursor: pointer;
  list-style: none;
}

.source-heading::-webkit-details-marker { display: none; }
.source-heading:hover { color: var(--color-primary-700); }
.source-chevron { width: 16px; height: 16px; flex: 0 0 16px; color: var(--color-text-muted); }
.source[open] > .source-heading .source-chevron { transform: rotate(90deg); }
.source-title { display: grid; flex: 1; gap: 3px; min-width: 0; overflow-wrap: anywhere; font-size: 14px; }
.source-title small, .source-note, .source-metric dt, .source-metric small {
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 400;
}

.source-content {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.source-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(64px, 1fr));
  gap: 6px;
  margin: 0;
}

.source-metric { display: grid; gap: 4px; padding: 6px 8px; border-radius: var(--radius-md); background: var(--color-bg-base); }
.source-metric dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; }
.source-metric .over-limit { color: var(--el-color-warning-dark-2); }
.source-tags { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
</style>
