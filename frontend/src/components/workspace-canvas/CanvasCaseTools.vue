<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import CasePromotionAction from '@/components/case-center/CasePromotionAction.vue'
import PlaybookLibrary from '@/components/case-center/PlaybookLibrary.vue'
import { useWorkspaceContext } from '@/composables/chat/tasklist/useWorkspaceContext'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'

const route = useRoute()
const { t } = useI18n()
const workspaceId = computed(() => String(route.params.wsId))
const requestedJob = computed(() => typeof route.query.promotionJob === 'string' ? route.query.promotionJob : '')
const requestedCase = computed(() => typeof route.query.case === 'string' ? route.query.case : '')
const active = shallowRef<'playbooks' | 'promotion'>(requestedJob.value || requestedCase.value ? 'promotion' : 'playbooks')
const { canCreateTask, loadWorkspace } = useWorkspaceContext({ getWorkspaceId: () => workspaceId.value })
const cases = shallowRef<{ id: string; title: string }[]>([])
const picked = shallowRef<string[]>([])
const query = shallowRef('')
const loading = shallowRef(false)
const error = shallowRef('')
const options = computed(() => cases.value.map(item => ({
  value: item.id, label: item.title, disabled: picked.value.length >= 20 && !picked.value.includes(item.id),
})))

watch(workspaceId, () => {
  cases.value = []
  picked.value = []
  query.value = ''
  loading.value = false
  error.value = ''
  void loadWorkspace().catch(() => {})
}, { immediate: true })
watch(requestedJob, id => { if (id) active.value = 'promotion' })
watch([requestedCase, canCreateTask, workspaceId], async ([id, allowed, workspace], _, onCleanup) => {
  if (!id || !allowed) return
  active.value = 'promotion'
  let current = true
  onCleanup(() => { current = false })
  try {
    const { data } = await api.get<{ id: string; title: string; status: string }>(`/workspaces/${workspace}/cases/${encodeURIComponent(id)}`)
    if (current && data.status === 'APPROVED') {
      picked.value = [...new Set([...picked.value, data.id])]
      if (!cases.value.some(item => item.id === data.id)) cases.value = [data, ...cases.value]
    }
  } catch (cause) {
    if (current) error.value = formatApiError(cause, t('workspace_canvas.load_failed'), t)
  }
}, { immediate: true })
watch([active, canCreateTask, workspaceId, query], ([type, allowed, workspace, keyword], _, cleanup) => {
  if (type !== 'promotion' || !allowed) return
  const request = new AbortController()
  const timer = setTimeout(() => void lookup(workspace, keyword, request.signal), keyword ? 180 : 0)
  cleanup(() => { clearTimeout(timer); request.abort() })
}, { immediate: true })

async function lookup(workspace: string, keyword: string, signal: AbortSignal) {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get<{ items: { id: string; title: string }[] }>(`/workspaces/${workspace}/cases`, {
      params: { keyword: keyword.trim(), status: 'APPROVED', page_size: 50 }, signal,
    })
    if (signal.aborted) return
    const selected = new Set(picked.value)
    const known = new Map(cases.value.filter(item => selected.has(item.id)).map(item => [item.id, item]))
    for (const item of data.items) known.set(item.id, item)
    cases.value = [...known.values()]
  } catch (cause) {
    if (!signal.aborted) error.value = formatApiError(cause, t('workspace_canvas.load_failed'), t)
  } finally {
    if (!signal.aborted) loading.value = false
  }
}
</script>

<template>
  <section class="case-tools">
    <el-tabs v-model="active">
      <el-tab-pane name="playbooks" :label="t('workspace_canvas.actions.playbooks')">
        <PlaybookLibrary v-if="active === 'playbooks'" :workspace-id="workspaceId" />
      </el-tab-pane>
      <el-tab-pane v-if="canCreateTask || requestedJob" name="promotion" :label="t('workspace_canvas.actions.case_promotion')">
        <div v-if="active === 'promotion'" class="promotion-tools">
          <BaseSelect v-if="canCreateTask" v-model="picked" :options="options" searchable remote-search multiple
            :placeholder="t('workspace_canvas.actions.choose_cases')" :aria-label="t('workspace_canvas.actions.choose_cases')"
            :search-placeholder="t('workspace_canvas.domains.search_by_title')" @open="query = ''" @search="query = $event" />
          <span v-if="loading" role="status">{{ t('common.loading') }}</span>
          <CasePromotionAction :workspace-id="workspaceId" :case-ids="picked" :requested-job-id="requestedJob" />
          <p v-if="error" role="alert">{{ error }}</p>
        </div>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>
.case-tools { padding: 16px; }
.promotion-tools { display: grid; gap: 12px; }
.case-tools :deep(.el-tabs__content) { overflow: visible; }
.promotion-tools .btn-primary { justify-self: start; }
</style>
