<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import UserAvatar from '@/components/user/UserAvatar.vue'
import type { MemberWorkload } from '@/types/workload'
import { countsFor } from './workloadCounts'

const props = defineProps<{ members: readonly MemberWorkload[] }>()
const emit = defineEmits<{ open: [userId: string] }>()
const { t } = useI18n()
const prefix = 'workspace_assets.workload.'
const rows = computed(() => props.members.map(member => ({ ...member, counts: countsFor(member) })))
const slots = ['background', 'interactive'] as const
function ratio(count: number, limit: number | null) {
  return limit === null ? '0%' : `${Math.min(1, limit === 0 ? Number(count > 0) : count / limit) * 100}%`
}
</script>

<template>
  <el-table :data="rows" row-key="user_id" class="asset-table">
    <el-table-column :label="t(prefix + 'member')" min-width="136">
      <template #default="{ row }">
        <button type="button" class="member-link" @click="emit('open', row.user_id)">
          <UserAvatar :display-name="row.display_name" :avatar-url="row.avatar_url" size="sm" aria-hidden="true" />
          <span class="identity">
            <strong>{{ row.display_name }}</strong><small>{{ t(prefix + 'role_' + row.role.toLowerCase()) }}</small>
          </span>
        </button>
      </template>
    </el-table-column>
    <el-table-column :label="t(prefix + 'pending')" min-width="130">
      <template #default="{ row }">
        <div v-if="row.counts.pending" class="todo">
          <strong>{{ row.counts.pending }}</strong>
          <el-tag v-for="item in row.counts.pendingByKind" :key="item.kind" size="small" type="info">
            {{ t(prefix + item.kind) }} {{ item.count }}
          </el-tag>
        </div>
        <span v-else class="muted">{{ t(prefix + 'no_pending') }}</span>
      </template>
    </el-table-column>
    <el-table-column min-width="200">
      <template #header>
        {{ t(prefix + 'sessions') }}
        <small class="muted ratio" :title="t(prefix + 'ratio_help')">{{ t(prefix + 'ratio') }}</small>
      </template>
      <template #default="{ row }">
        <div v-for="slot in slots" :key="slot" class="meter" :data-over="row.limits[slot] !== null && row.counts[slot] > row.limits[slot]">
          <span>{{ t(prefix + slot) }}</span>
          <span class="track" aria-hidden="true"><span :style="{ width: ratio(row.counts[slot], row.limits[slot]) }" /></span>
          <strong :title="row.limits[slot] === null ? t(prefix + 'unset') : undefined">
            {{ row.counts[slot] }}<small v-if="row.limits[slot] !== null"> / {{ row.limits[slot] }}</small>
          </strong>
        </div>
        <small v-if="row.counts.incomplete" class="muted">{{ t(prefix + 'incomplete') }} {{ row.counts.incomplete }}</small>
      </template>
    </el-table-column>
    <el-table-column :label="t(prefix + 'requirements')" min-width="120">
      <template #default="{ row }">
        <div class="requirement-counts">
          <div :data-over="row.limits.ongoing !== null && row.counts.ongoing > row.limits.ongoing">
            <strong>{{ row.counts.ongoing }}<small v-if="row.limits.ongoing !== null"> / {{ row.limits.ongoing }}</small></strong>
            <small>{{ t(prefix + 'ongoing') }}</small>
          </div>
          <div><strong>{{ row.counts.planned }}</strong><small>{{ t(prefix + 'planned') }}</small></div>
        </div>
      </template>
    </el-table-column>
    <el-table-column :label="t(prefix + 'attention')" min-width="148">
      <template #default="{ row }">
        <div class="todo">
          <el-tag v-if="row.counts.overdue" type="warning" size="small">{{ t(prefix + 'overdue', { count: row.counts.overdue }) }}</el-tag>
          <el-tag v-if="row.counts.expected" type="info" size="small">{{ t(prefix + 'return_count', { count: row.counts.expected }) }}</el-tag>
          <el-tag v-if="row.counts.uncertain" type="warning" size="small">{{ t(prefix + 'uncertain') }} {{ row.counts.uncertain }}</el-tag>
          <span v-if="!row.counts.overdue && !row.counts.expected && !row.counts.uncertain" class="muted">—</span>
        </div>
      </template>
    </el-table-column>
    <template #empty><el-empty :description="t(prefix + 'no_members')" /></template>
  </el-table>
</template>

<style scoped>
.member-link {
  display: inline-flex; align-items: center; gap: 8px; max-width: 100%; padding: 4px 0;
  border: 0; background: transparent; color: var(--el-text-color-primary); cursor: pointer;
  text-align: left; font: inherit;
}
.member-link:hover { color: var(--el-color-primary-dark-2); }
.identity { display: grid; min-width: 0; }
.identity strong, .identity small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.muted, .identity small, .requirement-counts small, .meter strong small {
  color: var(--el-text-color-secondary); font-size: 12px; font-weight: 400;
}
.ratio { margin-inline-start: 8px; }
.todo, .requirement-counts { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; }
.requirement-counts > div { display: grid; }
.requirement-counts > div + div { padding-inline-start: 8px; border-inline-start: 1px solid var(--el-border-color-lighter); }
.meter {
  display: grid; grid-template-columns: minmax(55px, auto) minmax(28px, 1fr) auto;
  align-items: center; gap: 8px; max-width: 260px; font-size: 12px;
}
.meter strong, .requirement-counts strong { font-variant-numeric: tabular-nums; white-space: nowrap; }
.track { display: block; height: 5px; border-radius: 4px; background: var(--el-border-color-lighter); }
.track > span { display: block; height: 100%; border-radius: inherit; background: var(--el-color-primary); }
[data-over='true'] strong { color: var(--el-color-warning-dark-2); }
[data-over='true'] .track > span { background: var(--el-color-warning); }
</style>
