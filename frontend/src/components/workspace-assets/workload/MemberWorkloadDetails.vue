<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { ChevronRight, FileText, MessageSquare } from '@/components/icons'
import type { WorkloadExecution, WorkloadItem, WorkloadKind } from '@/types/workload'
import { pendingKinds } from './workloadCounts'

const props = defineProps<{
  workspaceId: string
  items: readonly WorkloadItem[]
  executions?: readonly WorkloadExecution[]
  asOf: string
  inline?: boolean
}>()
const { t, locale } = useI18n()
const prefix = 'workspace_assets.workload.'
const itemGroups: { label: string; kinds: readonly WorkloadKind[] }[] = [
  { label: 'pending', kinds: pendingKinds },
  { label: 'expected_check', kinds: ['expected_check'] },
  { label: 'paused_check', kinds: ['paused_check'] },
  { label: 'ongoing', kinds: ['ongoing'] },
  { label: 'planned', kinds: ['planned'] },
]
const groups = computed(() => [
  ...itemGroups.map(({ label, kinds }) => ({
    label,
    entries: props.items.filter(item => kinds.includes(item.kind)).map(item => ({
      id: item.id,
      title: item.title,
      to: props.inline ? undefined : itemLocation(item),
      icon: item.requirement_id ? FileText : MessageSquare,
      status: label === 'pending' ? t(prefix + item.kind) : '',
      note: label === 'pending' ? waitTime(item.since) : item.kind === 'expected_check' ? t(prefix + 'return_unknown') : '',
      warning: item.overdue,
    })),
  })),
  {
    label: 'sessions',
    entries: (props.executions ?? []).map(run => ({
      id: run.id,
      title: run.title,
      to: props.inline ? undefined : taskLocation(run.task_id),
      icon: MessageSquare,
      status: t(prefix + (run.reason === 'reply' ? 'waiting_reply' : run.reason)),
      note: '',
      warning: run.slot === 'uncertain' || run.slot === 'incomplete',
    })),
  },
].filter(group => group.entries.length))

function itemLocation(item: WorkloadItem) {
  if (item.requirement_id) {
    return {
      name: 'workspaceAssetsRequirementDetail',
      params: { wsId: props.workspaceId, requirementId: item.requirement_id },
      query: item.kind === 'acceptance' || item.kind === 'check' ? { focus: 'acceptance' } : {},
    }
  }
  if (item.task_id) return taskLocation(item.task_id)
}

function taskLocation(taskId: string) {
  return { name: 'taskChat', params: { wsId: props.workspaceId, taskId } }
}

function waitTime(since?: string | null) {
  if (!since) return ''
  const parsed = Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(since) ? since : `${since}Z`)
  const minutes = Math.max(0, Math.floor((Date.parse(props.asOf) - parsed) / 60000))
  if (!Number.isFinite(minutes)) return ''
  const unit = minutes >= 60 ? 'hour' : 'minute'
  const time = new Intl.NumberFormat(locale.value, { style: 'unit', unit, unitDisplay: 'short' })
    .format(unit === 'hour' ? Math.floor(minutes / 60) : minutes)
  return t(prefix + 'wait', { time })
}
</script>

<template>
  <div class="workload-details" :class="{ 'is-inline': inline }">
    <el-empty v-if="!groups.length" :description="t(prefix + 'no_details')" :image-size="60" />
    <section v-for="group in groups" :key="group.label" class="detail-group">
      <h3>
        {{ t(prefix + group.label) }}
        <span class="group-count">{{ group.entries.length }}</span>
      </h3>
      <ul class="entry-list">
        <li v-for="entry in group.entries" :key="entry.id" class="entry">
          <component :is="entry.to ? RouterLink : 'div'" :to="entry.to" class="entry-row">
            <span v-if="!inline" class="entry-icon" aria-hidden="true"><component :is="entry.icon" /></span>
            <span class="entry-content">
              <span class="entry-title">{{ entry.title }}</span>
              <span v-if="entry.status || entry.note" class="entry-meta">
                <el-tag v-if="entry.status" size="small" :type="entry.warning ? 'warning' : 'info'">{{ entry.status }}</el-tag>
                <span v-if="entry.note">{{ entry.note }}</span>
              </span>
            </span>
            <ChevronRight v-if="entry.to" class="entry-chevron" aria-hidden="true" />
          </component>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.workload-details {
  display: grid;
  min-width: 0;
  gap: 16px;
  line-height: 1.5;
}

.detail-group {
  min-width: 0;
  border: 1px solid var(--el-border-color);
  border-radius: var(--radius-lg);
  background: var(--color-surface-white);
}

.detail-group h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 10px 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  color: var(--color-text-title);
  font-size: 14px;
}

.group-count {
  min-width: 22px;
  padding: 1px 6px;
  border-radius: var(--radius-full);
  background: var(--color-bg-base);
  color: var(--color-text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: center;
}

.entry-list {
  margin: 0;
  padding: 4px 8px;
  list-style: none;
}

.entry + .entry {
  border-top: 1px solid var(--el-border-color-lighter);
}

.entry-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 8px 6px;
  border-radius: var(--radius-md);
  color: var(--color-text-body);
  text-decoration: none;
}

a.entry-row:hover,
a.entry-row:focus-visible {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
}

a.entry-row:focus-visible {
  outline: 2px solid var(--color-primary-600);
  outline-offset: -2px;
}

.entry-icon {
  display: grid;
  flex: 0 0 28px;
  height: 28px;
  place-items: center;
  border-radius: var(--radius-sm);
  background: var(--color-bg-base);
  color: var(--color-text-muted);
}

.entry-icon svg,
.entry-chevron {
  flex: 0 0 15px;
  width: 15px;
  height: 15px;
}

.entry-chevron {
  color: var(--color-text-muted);
}

.entry-content {
  display: grid;
  flex: 1;
  gap: 4px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.entry-title {
  font-size: 14px;
  font-weight: 600;
}

.entry-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
  color: var(--color-text-muted);
  font-size: 12px;
}

.is-inline {
  gap: 8px;
}

.is-inline .detail-group h3,
.is-inline .entry-row {
  padding-block: 6px;
}

.is-inline .entry-row {
  min-height: 0;
}

.is-inline .entry-title {
  font-size: 13px;
  font-weight: 500;
}
</style>
