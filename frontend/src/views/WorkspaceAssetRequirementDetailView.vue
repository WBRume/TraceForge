<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from 'lucide-vue-next'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import RequirementDetailContent from '@/components/workspace-assets/requirements/RequirementDetailContent.vue'
import RequirementEditDrawer from '@/components/workspace-assets/requirements/RequirementEditDrawer.vue'
import RequirementImportDialog from '@/components/workspace-assets/requirements/RequirementImportDialog.vue'
import { useWorkspaceAssets } from '@/composables/useWorkspaceAssets'
import { useProvisioningStore, type ProvisionJobView } from '@/stores/provisioning'
import { formatApiError } from '@/utils/error'
import type {
  RequirementDetail,
  RequirementImportBatch,
  RequirementImportConfirmPayload,
  RequirementMutationPayload,
  RequirementPreviewJob,
  RequirementSplitPayload,
  RequirementSummary,
  RequirementTaskLinkPayload,
} from '@/types/workspaceAssets'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const {
  loading,
  error,
  tasks,
  loadTasks,
  loadRequirementDetail,
  createRequirement,
  updateRequirement,
  linkRequirementTask,
  unlinkRequirementTask,
  createRequirementSplitPreviewJob,
  fetchRequirementPreviewJob,
  listActiveRequirementPreviewJobs,
  confirmRequirementSplit,
  findRequirementSplitDraft,
} = useWorkspaceAssets()
const provisioningStore = useProvisioningStore()

const wsId = computed(() => String(route.params.wsId || ''))
const requirementId = computed(() => String(route.params.requirementId || ''))

const backLabelKey = computed(() =>
  route.query.from === 'task'
    ? 'workspace_assets.requirements.actions.back_to_task'
    : 'workspace_assets.requirements.actions.back_to_list',
)

function goBack() {
  // 从 Task 上下文进入（?from=task）时回到来源 Task 页；其余一律显式回列表页。
  // 绝不能无脑 router.back()：详情可能由拆分评审页 push 而来，back() 会落回编辑页。
  if (route.query.from === 'task' && window.history.length > 1) {
    router.back()
    return
  }
  router.push({ name: 'workspaceAssetsRequirements', params: { wsId: wsId.value } })
}
const detail = shallowRef<RequirementDetail | null>(null)
const editorOpen = shallowRef(false)
const editingRequirement = shallowRef<RequirementSummary | null>(null)
const childParent = shallowRef<RequirementSummary | null>(null)
const splitDialogOpen = shallowRef(false)
const splitRequirementId = shallowRef('')
let detailLoadSeq = 0

const currentRequirement = computed(() => detail.value?.requirement || null)
const taskItems = computed(() => tasks.value?.items || [])

async function reloadDetail() {
  if (!wsId.value || !requirementId.value) {
    detail.value = null
    return null
  }
  const nextDetail = await loadRequirementDetail(wsId.value, requirementId.value)
  detail.value = nextDetail
  return nextDetail
}

async function openRequirementDetail(nextRequirementId: string) {
  await router.push({
    name: 'workspaceAssetsRequirementDetail',
    params: {
      wsId: wsId.value,
      requirementId: nextRequirementId,
    },
  })
}

function openEdit(requirement: RequirementSummary) {
  childParent.value = null
  editingRequirement.value = requirement
  editorOpen.value = true
}

function openCreateChild(parent: RequirementSummary) {
  childParent.value = parent
  editingRequirement.value = null
  editorOpen.value = true
}

async function submitEditor(payload: RequirementMutationPayload) {
  const result = editingRequirement.value
    ? await updateRequirement(wsId.value, editingRequirement.value.id, payload)
    : await createRequirement(wsId.value, {
      ...payload,
      parent_requirement_id: childParent.value?.id || payload.parent_requirement_id || null,
    })

  if (!result) return
  editorOpen.value = false
  editingRequirement.value = null
  childParent.value = null
  detail.value = result
  if (result.requirement.id !== requirementId.value) {
    await openRequirementDetail(result.requirement.id)
  }
}

// 拆分预览作业绑定：优先非终态（进行中），否则最近一条（SUCCESS 带批次可确认）
const splitTrackedJob = computed<ProvisionJobView | null>(() => {
  const reqId = splitRequirementId.value
  if (!reqId) return null
  const matched = provisioningStore.jobList.filter(
    (job) => job.kind === 'requirement_split_preview' && job.requirementId === reqId,
  )
  return matched.find((job) => !job.terminal) || matched[matched.length - 1] || null
})

const splitPreviewJob = computed<RequirementPreviewJob | null>(() => {
  const job = splitTrackedJob.value
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
})

const splitBatch = computed<RequirementImportBatch | null>(() => (
  splitTrackedJob.value?.status === 'SUCCESS' ? splitTrackedJob.value.batch : null
))

