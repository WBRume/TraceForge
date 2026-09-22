<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import router from '@/router'
import api from '@/utils/api'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import RequirementImportDialog from '@/components/workspace-assets/requirements/RequirementImportDialog.vue'
import type { PromotionJob, PromotionDraft } from '@/types/playbookPromotion'
import CasePromotionReview from './CasePromotionReview.vue'
import { useProvisioningStore } from '@/stores/provisioning'
const props = defineProps<{ workspaceId: string; caseIds: string[]; requestedJobId?: string }>()
const floating = useProvisioningStore()
const emit = defineEmits<{ completed: [] }>()
type Job = PromotionJob
const confirm = shallowRef(false)
const open = shallowRef(false)
const busy = shallowRef(false)
const job = shallowRef<Job | null>(null)
const error = shallowRef('')
const reviewDraft = ref<PromotionDraft | null>(null)
const pendingReview = computed(() => job.value?.result?.review_state === 'PENDING')
const active = computed(() => job.value && !['SUCCESS', 'FAILED', 'CANCELLED', 'REVERTED'].includes(job.value.status))
const hasWork = computed(() => active.value || pendingReview.value)
let draftIdentity = ''
let regenerationKey = ''
let generation = 0
let readVersion = 0
let key = ''
let signature = ''
let completedId = ''
const accept = (value: Job) => {
  if (job.value?.job_id === value.job_id && ['SUCCESS', 'FAILED', 'CANCELLED', 'REVERTED'].includes(job.value.status) && !['SUCCESS', 'FAILED', 'CANCELLED', 'REVERTED'].includes(value.status)) return
  job.value = value
  const identity = `${value.job_id}:${value.result?.draft_revision || ''}`
  if (identity !== draftIdentity) {
    draftIdentity = identity
    reviewDraft.value = value.result?.draft ? JSON.parse(JSON.stringify(value.result.draft)) : null
  }
  floating.ingestPromotionJob(value, open.value)
  if (value.result?.spec_ids?.length && completedId !== value.job_id) { completedId = value.job_id; emit('completed') }
}
const reload = async () => {
  if (!props.workspaceId) return
  const captured = generation
  const version = ++readVersion
  try {
    const targetId = job.value?.job_id || props.requestedJobId
    const endpoint = `/workspaces/${props.workspaceId}/cases/playbook-promotions`
    const { data } = await api.get(endpoint, { params: targetId ? { job_id: targetId } : {} })
    if (captured !== generation || version !== readVersion) return
    let current: Job | undefined = data.items.find((item: Job) => item.job_id === targetId)
      || data.items.find((item: Job) => item.result?.review_state === 'PENDING' || !['SUCCESS', 'FAILED', 'CANCELLED', 'REVERTED'].includes(item.status))
    const visited = new Set<string>()
    while (current?.result?.replacement_job_id && !visited.has(current.job_id)) {
      visited.add(current.job_id)
      const response = await api.get(endpoint, { params: { job_id: current.result.replacement_job_id } })
      if (captured !== generation || version !== readVersion) return
      current = response.data.items[0]
    }
    if (current) accept(current)
  } catch { if (captured === generation) error.value = '晋升进度加载失败' }
}
const start = async () => {
  if (busy.value) return
  const captured = generation
  const next = JSON.stringify([props.workspaceId, [...props.caseIds].sort()])
  if (signature !== next) { signature = next; key = crypto.randomUUID() }
  busy.value = true; error.value = ''
  try {
    const { data } = await api.post(`/workspaces/${props.workspaceId}/cases/playbook-promotions`, { case_ids: props.caseIds, idempotency_key: key })
    if (captured !== generation) return
    open.value = true; accept(data); confirm.value = false; signature = ''; key = ''
    await reload()
  } catch (e: any) { if (captured === generation) error.value = e.response?.data?.detail?.code === 'CASE_NOT_APPROVED' ? '只有评审入库的案例才能晋升，请刷新案例列表' : '晋升启动失败' }
  finally { if (captured === generation) busy.value = false }
}
const close = async () => {
  if (busy.value) return
  if (pendingReview.value) { minimize(); return }
  if (!active.value) { open.value = false; if (job.value) floating.dismiss(job.value.job_id); return }
  const captured = generation
  try {
    const { data } = await api.post(`/workspaces/${props.workspaceId}/cases/playbook-promotions/${job.value!.job_id}/cancel`)
    if (captured === generation) accept(data)
  } catch { if (captured === generation) error.value = '取消失败，请重试' }
}
const reviewAction = async (action: 'confirm' | 'discard' | 'regenerate') => {
  if (!job.value || !pendingReview.value || busy.value) return
  const captured = generation
  const current = job.value
  busy.value = true; error.value = ''
  if (action === 'regenerate' && !regenerationKey) regenerationKey = crypto.randomUUID()
  try {
    const { data } = await api.post(`/workspaces/${props.workspaceId}/cases/playbook-promotions/${current.job_id}/${action}`, {
      draft_revision: current.result?.draft_revision,
      ...(action === 'confirm' && reviewDraft.value ? { draft: { ...reviewDraft.value, playbooks: reviewDraft.value.playbooks.map(candidate => ({
        ...candidate, symptoms: candidate.symptoms.map(v => v.trim()).filter(Boolean), steps: candidate.steps.map(v => v.trim()).filter(Boolean),
      })) } } : {}),
      ...(action === 'regenerate' ? { idempotency_key: regenerationKey } : {}),
    })
    if (captured !== generation) return
    if (action === 'regenerate') { floating.dismiss(current.job_id); regenerationKey = '' }
    accept(data)
    if (action === 'discard') { open.value = false; floating.dismiss(current.job_id) }
  } catch (e: any) {
    if (captured !== generation) return
    const code = e.response?.data?.detail?.code
    error.value = code === 'PROMOTION_DRAFT_CHANGED' ? '草案已在其他页面处理，请重新查看' : code === 'CASE_NOT_APPROVED' ? '案例评审状态已变更，无法入库' : '操作失败，请检查草案内容后重试'
    if (code === 'PROMOTION_DRAFT_CHANGED') await reload()
  } finally { if (captured === generation) busy.value = false }
}
const onUpdate = (event: Event) => {
  if ((event as CustomEvent).detail?.workspace_id === props.workspaceId) void reload()
}
const resync = () => { void reload() }
const showProgress = () => { open.value = true; void reload() }
const minimize = () => {
  if (job.value) { floating.ingestPromotionJob(job.value); floating.minimizePreviewJob(job.value.job_id) }
  open.value = false
}
const handleActionClick = () => {
  if (hasWork.value) {
    if (job.value?.job_id && router && typeof router.push === 'function') {
      try {
        void router.push({
          name: 'workspaceCasePromotionReview',
          params: { wsId: props.workspaceId, jobId: job.value.job_id },
        })
      } catch {
        // ignore routing failure in isolated test harness
      }
    }
    showProgress()
  } else {
    confirm.value = true
  }
}
const onOpen = (event: Event) => {
  if ((event as CustomEvent).detail?.jobId === job.value?.job_id) showProgress()
}
watch(() => [props.workspaceId, props.requestedJobId], () => {
  if (hasWork.value) minimize()
  generation++; job.value = null; open.value = Boolean(props.requestedJobId); confirm.value = false; busy.value = false; error.value = ''; void reload()
}, { immediate: true })
onMounted(() => { window.addEventListener('playbook-promotion-open', onOpen); window.addEventListener('playbook-promotion-updated', onUpdate); window.addEventListener('playbook-promotion-resync', resync) })
onUnmounted(() => { if (hasWork.value) minimize(); generation++; window.removeEventListener('playbook-promotion-open', onOpen); window.removeEventListener('playbook-promotion-updated', onUpdate); window.removeEventListener('playbook-promotion-resync', resync) })
</script>
<template>
  <button class="btn-primary" :disabled="!workspaceId || (!hasWork && !caseIds.length) || caseIds.length > 20" @click="handleActionClick">{{ pendingReview ? '确认晋升草案' : active ? '查看晋升进度' : `晋升诊断规程${caseIds.length ? `（${caseIds.length}）` : ''}` }}</button>
  <span v-if="error" role="alert">{{ error }} <button @click="reload">刷新</button></span>
  <ConfirmActionModal :show="confirm" title="案例晋升诊断规程" :message="`将所选 ${caseIds.length} 个案例交给 AI 提炼诊断规程与症状短语。`" cancel-text="取消" confirm-text="开始晋升" tone="primary" :loading="busy" @cancel="confirm = false" @confirm="start" />
  <RequirementImportDialog :open="open" mode="promotion" :batch="null" :preview-job="job" :review-pending="pendingReview" @close="close" @minimize="minimize" @clear-preview-job="close">
    <template #promotion><CasePromotionReview v-if="reviewDraft" v-model="reviewDraft" :cases="job?.cases || []" :busy="busy" :error="error" @confirm="reviewAction('confirm')" @discard="reviewAction('discard')" @merge="reviewAction('regenerate')" /></template>
  </RequirementImportDialog>
</template>
