<script setup lang="ts">
import { computed, reactive, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import RequirementEditDrawer from './RequirementEditDrawer.vue'
import RequirementImportDialog from './RequirementImportDialog.vue'
import RequirementTableWorkbench from './RequirementTableWorkbench.vue'
import { useWorkspaceAssets } from '@/composables/useWorkspaceAssets'
import { useProvisioningStore, type ProvisionJobView } from '@/stores/provisioning'
import { formatApiError } from '@/utils/error'
import type {
  RequirementImportBatch,
  RequirementImportConfirmPayload,
  RequirementListQuery,
  RequirementMutationPayload,
  RequirementPreviewJob,
  RequirementSplitPayload,
  RequirementSummary,
  WorkspaceAssetsRequirements,
} from '@/types/workspaceAssets'

const props = defineProps<{
  workspaceId: string
  requirements: readonly RequirementSummary[]
  loading?: boolean
}>()

const emit = defineEmits<{
  refresh: []
}>()

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const {
  loading: actionLoading,
  error,
  loadRequirements,
  createRequirement,
  updateRequirement,
  createRequirementImportPreviewJob,
  fetchRequirementPreviewJob,
  listActiveRequirementPreviewJobs,
  directImportRequirement,
  confirmRequirementImport,
  createRequirementSplitPreviewJob,
  confirmRequirementSplit,
  findRequirementSplitDraft,
} = useWorkspaceAssets()
const provisioningStore = useProvisioningStore()

function routeString(key: string): string | undefined {
  const value = route.query[key]
  return typeof value === 'string' && value.trim() ? value : undefined
}

function routeNumber(key: string, fallback: number): number {
  const value = Number(routeString(key))
  return Number.isFinite(value) && value > 0 ? value : fallback
}

const tableQuery = reactive<RequirementListQuery>({
  q: routeString('q'),
  status: routeString('status'),
  priority: routeString('priority'),
  source_kind: routeString('source_kind'),
  parent_id: routeString('parentId'),
  scope: 'tree',
  sort_by: (routeString('sort_by') as RequirementListQuery['sort_by']) || 'updated_at',
  sort_order: (routeString('sort_order') as RequirementListQuery['sort_order']) || 'desc',
  page: routeNumber('page', 1),
  page_size: routeNumber('page_size', 20),
})
const requirementsResponse = shallowRef<WorkspaceAssetsRequirements | null>(null)
const editorOpen = shallowRef(false)
const editingRequirement = shallowRef<RequirementSummary | null>(null)
const childParent = shallowRef<RequirementSummary | null>(null)
const createOpen = shallowRef(false)
// AI 预览作业：创建后交给右下角浮窗后台跟踪（分钟级等待不再阻塞弹窗/页面）
const createPreviewJobId = shallowRef('')
const splitDialogOpen = shallowRef(false)
const splitRequirementId = shallowRef('')

function trackedJobToPreviewJob(job: ProvisionJobView | null): RequirementPreviewJob | null {
  if (!job) return null
  return {
    job_id: job.jobId,
    workspace_id: job.workspaceId,
    status: job.status,
    progress: job.progress,
    message: job.message || null,
    error: job.errorMessage || null,
    batch: job.batch,
    cancel_requested: job.cancelRequested,
  }
}

const createPreviewJob = computed<RequirementPreviewJob | null>(() => (
  trackedJobToPreviewJob(provisioningStore.getTrackedJob(createPreviewJobId.value))
))

const createBatch = computed<RequirementImportBatch | null>(() => {
  const job = provisioningStore.getTrackedJob(createPreviewJobId.value)
  return job?.status === 'SUCCESS' ? job.batch : null
})

// 拆分预览作业绑定：优先非终态（进行中），否则最近一条（SUCCESS 带批次可确认）
const splitTrackedJob = computed<ProvisionJobView | null>(() => {
  const reqId = splitRequirementId.value
  if (!reqId) return null
  const matched = provisioningStore.jobList.filter(
    (job) => job.kind === 'requirement_split_preview' && job.requirementId === reqId,
  )
  return matched.find((job) => !job.terminal) || matched[matched.length - 1] || null
})

const splitPreviewJob = computed<RequirementPreviewJob | null>(() => trackedJobToPreviewJob(splitTrackedJob.value))

const splitBatch = computed<RequirementImportBatch | null>(() => (
  splitTrackedJob.value?.status === 'SUCCESS' ? splitTrackedJob.value.batch : null
))

function navigateToSplitReview(requirementId: string, batch: RequirementImportBatch) {
  splitDialogOpen.value = false
  splitRequirementId.value = ''
  void router.push({
    name: 'workspaceAssetRequirementSplitReview',
    params: {
      wsId: props.workspaceId,
      requirementId,
      batchId: batch.id,
    },
    state: {
      batchJson: JSON.stringify(batch),
    },
  })
}

watch(
  () => splitTrackedJob.value,
  (job) => {
    // 取消已收敛（CANCELLED 自动清理）或作业被移除时，弹窗失去绑定对象：
    // 直接关闭，避免回落到无批次的空白编辑态
    if (!job && splitDialogOpen.value) {
      splitDialogOpen.value = false
      splitRequirementId.value = ''
      return
    }
    if (job?.status === 'SUCCESS' && job.batch) {
      navigateToSplitReview(splitRequirementId.value || job.requirementId || '', job.batch)
    }
  },
)

const fallbackResponse = computed<WorkspaceAssetsRequirements>(() => ({
  workspace_id: props.workspaceId,
  items: [...props.requirements],
  total: props.requirements.length,
  page: 1,
  page_size: 20,
  scope: 'tree',
  state: {
    empty: props.requirements.length === 0,
    message: props.requirements.length ? null : 'Requirement source is not connected or has no records.',
  },
  connection_status: [],
}))
const activeResponse = computed(() => requirementsResponse.value || fallbackResponse.value)
const requirementItems = computed(() => activeResponse.value.items)
const requestedRequirementId = computed(() => {
  const value = route.query.requirementId
  return typeof value === 'string' ? value : null
})

function currentQuery(): RequirementListQuery {
  return { ...tableQuery }
}

async function reloadRequirements(query: RequirementListQuery = currentQuery()) {
  const result = await loadRequirements(props.workspaceId, query)
  if (result) requirementsResponse.value = result
  return result
}

async function openRequirement(requirement: RequirementSummary) {
  await openRequirementById(requirement.id)
}

async function openRequirementById(requirementId: string) {
  await router.push({
    name: 'workspaceAssetsRequirementDetail',
    params: {
      wsId: props.workspaceId,
      requirementId,
    },
  })
}

async function handleQueryChange(query: RequirementListQuery) {
  Object.assign(tableQuery, {
    q: undefined,
    status: undefined,
    priority: undefined,
    source_kind: undefined,
    parent_id: undefined,
    sort_by: 'updated_at',
    sort_order: 'desc',
    page: 1,
    page_size: 20,
  }, query)
  await reloadRequirements()
  const nextQuery = { ...route.query }
  for (const key of ['q', 'status', 'priority', 'source_kind', 'sort_by', 'sort_order', 'page', 'page_size', 'parentId']) {
    delete nextQuery[key]
  }
  if (tableQuery.q) nextQuery.q = String(tableQuery.q)
  if (tableQuery.status) nextQuery.status = String(tableQuery.status)
  if (tableQuery.priority) nextQuery.priority = String(tableQuery.priority)
  if (tableQuery.source_kind) nextQuery.source_kind = String(tableQuery.source_kind)
  if (tableQuery.parent_id) nextQuery.parentId = String(tableQuery.parent_id)
  if (tableQuery.sort_by && tableQuery.sort_by !== 'updated_at') nextQuery.sort_by = tableQuery.sort_by
  if (tableQuery.sort_order && tableQuery.sort_order !== 'desc') nextQuery.sort_order = tableQuery.sort_order
  if (tableQuery.page && tableQuery.page > 1) nextQuery.page = String(tableQuery.page)
  if (tableQuery.page_size && tableQuery.page_size !== 20) nextQuery.page_size = String(tableQuery.page_size)
  await router.replace({ query: nextQuery })
}

function openCreate() {
  childParent.value = null
  // 重新打开新建弹窗时回到初始步骤；进行中的预览作业留在浮窗继续跑
  createPreviewJobId.value = ''
  createOpen.value = true
}

function openCreateChild(parent: RequirementSummary) {
  childParent.value = parent
  editingRequirement.value = null
  editorOpen.value = true
}

function openEdit(requirement: RequirementSummary) {
  childParent.value = null
  editingRequirement.value = requirement
  editorOpen.value = true
}

async function refreshAfterMutation(nextRequirementId?: string | null) {
  await reloadRequirements()
  emit('refresh')
  if (nextRequirementId) {
    await openRequirementById(nextRequirementId)
  }
}

async function submitEditor(payload: RequirementMutationPayload) {
  const result = editingRequirement.value
    ? await updateRequirement(props.workspaceId, editingRequirement.value.id, payload)
    : await createRequirement(props.workspaceId, {
      ...payload,
      parent_requirement_id: childParent.value?.id || payload.parent_requirement_id || null,
    })
  if (result) {
    editorOpen.value = false
    editingRequirement.value = null
    childParent.value = null
    await refreshAfterMutation(result.requirement.id)
  }
}

async function previewImport(payload: Parameters<typeof createRequirementImportPreviewJob>[1]) {
  // 导入预览每次都是新内容，总是发起新作业（进行中的旧作业继续后台执行）
  try {
    const job = await createRequirementImportPreviewJob(props.workspaceId, payload)
    if (!job) return
    provisioningStore.trackRequirementPreviewJob({
      jobId: job.job_id,
      workspaceId: job.workspace_id || props.workspaceId,
      kind: 'requirement_import_preview',
    })
    createPreviewJobId.value = job.job_id
  } catch (err) {
    ElMessage.error(formatApiError(
      err,
      t('workspace_assets.requirements.preview_progress.create_failed'),
      t,
    ))
  }
}

/** 弹窗点「缩小」：作业收起到右下角浮窗（卡片才出现），关闭弹窗 */
function minimizeCreatePreview() {
  if (createPreviewJobId.value) provisioningStore.minimizePreviewJob(createPreviewJobId.value)
  createOpen.value = false
  createPreviewJobId.value = ''
}

async function confirmImport(payload: RequirementImportConfirmPayload) {
  const previewBatch = createBatch.value
  if (!previewBatch) return
  const batch = await confirmRequirementImport(props.workspaceId, previewBatch.id, payload)
  if (!batch) return
  createOpen.value = false
  if (createPreviewJobId.value) provisioningStore.dismiss(createPreviewJobId.value)
  createPreviewJobId.value = ''
  await reloadRequirements()
  emit('refresh')
  const root = requirementItems.value.find((item) => item.import_batch_id === batch.id && !item.parent_requirement_id)
  const directCreated = batch.items.find((item) => item.requirement_id)
  if (root) {
    await openRequirement(root)
  } else if (directCreated?.requirement_id) {
    await openRequirementById(directCreated.requirement_id)
  }
}

async function submitCreatedRequirement(payload: RequirementMutationPayload) {
  const result = await createRequirement(props.workspaceId, payload)
  if (result) {
    createOpen.value = false
    await refreshAfterMutation(result.requirement.id)
  }
}

async function directImport(payload: Parameters<typeof directImportRequirement>[1]) {
  const result = await directImportRequirement(props.workspaceId, payload)
  if (result) {
    createOpen.value = false
    await refreshAfterMutation(result.requirement.id)
  }
}

// ── 拆分入口：二次确认 → 发起预览作业 ──
const splitConfirmTarget = shallowRef<RequirementSummary | null>(null)

async function openSplit(requirement: RequirementSummary) {
  // 草稿优先：该需求存在未提交的拆分草稿 → 直接回拆分评审工作台续编，
  // 不弹「发起 AI 拆分」二次确认；只有草稿被取消/确认消费后才走新拆分流程。
  const draftBatch = await findRequirementSplitDraft(props.workspaceId, requirement.id)
  if (draftBatch) {
    navigateToSplitReview(requirement.id, draftBatch)
    return
  }
  // 拆分会调用 AI CLI（分钟级开销），先弹二次确认（与全局确认弹窗同款样式）
  splitConfirmTarget.value = requirement
}

function cancelSplitRequest() {
  splitConfirmTarget.value = null
}

async function startSplitPreview(requirement: RequirementSummary) {
  splitRequirementId.value = requirement.id
  // 同一需求已有进行中的预览（store 内）：直接回绑弹窗，不重复发起作业
  const active = provisioningStore.findActivePreviewJob(requirement.id, 'requirement_split_preview')
  if (active) {
    splitDialogOpen.value = true
    return
  }
  // 已完成但未查看的结果：直接跳转至独立拆分评审工作台
  const finished = provisioningStore.findLatestPreviewResult(requirement.id, 'requirement_split_preview')
  if (finished && finished.batch) {
    navigateToSplitReview(requirement.id, finished.batch)
    return
  }
  // 服务端兜底：store 无记录（刷新/卡片已被清理）但后端仍有该需求的进行中
  // 作业时回绑，避免重复发起新 CLI 排在旧作业后面一直 PENDING
  try {
    const activeJobs = await listActiveRequirementPreviewJobs()
    const serverActive = activeJobs.find((job) => (
      String(job.job_kind || '').toUpperCase() === 'REQUIREMENT_SPLIT_PREVIEW'
      && job.requirement_id === requirement.id
      && (!job.workspace_id || job.workspace_id === props.workspaceId)
    ))
    if (serverActive) {
      provisioningStore.trackRequirementPreviewJob({
        jobId: serverActive.job_id,
        workspaceId: serverActive.workspace_id || props.workspaceId,
        kind: 'requirement_split_preview',
        requirementId: requirement.id,
        requirementTitle: serverActive.requirement_title || requirement.title,
      })
      splitDialogOpen.value = true
      return
    }
  } catch {
    // 服务端查询失败不阻断主流程：退回「发起新作业」路径
  }
  try {
    const job = await createRequirementSplitPreviewJob(props.workspaceId, requirement.id)
    if (!job) return
    provisioningStore.trackRequirementPreviewJob({
      jobId: job.job_id,
      workspaceId: job.workspace_id || props.workspaceId,
      kind: 'requirement_split_preview',
      requirementId: requirement.id,
      requirementTitle: requirement.title,
    })
    splitDialogOpen.value = true
  } catch (err) {
    ElMessage.error(formatApiError(
      err,
      t('workspace_assets.requirements.preview_progress.create_failed'),
      t,
    ))
  }
}

async function confirmSplitRequest() {
  const requirement = splitConfirmTarget.value
  splitConfirmTarget.value = null
  if (!requirement) return
  await startSplitPreview(requirement)
}

/** 弹窗点「缩小」：作业收起到右下角浮窗（卡片才出现），关闭弹窗 */
function minimizeSplitPreview() {
  const job = splitTrackedJob.value
  if (job) provisioningStore.minimizePreviewJob(job.jobId)
  splitDialogOpen.value = false
  splitRequirementId.value = ''
}

async function confirmSplit(payload: RequirementImportConfirmPayload) {
  const batch = splitBatch.value
  if (!batch || !splitRequirementId.value) return
  const splitPayload: RequirementSplitPayload = {
    batch_id: batch.id,
    items: payload.items,
    change_reason: payload.change_reason,
  }
  const confirmed = await confirmRequirementSplit(props.workspaceId, splitRequirementId.value, splitPayload)
  if (confirmed) {
    const parentId = splitRequirementId.value
    discardSplitPreview()
    await refreshAfterMutation(parentId)
  }
}

function ignorePreview() {
  // 丢弃导入预览：清理浮窗作业并回到导入步骤
  const job = provisioningStore.getTrackedJob(createPreviewJobId.value)
  if (job) provisioningStore.dismiss(job.jobId)
  createPreviewJobId.value = ''
}

function clearCreatePreviewJob() {
  ignorePreview()
}

async function cancelRunningPreview(jobId: string) {
  const ok = await provisioningStore.cancelPreviewJob(jobId)
  if (!ok) {
    ElMessage.error(t('provisioning.preview_cancel_failed'))
  }
  return ok
}

function closeCreateDialog() {
  // 关闭对话框 = 取消后台预览（「缩小」才是转入后台继续执行）
  const job = provisioningStore.getTrackedJob(createPreviewJobId.value)
  createOpen.value = false
  createPreviewJobId.value = ''
  if (job && !job.terminal) {
    // 取消请求受理后作业保留在 store（cancelRequested），轮询到 CANCELLED 自动清理
    void cancelRunningPreview(job.jobId)
  }
}

function discardSplitPreview() {
  const job = splitTrackedJob.value
  splitDialogOpen.value = false
  splitRequirementId.value = ''
  if (job) provisioningStore.dismiss(job.jobId)
}

/** 拆分进度弹窗关闭中（等待后端取消受理），防重复触发 */
const closingSplitDialog = shallowRef(false)

async function closeSplitDialog() {
  if (closingSplitDialog.value) return
  const job = splitTrackedJob.value
  if (!job || job.terminal) {
    splitDialogOpen.value = false
    splitRequirementId.value = ''
    return
  }
  // 关闭 = 取消后台 CLI：等待后端受理后再关弹窗；受理失败则保持弹窗打开
  // （作业仍在运行，用户可重试关闭或点「缩小」转入后台），绝不静默泄漏 CLI。
  closingSplitDialog.value = true
  const ok = await provisioningStore.cancelPreviewJob(job.jobId)
  closingSplitDialog.value = false
  if (!ok) {
    ElMessage.error(t('provisioning.preview_cancel_failed'))
    return
  }
  splitDialogOpen.value = false
  splitRequirementId.value = ''
}

// 浮窗「查看预览」深链（导入预览没有详情页，回到列表打开 create 弹窗）
watch(
  () => route.query.previewJob,
  async (previewJobId) => {
    if (typeof previewJobId !== 'string' || !previewJobId || !props.workspaceId) return
    const jobId = previewJobId
    const nextQuery = { ...route.query }
    delete nextQuery.previewJob
    await router.replace({ query: nextQuery })
    let job = provisioningStore.getTrackedJob(jobId)
    if (!job) {
      try {
        const fetched = await fetchRequirementPreviewJob(props.workspaceId, jobId)
        job = provisioningStore.ingestPreviewJobPayload(fetched)
      } catch {
        return
      }
    }
    if (!job || job.kind === 'provision') return
    provisioningStore.markPreviewJobViewed(jobId)
    if (job.kind === 'requirement_split_preview' && job.status === 'SUCCESS' && job.batch) {
      navigateToSplitReview(job.requirementId || '', job.batch)
      return
    }
    if (job.kind === 'requirement_split_preview') {
      splitRequirementId.value = job.requirementId || ''
      splitDialogOpen.value = true
      return
    }
    createPreviewJobId.value = jobId
    createOpen.value = true
  },
  { immediate: true },
)

watch(
  () => props.workspaceId,
  async (workspaceId) => {
    if (!workspaceId) return
    await reloadRequirements()
    if (requestedRequirementId.value) {
      await openRequirementById(requestedRequirementId.value)
    }
  },
  { immediate: true },
)

watch(
  requestedRequirementId,
  async (requirementId) => {
    if (!requirementId) return
    const nextQuery = { ...route.query }
    delete nextQuery.requirementId
    await router.replace({
      name: 'workspaceAssetsRequirementDetail',
      params: {
        wsId: props.workspaceId,
        requirementId,
      },
      query: nextQuery,
    })
  },
)
</script>

<template>
  <section class="requirements-workbench">
    <p v-if="error" class="error-note">{{ error }}</p>

    <RequirementTableWorkbench
      :items="requirementItems"
      :total="activeResponse.total"
      :page="activeResponse.page"
      :page-size="activeResponse.page_size"
      :loading="props.loading || actionLoading"
      @query-change="handleQueryChange"
      @open="openRequirement"
      @create="openCreate"
      @create-child="openCreateChild"
      @edit="openEdit"
      @split="openSplit"
    />

    <RequirementEditDrawer
      :open="editorOpen"
      :requirement="editingRequirement"
      :loading="actionLoading"
      @close="editorOpen = false"
      @submit="submitEditor"
    />

    <RequirementImportDialog
      :open="createOpen"
      mode="create"
      :batch="createBatch"
      :preview-job="createPreviewJob"
      :loading="actionLoading"
      @close="closeCreateDialog"
      @minimize="minimizeCreatePreview"
      @manual="submitCreatedRequirement"
      @direct="directImport"
      @preview="previewImport"
      @confirm="confirmImport"
      @discard-preview="ignorePreview"
      @clear-preview-job="clearCreatePreviewJob"
    />

    <RequirementImportDialog
      :open="splitDialogOpen && !splitBatch"
      mode="split"
      :batch="null"
      :preview-job="splitPreviewJob"
      :loading="actionLoading"
      @close="closeSplitDialog"
      @minimize="minimizeSplitPreview"
      @discard-preview="discardSplitPreview"
      @confirm="confirmSplit"
      @clear-preview-job="discardSplitPreview"
    />

    <!-- 拆分二次确认：与全局确认弹窗同款样式（ConfirmActionModal） -->
    <ConfirmActionModal
      :show="Boolean(splitConfirmTarget)"
      :title="t('workspace_assets.requirements.split_confirm.title')"
      :message="t('workspace_assets.requirements.split_confirm.message', { name: splitConfirmTarget?.title || '' })"
      :cancel-text="t('common.cancel')"
      :confirm-text="t('workspace_assets.requirements.split_confirm.confirm_text')"
      tone="primary"
      @cancel="cancelSplitRequest"
      @confirm="confirmSplitRequest"
    />
  </section>
</template>

<style scoped>
.requirements-workbench {
  display: flex;
  flex-direction: column;
  gap: 18px;
  animation: slide-up 0.4s ease-out;
}

@keyframes slide-up {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.error-note {
  margin: 0;
  padding: 1rem 1.5rem;
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 12px;
  background: #fef2f2;
  color: #dc2626;
  font-size: 0.875rem;
  font-weight: 600;
}
</style>