function navigateToSplitReview(reqId: string, batch: RequirementImportBatch) {
  splitDialogOpen.value = false
  splitRequirementId.value = ''
  void router.push({
    name: 'workspaceAssetRequirementSplitReview',
    params: {
      wsId: wsId.value,
      requirementId: reqId,
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
      navigateToSplitReview(splitRequirementId.value || requirementId.value, job.batch)
    }
  },
)

// ── 拆分入口：二次确认 → 发起预览作业 ──
const splitConfirmTarget = shallowRef<RequirementSummary | null>(null)

async function openSplit(requirement: RequirementSummary) {
  // 草稿优先：该需求存在未提交的拆分草稿 → 直接回拆分评审工作台续编，
  // 不弹「发起 AI 拆分」二次确认；只有草稿被取消/确认消费后才走新拆分流程。
  const draftBatch = await findRequirementSplitDraft(wsId.value, requirement.id)
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
      && (!job.workspace_id || job.workspace_id === wsId.value)
    ))
    if (serverActive) {
      provisioningStore.trackRequirementPreviewJob({
        jobId: serverActive.job_id,
        workspaceId: serverActive.workspace_id || wsId.value,
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
    const job = await createRequirementSplitPreviewJob(wsId.value, requirement.id)
    if (!job) return
    provisioningStore.trackRequirementPreviewJob({
      jobId: job.job_id,
      workspaceId: job.workspace_id || wsId.value,
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
  if (!splitBatch.value || !splitRequirementId.value) return
  const splitPayload: RequirementSplitPayload = {
    batch_id: splitBatch.value.id,
    items: payload.items,
    change_reason: payload.change_reason,
  }
  const batch = await confirmRequirementSplit(wsId.value, splitRequirementId.value, splitPayload)
  if (!batch) return
  discardSplitPreview()
  await reloadDetail()
}

/** 丢弃/确认后清理：关弹窗 + 移除浮窗作业卡片 */
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
  // 关闭 = 取消后台 CLI（「缩小」才是转入后台继续执行）：等待后端受理后再关
  // 弹窗；受理失败则保持弹窗打开（作业仍在运行，可重试或缩小），绝不静默泄漏。
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

// 浮窗「查看预览」深链：?previewJob=<jobId> → 若已成功直接跳路由，否则打开进度弹窗
watch(
  () => route.query.previewJob,
  async (previewJobId) => {
    if (typeof previewJobId !== 'string' || !previewJobId || !wsId.value) return
    const jobId = previewJobId
    const nextQuery = { ...route.query }
    delete nextQuery.previewJob
    await router.replace({ query: nextQuery })
    let job = provisioningStore.getTrackedJob(jobId)
    if (!job) {
      try {
        const fetched = await fetchRequirementPreviewJob(wsId.value, jobId)
        job = provisioningStore.ingestPreviewJobPayload(fetched)
      } catch {
        return
      }
    }
    if (!job) return
    provisioningStore.markPreviewJobViewed(jobId)
    if (job.kind === 'requirement_split_preview' && job.status === 'SUCCESS' && job.batch) {
      navigateToSplitReview(job.requirementId || requirementId.value, job.batch)
      return
    }
    splitRequirementId.value = job.requirementId || requirementId.value
    splitDialogOpen.value = true
  },
  { immediate: true },
)

async function linkTask(payload: { taskId: string; relationType: 'RELATES_TO' | 'COVERS'; reason?: string | null }) {
  if (!currentRequirement.value) return
  const request: RequirementTaskLinkPayload = {
    task_id: payload.taskId,
    relation_type: payload.relationType,
    change_reason: payload.reason,
  }
  const result = await linkRequirementTask(wsId.value, currentRequirement.value.id, request)
  if (result) detail.value = result
}

async function unlinkTask(taskId: string) {
  if (!currentRequirement.value) return
  const result = await unlinkRequirementTask(wsId.value, currentRequirement.value.id, taskId)
  if (result) detail.value = result
}

watch(
  [wsId, requirementId],
  async ([currentWsId, currentRequirementId]) => {
    const seq = ++detailLoadSeq
    detail.value = null
    if (!currentWsId || !currentRequirementId) return
    const [nextDetail] = await Promise.all([
      loadRequirementDetail(currentWsId, currentRequirementId),
      loadTasks(currentWsId),
    ])
    if (seq !== detailLoadSeq) return
    detail.value = nextDetail
  },
  { immediate: true },
)
</script>

<template>
  <div class="requirement-detail-view">
    <button class="back-link" type="button" @click="goBack">
      <ArrowLeft class="back-icon" />
      <span>{{ t(backLabelKey) }}</span>
    </button>

    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      :title="error"
    />

    <main v-loading="loading" class="detail-shell">
      <RequirementDetailContent
        :workspace-id="wsId"
        :requirement="currentRequirement"
        :detail="detail"
        :tasks="taskItems"
        :loading="loading"
        @edit="openEdit"
        @split="openSplit"
        @open-child="openRequirementDetail($event.id)"
        @create-child="openCreateChild"
        @link="linkTask"
        @unlink="unlinkTask"
      />
    </main>

    <RequirementEditDrawer
      :open="editorOpen"
      :requirement="editingRequirement"
      :loading="loading"
      @close="editorOpen = false"
      @submit="submitEditor"
    />

    <RequirementImportDialog
      :open="splitDialogOpen && !splitBatch"
      mode="split"
      :batch="null"
      :preview-job="splitPreviewJob"
      :loading="loading"
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
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');

.requirement-detail-view {
  min-height: 100%;
  padding: 30px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  background-color: #ffffff;
  background-image:
    radial-gradient(circle at 0% 0%, #eff6ff 0%, transparent 40%),
    radial-gradient(circle at 100% 100%, #f0f9ff 0%, transparent 40%);
  color: #0f172a;
  font-family: 'Open Sans', var(--font-body);
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  min-height: 38px;
  padding: 0 16px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(8px);
  color: #64748b;
  font-size: 0.875rem;
  font-weight: 600;
  text-decoration: none;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.back-link:hover {
  color: #0ea5e9;
  border-color: #0ea5e966;
  background: white;
  transform: translateX(-2px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.1);
}

.back-icon {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
}

.detail-shell {
  min-width: 0;
}

@media (max-width: 720px) {
  .requirement-detail-view {
    padding: 14px;
  }
}
</style>
