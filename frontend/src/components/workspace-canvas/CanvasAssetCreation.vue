<script setup lang="ts">
import { defineAsyncComponent, proxyRefs, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { useCaseCenter } from '@/composables/useCaseCenter'
import { useRequirementAssetCreation } from '@/composables/useRequirementAssetCreation'
import { useWorkspaceAssets } from '@/composables/useWorkspaceAssets'
import { canvasOperationTarget, WORKSPACE_ASSET_CANVAS } from '@/router/workspaceAssetPresentation'
import { useProvisioningStore } from '@/stores/provisioning'
import { formatApiError } from '@/utils/error'
import type { TaskCreatedEvent } from '@/components/task-create/types'
import type { RequirementOption } from '@/types/taskRail'
import type { CanvasCommand, CanvasDocumentOwner } from './model'

const props = defineProps<{ workspaceId: string; documentOwners: readonly CanvasDocumentOwner[] }>()
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const jobs = useProvisioningStore()
const cases = proxyRefs(useCaseCenter({ workspaceId: () => props.workspaceId }))
const { fetchRequirementPreviewJob, loadRequirementDetail } = useWorkspaceAssets()
const RequirementImportDialog = defineAsyncComponent(() => import('@/components/workspace-assets/requirements/RequirementImportDialog.vue'))
const NewTaskModal = defineAsyncComponent(() => import('@/components/task-create/NewTaskModal.vue'))
const CaseFormDialog = defineAsyncComponent(() => import('@/components/case-center/CaseFormDialog.vue'))
const CanvasDocumentUpload = defineAsyncComponent(() => import('./CanvasDocumentUpload.vue'))
const taskOpen = shallowRef(false)
const taskRequirement = shallowRef<RequirementOption | null>(null)
const docOpen = shallowRef(false)
const documentOwner = shallowRef<CanvasDocumentOwner>()

const requirement = useRequirementAssetCreation(() => props.workspaceId, async ({ requirementId, batch }) => {
  emit('changed')
  const id = requirementId ?? batch?.items.find(item => item.requirement_id)?.requirement_id
  if (id) await router.push(canvasOperationTarget('workspaceAssetsRequirementDetail', { wsId: props.workspaceId, requirementId: id }))
})

function open(command: CanvasCommand, owner?: CanvasDocumentOwner) {
  switch (command) {
    case 'requirement': requirement.show(); break
    case 'task': taskRequirement.value = null; taskOpen.value = true; break
    case 'case': cases.openCreateForm(); break
    case 'document': documentOwner.value = owner; docOpen.value = true; break
    case 'playbooks': void router.push(canvasOperationTarget('playbooks', { wsId: props.workspaceId })); break
  }
}

async function createLinkedTask(requirementId: string) {
  const detail = await loadRequirementDetail(props.workspaceId, requirementId)
  if (!detail) return
  taskRequirement.value = detail.requirement
  taskOpen.value = true
}

function taskCreated(event: TaskCreatedEvent) {
  taskOpen.value = false
  jobs.startWatching(event)
  emit('changed')
}

async function saveCase() {
  await cases.saveForm()
  if (cases.formVisible || !cases.currentCase?.id) return
  emit('changed')
  await router.push(canvasOperationTarget('workspaceCaseDetail', { wsId: props.workspaceId, caseId: cases.currentCase.id }))
}

function documentCreated(owner: CanvasDocumentOwner, asset: string) {
  docOpen.value = false
  emit('changed')
  if (owner.kind === 'requirement') {
    void router.push(canvasOperationTarget('workspaceRequirementDocument', { wsId: props.workspaceId, documentId: asset }))
  } else {
    void router.push(canvasOperationTarget('taskSpec', { wsId: props.workspaceId, taskId: owner.id }, { asset }))
  }
}

watch(requirement.error, value => { if (value && requirement.open.value) ElMessage.error(value) })
watch(() => route.name === WORKSPACE_ASSET_CANVAS ? route.query.previewJob : null, async id => {
  if (typeof id !== 'string' || !id) return
  const query = { ...route.query }
  delete query.previewJob
  await router.replace({ query })
  let job = jobs.getTrackedJob(id)
  if (!job) {
    try { job = jobs.ingestPreviewJobPayload(await fetchRequirementPreviewJob(props.workspaceId, id)) }
    catch (error) { ElMessage.error(formatApiError(error, t('workspace_canvas.load_failed'), t)); return }
  }
  if (job?.workspaceId !== props.workspaceId) return
  if (job.kind === 'requirement_import_preview') {
    jobs.markPreviewJobViewed(id)
    requirement.show(id)
  } else if (job.kind === 'requirement_split_preview' && job.requirementId) {
    await router.push(canvasOperationTarget('workspaceAssetsRequirementDetail',
      { wsId: props.workspaceId, requirementId: job.requirementId }, { previewJob: id }))
  }
}, { immediate: true })

defineExpose({ open, createLinkedTask })
</script>

<template>
  <RequirementImportDialog v-if="requirement.open.value" open mode="create"
    :batch="requirement.batch.value ?? null" :preview-job="requirement.preview.value" :loading="requirement.loading.value"
    @manual="requirement.manual" @direct="requirement.direct" @preview="requirement.requestPreview" @confirm="requirement.confirm"
    @minimize="requirement.minimize" @close="requirement.close" @discard-preview="requirement.discard"
    @clear-preview-job="requirement.discard" />
  <Teleport to="body">
    <NewTaskModal v-if="taskOpen" show :ws-id="workspaceId" :initial-requirement="taskRequirement"
      @close="taskOpen = false" @created="taskCreated" />
  </Teleport>
  <CaseFormDialog v-if="cases.formVisible" :visible="cases.formVisible" :saving="cases.formSaving" :model="cases.formModel"
    :is-edit="false" @close="cases.closeForm" @save="saveCase" />
  <CanvasDocumentUpload v-if="docOpen" :workspace-id="workspaceId" :owners="documentOwners" :initial-owner="documentOwner"
    @close="docOpen = false" @created="documentCreated" />
</template>
