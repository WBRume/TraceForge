<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import UserAvatar from '@/components/user/UserAvatar.vue'
import type { MemberWorkloadOverview } from '@/types/workload'
import { countsFromSummary } from './workloadCounts'

const props = defineProps<{ members: readonly MemberWorkloadOverview[] }>()
const emit = defineEmits<{ open: [userId: string] }>()
const { t } = useI18n()
const prefix = 'workspace_assets.workload.'
const rows = computed(() => props.members.map(member => ({ ...member, totals: countsFromSummary(member.counts) })))
const slots = ['background', 'interactive'] as const
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
        <div v-if="row.totals.pending" class="todo">
          <strong>{{ row.totals.pending }}</strong>
          <el-tag v-for="item in row.totals.pendingByKind" :key="item.kind" size="small" type="info">
            {{ t(prefix + item.kind) }} {{ item.count }}
          </el-tag>
        </div>
        <span v-else class="muted">{{ t(prefix + 'no_pending') }}</span>
      </template>
    </el-table-column>
    <el-table-column :label="t(prefix + 'sessions')" min-width="160">
      <template #default="{ row }">
        <div v-for="slot in slots" :key="slot" class="session-count">
          <span>{{ t(prefix + slot) }}</span>
          <strong>{{ row.totals[slot] }}</strong>
        </div>
        <small v-if="row.totals.incomplete" class="muted">{{ t(prefix + 'incomplete') }} {{ row.totals.incomplete }}</small>
      </template>
    </el-table-column>
    <el-table-column :label="t(prefix + 'requirements')" min-width="120">
      <template #default="{ row }">
        <div class="requirement-counts">
          <div>
            <strong>{{ row.totals.ongoing }}</strong>
            <small>{{ t(prefix + 'ongoing') }}</small>
          </div>
          <div><strong>{{ row.totals.planned }}</strong><small>{{ t(prefix + 'planned') }}</small></div>
        </div>
      </template>
    </el-table-column>
    <el-table-column :label="t(prefix + 'attention')" min-width="148">
      <template #default="{ row }">
        <div class="todo">
          <el-tag v-if="row.totals.overdue" type="warning" size="small">{{ t(prefix + 'overdue', { count: row.totals.overdue }) }}</el-tag>
          <el-tag v-if="row.totals.expected" type="info" size="small">{{ t(prefix + 'return_count', { count: row.totals.expected }) }}</el-tag>
          <el-tag v-if="row.totals.paused" type="info" size="small">{{ t(prefix + 'paused_check') }} {{ row.totals.paused }}</el-tag>
          <el-tag v-if="row.totals.uncertain" type="warning" size="small">{{ t(prefix + 'uncertain') }} {{ row.totals.uncertain }}</el-tag>
          <span v-if="!row.totals.overdue && !row.totals.expected && !row.totals.paused && !row.totals.uncertain" class="muted">—</span>
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
.muted, .identity small, .requirement-counts small {
  color: var(--el-text-color-secondary); font-size: 12px; font-weight: 400;
}
.todo, .requirement-counts { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; }
.requirement-counts > div { display: grid; }
.requirement-counts > div + div { padding-inline-start: 8px; border-inline-start: 1px solid var(--el-border-color-lighter); }
.session-count {
  display: flex; justify-content: space-between; align-items: center;
  gap: 8px; max-width: 130px; padding-inline-end: 8px; font-size: 12px;
}
.session-count strong, .requirement-counts strong { font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
