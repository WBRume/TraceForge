<script setup lang="ts">
import { computed, reactive, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import BaseSelect from '@/components/BaseSelect.vue'
import { Inbox, SlidersHorizontal } from '@/components/icons'
import UserAvatar from '@/components/user/UserAvatar.vue'
import { useWorkspaceMemberWorkload } from '@/composables/useWorkspaceWorkload'
import { formatApiError } from '@/utils/error'
import MemberWorkloadTable from './MemberWorkloadTable.vue'
import MemberWorkloadDetails from './MemberWorkloadDetails.vue'
import MemberWorkloadSources from './MemberWorkloadSources.vue'
import { countsFromSummary } from './workloadCounts'
import type { WorkloadLimits } from '@/types/workload'

const props = defineProps<{ workspaceId: string }>()
const { t } = useI18n()
const prefix = 'workspace_assets.workload.'
const { data, failed, loading, saveLimits } = useWorkspaceMemberWorkload(() => props.workspaceId)
const query = shallowRef('')
const scope = shallowRef('all')
const selected = shallowRef<string | null>(null)
const editing = shallowRef(false)
const saving = shallowRef(false)
const fields = ['background', 'interactive', 'ongoing'] as const
const limitInput = reactive<WorkloadLimits>({ background: null, interactive: null, ongoing: null })
const options = computed(() => ['all', 'only_pending'].map(value => ({ value, label: t(prefix + value) })))
const visible = computed(() => {
  const text = query.value.trim().toLocaleLowerCase()
  return (data.value?.members || []).map(member => ({ member, counts: countsFromSummary(member.counts) })).filter(
    row => row.member.display_name.toLocaleLowerCase().includes(text) && (scope.value === 'all' || row.counts.pending),
  ).sort((a, b) => b.counts.overdue - a.counts.overdue || b.counts.pending - a.counts.pending
    || a.member.display_name.localeCompare(b.member.display_name)).map(row => row.member)
})
const member = computed(() => data.value?.members.find(item => item.user_id === selected.value))
const showUnassigned = computed(() => selected.value === 'unassigned')
const unassignedCount = computed(() => data.value?.unassigned.length ?? 0)
const drawerOpen = computed({
  get: () => Boolean(selected.value),
  set: value => { if (!value) selected.value = null },
})

watch(() => props.workspaceId, () => {
  selected.value = null
  editing.value = false
})

function editLimits() {
  if (!member.value) return
  Object.assign(limitInput, member.value.limits)
  editing.value = true
}

async function submitLimits() {
  if (!member.value || saving.value) return
  saving.value = true
  try {
    await saveLimits(member.value.user_id, { ...limitInput })
    editing.value = false
  } catch (error) {
    ElMessage.error(formatApiError(error, t(prefix + 'unavailable'), t))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="asset-table-workbench">
    <header class="table-toolbar">
      <div class="workload-title">
        <h3>{{ t(prefix + 'title') }}</h3>
        <span>{{ t(prefix + 'cross_workspace') }}</span>
      </div>
      <el-button v-if="unassignedCount" :icon="Inbox" aria-haspopup="dialog" @click="selected = 'unassigned'">
        {{ t(prefix + 'unassigned', { count: unassignedCount }) }}
      </el-button>
    </header>
    <el-form class="query-bar" label-position="top" @submit.prevent>
      <div class="query-grid">
        <el-form-item class="search-field" :label="t(prefix + 'member')">
          <el-input v-model="query" clearable :placeholder="t(prefix + 'search')" />
        </el-form-item>
        <el-form-item class="select-field">
          <BaseSelect v-model="scope" :options="options" :aria-label="t(prefix + 'member')" />
        </el-form-item>
      </div>
    </el-form>
    <el-alert v-if="failed" type="warning" :closable="false" :title="t(prefix + (data ? 'stale' : 'unavailable'))" />
    <MemberWorkloadTable v-if="data || !failed" v-loading="!data && loading" :members="visible" @open="selected = $event" />
    <footer v-if="data?.observation_gaps" class="workload-footer">
      <small>{{ t(prefix + 'gaps', { count: data.observation_gaps }) }}</small>
    </footer>

    <el-drawer
      v-model="drawerOpen"
      class="workload-drawer"
      size="min(520px, 100vw)"
      destroy-on-close
      append-to-body
    >
      <template #header="{ titleId, titleClass }">
        <div class="drawer-heading">
          <UserAvatar v-if="member" :display-name="member.display_name" :avatar-url="member.avatar_url" aria-hidden="true" />
          <span v-else class="drawer-icon" aria-hidden="true"><Inbox /></span>
          <h2 :id="titleId" :class="titleClass">
            {{ showUnassigned ? t(prefix + 'unassigned_title') : member?.display_name }}
          </h2>
        </div>
      </template>
      <MemberWorkloadSources
        v-if="data && member"
        :key="member.user_id"
        :workspace-id="workspaceId"
        :sources="member.sources"
        :as-of="data.as_of"
        :limits="member.limits"
      />
      <MemberWorkloadDetails
        v-else-if="data && showUnassigned"
        :workspace-id="workspaceId"
        :as-of="data.as_of"
        :items="data.unassigned"
      />
      <template v-if="data?.can_edit_limits && member" #footer>
        <el-button :icon="SlidersHorizontal" @click="editLimits">{{ t(prefix + 'limits') }}</el-button>
      </template>
    </el-drawer>
    <el-dialog v-model="editing" :title="t(prefix + 'limits')" width="min(420px, 92vw)" append-to-body>
      <el-form id="workload-limits" label-position="top" @submit.prevent="submitLimits">
        <el-form-item v-for="field in fields" :key="field" :label="t(prefix + field)">
          <el-input-number v-model="limitInput[field]" :min="0" :max="999" :precision="0" :value-on-clear="null"
            :placeholder="t(prefix + 'unset')" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editing = false">{{ t('common.cancel') }}</el-button>
        <el-button form="workload-limits" native-type="submit" type="primary" :loading="saving">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped src="../asset-table-workbench.css"></style>
<style scoped>
.query-grid { align-items: flex-end; }
.workload-footer { color: var(--el-text-color-secondary); }
.workload-title { display: flex; flex-wrap: wrap; align-items: baseline; column-gap: 10px; }
.workload-title > span { color: var(--color-text-muted); font-size: 12px; }

.drawer-heading {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 12px;
  min-width: 0;
  margin-inline-end: 12px;
}

.drawer-heading h2 {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}

.drawer-icon {
  display: grid;
  flex: 0 0 36px;
  height: 36px;
  place-items: center;
  border-radius: var(--radius-md);
  background: var(--color-primary-50);
  color: var(--color-primary-700);
}

.drawer-icon svg {
  width: 18px;
  height: 18px;
}

@media (max-width: 660px) { .search-field { min-width: 100%; } }
</style>

<style>
.workload-drawer .el-drawer__body {
  background: var(--color-bg-base);
}

.workload-drawer .el-drawer__footer {
  padding: 16px 24px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
