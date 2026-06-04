<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft } from 'lucide-vue-next'
import RequirementDetailContent from '@/components/workspace-assets/requirements/RequirementDetailContent.vue'
import RequirementEditDrawer from '@/components/workspace-assets/requirements/RequirementEditDrawer.vue'
import RequirementImportDialog from '@/components/workspace-assets/requirements/RequirementImportDialog.vue'
import { useWorkspaceAssets } from '@/composables/useWorkspaceAssets'
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
  createRequirementSplitPreview,
  confirmRequirementSplit,
} = useWorkspaceAssets()

const wsId = computed(() => String(route.params.wsId || ''))
const requirementId = computed(() => String(route.params.requirementId || ''))

const backLabelKey = computed(() =>
  route.query.from === 'task'
    ? 'workspace_assets.requirements.actions.back_to_task'
    : 'workspace_assets.requirements.actions.back_to_list',
)

function goBack() {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push({ name: 'workspaceAssetsRequirements', params: { wsId: wsId.value } })
  }
}
const detail = shallowRef<RequirementDetail | null>(null)
const editorOpen = shallowRef(false)
const editingRequirement = shallowRef<RequirementSummary | null>(null)
const childParent = shallowRef<RequirementSummary | null>(null)
const splitBatch = shallowRef<RequirementImportBatch | null>(null)
const splitPreviewJob = shallowRef<RequirementPreviewJob | null>(null)
const splitPreviewRunId = shallowRef(0)
const splitRequirement = shallowRef<RequirementSummary | null>(null)
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

async function openSplit(requirement: RequirementSummary) {
  splitPreviewRunId.value += 1
  const runId = splitPreviewRunId.value
  splitRequirement.value = requirement
  splitBatch.value = null
  splitPreviewJob.value = null
  const batch = await createRequirementSplitPreview(
    wsId.value,
    requirement.id,
    null,
    (job) => {
      if (runId === splitPreviewRunId.value) splitPreviewJob.value = job
    },
  )
  if (batch && runId === splitPreviewRunId.value) splitBatch.value = batch
}

async function confirmSplit(payload: RequirementImportConfirmPayload) {
  if (!splitBatch.value || !splitRequirement.value) return
  const splitPayload: RequirementSplitPayload = {
    batch_id: splitBatch.value.id,
    items: payload.items,
    change_reason: payload.change_reason,
  }
  const batch = await confirmRequirementSplit(wsId.value, splitRequirement.value.id, splitPayload)
  if (!batch) return
  closeSplitDialog()
  await reloadDetail()
}

function closeSplitDialog() {
  splitPreviewRunId.value += 1
  splitBatch.value = null
  splitPreviewJob.value = null
  splitRequirement.value = null
}

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
      :open="Boolean(splitBatch || splitPreviewJob)"
      mode="split"
      :batch="splitBatch"
      :preview-job="splitPreviewJob"
      :loading="loading"
      @close="closeSplitDialog"
      @preview="closeSplitDialog"
      @confirm="confirmSplit"
      @clear-preview-job="closeSplitDialog"
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
