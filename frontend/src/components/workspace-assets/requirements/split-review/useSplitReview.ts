import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { useWorkspaceAssets } from '@/composables/useWorkspaceAssets'
import { useProvisioningStore } from '@/stores/provisioning'
import { useAuthStore } from '@/stores/auth'
import type { RequirementDetail } from '@/types/workspaceAssets'
import api from '@/utils/api'
import { backendFetch } from '@/utils/http'
import { createDraftPersistence, type DraftStatus } from './draftPersistence'
import { buildConfirmItems, buildDraft, createSplitItem, restoreSplitItems, type EditableSplitItem } from './model'

export function useSplitReview(identity: { wsId: string; requirementId: string; batchId: string }) {
  const { wsId, requirementId, batchId } = identity
  const router = useRouter()
  const { t } = useI18n()
  const assets = useWorkspaceAssets()
  const provisioning = useProvisioningStore()
  const loading = ref(true)
  const submitting = ref(false)
  const discarding = ref(false)
  const discardConfirmOpen = ref(false)
  const detail = ref<RequirementDetail | null>(null)
  const items = ref<EditableSplitItem[]>([])
  const activeIndex = ref(0)
  const changeReason = ref('')
  const draftStatus = ref<DraftStatus>('idle')
  const savedTime = ref('')
  let disposed = false
  const draft = createDraftPersistence({
    snapshot: () => buildDraft(items.value, changeReason.value),
    save: payload => assets.saveRequirementSplitDraft(wsId, batchId, payload),
    status(status) {
      if (disposed) return
      draftStatus.value = status
      if (status === 'saved') savedTime.value = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    },
  })
  const parentRequirement = computed(() => detail.value?.requirement || null)
  const activeItem = computed({
    get: () => items.value[activeIndex.value] || null,
    set(value: EditableSplitItem | null) { if (value) items.value[activeIndex.value] = value },
  })
  const selectedCount = computed(() => items.value.filter(item => item.include).length)
  const allSelected = computed({
    get: () => items.value.length > 0 && items.value.every(item => item.include),
    set(value: boolean) { items.value = items.value.map(item => ({ ...item, include: value })) },
  })
  const draftStatusText = computed(() => {
    if (draftStatus.value === 'saving') return t('workspace_assets.requirements.split_review.draft_saving')
    if (draftStatus.value === 'saved') return t('workspace_assets.requirements.split_review.draft_saved', { time: savedTime.value })
    if (draftStatus.value === 'error') return t('workspace_assets.requirements.split_review.draft_save_failed')
    return ''
  })

  function addNewItem() { items.value.push(createSplitItem()); activeIndex.value = items.value.length - 1 }
  function removeItem(index: number) {
    items.value.splice(index, 1)
    if (index < activeIndex.value) activeIndex.value -= 1
    activeIndex.value = Math.max(0, Math.min(activeIndex.value, items.value.length - 1))
  }
  function setIncluded(id: string, include: boolean) {
    const item = items.value.find(candidate => candidate.item_id === id)
    if (item) item.include = include
  }
  function dismissBatchJob() {
    const job = provisioning.jobList.find(candidate => candidate.kind === 'requirement_split_preview' && candidate.batch?.id === batchId)
    if (job) provisioning.dismiss(job.jobId)
  }
  const navigateBack = () => router.push({ name: 'workspaceAssetsRequirementDetail', params: { wsId, requirementId } })
  async function goBack() {
    if (await draft.flush()) await navigateBack()
  }
  async function confirmDiscard() {
    if (discarding.value || submitting.value) return
    discarding.value = true
    await draft.close()
    try {
      if (!await assets.clearRequirementSplitDraft(wsId, batchId)) {
        draft.open()
        ElMessage.error(t('workspace_assets.requirements.split_review.draft_discard_failed'))
        return
      }
      discardConfirmOpen.value = false
      dismissBatchJob()
      ElMessage.success(t('workspace_assets.requirements.split_review.draft_discarded'))
      await navigateBack()
    } catch {
      draft.open()
      ElMessage.error(t('workspace_assets.requirements.split_review.draft_discard_failed'))
    } finally { discarding.value = false }
  }
  async function handleConfirm() {
    if (!selectedCount.value || submitting.value || discarding.value) return
    submitting.value = true
    await draft.close()
    try {
      const result = await assets.confirmRequirementSplit(wsId, requirementId, {
        batch_id: batchId, items: buildConfirmItems(items.value), change_reason: changeReason.value.trim() || null,
      })
      if (!result) { draft.open(); return }
      dismissBatchJob()
      ElMessage.success(t('workspace_assets.requirements.split_review.confirm_success'))
      await navigateBack()
    } catch { draft.open() } finally { submitting.value = false }
  }
  function saveOnPageExit() {
    const token = useAuthStore().token
    if (!token || !draft.canSaveOnExit()) return
    const url = `${api.defaults.baseURL}/workspaces/${wsId}/workspace-assets/requirements/import-batches/${batchId}/draft`
    void backendFetch(url, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(buildDraft(items.value, changeReason.value)), keepalive: true,
    }).catch(() => {})
  }
  const onVisibility = () => { if (document.visibilityState === 'hidden') void draft.flush() }
  watch([items, changeReason], () => draft.schedule(), { deep: true, flush: 'sync' })
  onBeforeRouteLeave(() => draft.flush())
  onMounted(async () => {
    window.addEventListener('pagehide', saveOnPageExit)
    document.addEventListener('visibilitychange', onVisibility)
    try {
      const [requirement, batch] = await Promise.all([assets.loadRequirementDetail(wsId, requirementId), assets.loadImportBatch(wsId, batchId)])
      if (disposed) return
      detail.value = requirement
      if (batch) {
        items.value = restoreSplitItems(batch, batch.draft)
        changeReason.value = batch.draft?.change_reason || ''
        if (batch.draft) ElMessage.info(t('workspace_assets.requirements.split_review.draft_restored'))
      }
      await nextTick()
      if (!disposed) draft.open()
    } catch {
      if (!disposed) draftStatus.value = 'error'
    } finally { if (!disposed) loading.value = false }
  })
  onBeforeUnmount(() => {
    disposed = true
    draft.dispose()
    window.removeEventListener('pagehide', saveOnPageExit)
    document.removeEventListener('visibilitychange', onVisibility)
  })
  return { loading, submitting, discarding, discardConfirmOpen, parentRequirement, items, activeIndex, activeItem, changeReason, selectedCount, allSelected, draftStatus, draftStatusText, addNewItem, removeItem, setIncluded, goBack, confirmDiscard, handleConfirm }
}
