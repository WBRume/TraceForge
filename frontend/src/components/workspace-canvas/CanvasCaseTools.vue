<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { BookMarked, Workflow } from '@/components/icons'
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
const loading = shallowRef(false)
const error = shallowRef('')
let searchSequence = 0

watch(workspaceId, () => { void loadWorkspace().catch(() => {}) }, { immediate: true })
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
watch(active, type => { if (type === 'promotion' && canCreateTask.value) void lookup('') })
watch(canCreateTask, allowed => { if (allowed && active.value === 'promotion') void lookup('') })

async function lookup(q: string) {
  const request = ++searchSequence
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get<{ items: { id: string; title: string }[] }>(`/workspaces/${workspaceId.value}/cases`, {
      params: { q, status: 'APPROVED', page_size: 50 },
    })
    if (request !== searchSequence) return
    const selected = new Set(picked.value)
    const known = new Map(cases.value.filter(item => selected.has(item.id)).map(item => [item.id, item]))
    for (const item of data.items) known.set(item.id, item)
    cases.value = [...known.values()]
  } catch (cause) {
    if (request === searchSequence) error.value = formatApiError(cause, t('workspace_canvas.load_failed'), t)
  } finally {
    if (request === searchSequence) loading.value = false
  }
}
</script>

<template>
  <section class="case-tools">
    <nav class="case-tool-tabs" :aria-label="t('workspace_canvas.actions.case_tools')">
      <button type="button" :aria-pressed="active === 'playbooks'" @click="active = 'playbooks'">
        <Workflow :size="16" />{{ t('workspace_canvas.actions.playbooks') }}
      </button>
      <button v-if="canCreateTask || requestedJob" type="button" :aria-pressed="active === 'promotion'" @click="active = 'promotion'">
        <BookMarked :size="16" />{{ t('workspace_canvas.actions.case_promotion') }}
      </button>
    </nav>
    <PlaybookLibrary v-if="active === 'playbooks'" :workspace-id="workspaceId" />
    <section v-else class="promotion-tools">
      <el-select v-if="canCreateTask" v-model="picked" remote filterable multiple :remote-method="lookup" :loading="loading"
        :multiple-limit="20" :placeholder="t('workspace_canvas.actions.choose_cases')" :aria-label="t('workspace_canvas.actions.choose_cases')">
        <el-option v-for="item in cases" :key="item.id" :value="item.id" :label="item.title" />
      </el-select>
      <CasePromotionAction :workspace-id="workspaceId" :case-ids="picked" :requested-job-id="requestedJob" />
      <p v-if="error" role="alert">{{ error }}</p>
    </section>
  </section>
</template>

<style scoped>
.case-tools { padding: 16px; }
.case-tool-tabs { display: flex; gap: 6px; margin-bottom: 16px; }
.case-tool-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 11px;
  font: inherit;
  font-size: 13px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  color: #475569;
  cursor: pointer;
}
.case-tool-tabs button[aria-pressed='true'] { color: #0369a1; border-color: #7dd3fc; background: #f0f9ff; }
.promotion-tools { display: grid; gap: 12px; }
.promotion-tools .btn-primary { justify-self: start; }
</style>
