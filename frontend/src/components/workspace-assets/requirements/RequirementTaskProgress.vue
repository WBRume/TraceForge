<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { taskStatusKey } from '@/utils/taskStatus'
import type { RequirementSummary } from '@/types/workspaceAssets'

const props = defineProps<{ requirement: RequirementSummary }>()
const { t } = useI18n()
const open = shallowRef(false)
const progress = computed(() => props.requirement.task_progress)
const percentage = computed(() => progress.value?.total
  ? Math.round(100 * progress.value.completed / progress.value.total)
  : 0)
const statusOrder = new Map([
  'COMPLETED', 'RUNNING', 'AWAITING_INPUT', 'ROUND_COMPLETED', 'FAILED',
  'INTERRUPTED', 'INITIALIZED', 'PROVISIONING',
].map((status, index) => [status, index]))

const statusCounts = computed(() => Object.entries(progress.value?.status_counts ?? {})
  .filter(([, count]) => count > 0)
  .sort(([a], [b]) => (statusOrder.get(a) ?? statusOrder.size) - (statusOrder.get(b) ?? statusOrder.size)))
</script>

<template>
  <div v-if="progress" class="requirement-progress">
    <el-popover v-model:visible="open" placement="bottom-start" trigger="click" width="min(300px, calc(100vw - 32px))">
      <template #reference>
        <button type="button" class="progress-trigger" @click.stop @keydown.esc="open = false">
          <span class="progress-label">
            <span>{{ progress.total
              ? t('workspace_assets.requirements.progress.complete', { done: progress.completed, total: progress.total })
              : t('workspace_assets.requirements.progress.no_tasks') }}</span>
            <span v-if="progress.total" class="progress-percentage">{{ percentage }}%</span>
          </span>
          <span v-if="progress.total" class="progress-track" aria-hidden="true">
            <span class="progress-fill" :style="{ width: `${percentage}%` }" />
          </span>
        </button>
      </template>

      <section class="progress-stats" :aria-label="t('workspace_assets.requirements.progress.stats_title')">
        <header class="progress-stats-header">
          <strong>{{ t('workspace_assets.requirements.progress.stats_title') }}</strong>
          <span>{{ t('workspace_assets.requirements.progress.counted_tasks', { count: progress.total }) }}</span>
        </header>

        <dl v-if="statusCounts.length" class="progress-stats-list">
          <div v-for="[status, count] in statusCounts" :key="status" class="progress-stat" :data-status="status">
            <dt><span class="status-dot" aria-hidden="true" />{{ t(taskStatusKey(status)) }}</dt>
            <dd>{{ count }}</dd>
          </div>
        </dl>

        <dl v-if="progress.reference_only || progress.unassigned_child_ids.length" class="progress-stats-list progress-scope">
          <div v-if="progress.reference_only" class="progress-stat">
            <dt>{{ t('workspace_assets.requirements.progress.reference') }}</dt>
            <dd>{{ progress.reference_only }}</dd>
          </div>
          <div v-if="progress.unassigned_child_ids.length" class="progress-stat">
            <dt>{{ t('workspace_assets.requirements.progress.unassigned_children') }}</dt>
            <dd>{{ progress.unassigned_child_ids.length }}</dd>
          </div>
        </dl>

        <p class="progress-rule">{{ t('workspace_assets.requirements.progress.rule') }}</p>
      </section>
    </el-popover>
  </div>
</template>

<style scoped>
.progress-trigger {
  display: grid;
  gap: 5px;
  width: 100%;
  padding: 0;
  text-align: start;
  color: var(--el-text-color-regular);
  background: none;
  border: 0;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.progress-trigger:hover { color: var(--el-color-primary-dark-2); }
.progress-trigger:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 3px; border-radius: 3px; }
.progress-label { display: flex; justify-content: space-between; gap: 6px; }
.progress-percentage { font-variant-numeric: tabular-nums; }
.progress-track { height: 5px; border-radius: 3px; overflow: hidden; background: var(--el-border-color-lighter); }
.progress-fill { display: block; height: 100%; border-radius: inherit; background: var(--el-color-primary); }

.progress-stats { color: var(--el-text-color-regular); font-size: 12px; }
.progress-stats-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 4px 12px;
  padding: 3px 0 10px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.progress-stats-header strong { color: var(--el-text-color-primary); font-size: 14px; }
.progress-stats-header span { color: var(--el-text-color-secondary); }
.progress-stats-list { display: grid; gap: 4px; margin: 8px 0; }
.progress-stat { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 26px; }
.progress-stat dt { display: flex; align-items: center; gap: 8px; }
.progress-stat dd {
  margin: 0;
  min-width: 26px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
  text-align: center;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.status-dot { width: 8px; height: 8px; flex: none; border-radius: 50%; background: var(--el-color-info); }
[data-status="COMPLETED"] .status-dot { background: var(--el-color-success); }
[data-status="RUNNING"] .status-dot { background: var(--el-color-primary); }
[data-status="AWAITING_INPUT"] .status-dot,
[data-status="INTERRUPTED"] .status-dot { background: var(--el-color-warning); }
[data-status="ROUND_COMPLETED"] .status-dot { background: #818cf8; }
[data-status="FAILED"] .status-dot { background: var(--el-color-danger); }
.progress-scope { padding-top: 6px; border-top: 1px solid var(--el-border-color-lighter); }
.progress-stats-header + .progress-scope { padding-top: 0; border-top: 0; }
.progress-rule {
  margin: 10px 0 0;
  padding: 7px 9px;
  border-radius: 5px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  font-size: 11px;
  line-height: 1.55;
}
</style>
