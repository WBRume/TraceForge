import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { useProvisioningStore, type ProvisionJobView } from '@/stores/provisioning'
import type { RequirementImportBatch, RequirementImportConfirmPayload, RequirementMutationPayload, RequirementPreviewJob } from '@/types/workspaceAssets'
import type { RequirementDirectImportPayload, RequirementPreviewPayload } from '@/components/workspace-assets/requirements/requirementCreateTypes'
import { formatApiError } from '@/utils/error'
import { useWorkspaceAssets } from './useWorkspaceAssets'

export function trackedJobToPreviewJob(job: ProvisionJobView | null): RequirementPreviewJob | null {
  if (!job) return null
  return {
    job_id: job.jobId,
    domain_milestones: job.domain_milestones,
    workspace_id: job.workspaceId,
    status: job.status,
    progress: job.progress,
    message: job.message || null,
    error: job.errorMessage || null,
    batch: job.batch,
    cancel_requested: job.cancelRequested,
  }
}

type CreatedRequirement = { requirementId: string; batch?: never } | { batch: RequirementImportBatch; requirementId?: never }

export function useRequirementAssetCreation(
  workspaceId: () => string,
  onCreated: (result: CreatedRequirement) => void | Promise<void>,
) {
  const { t } = useI18n()
  const store = useProvisioningStore()
  const { loading, error, clearError, createRequirement, directImportRequirement,
    createRequirementImportPreviewJob, confirmRequirementImport } = useWorkspaceAssets()
  const open = shallowRef(false)
  const jobId = shallowRef('')
  const job = computed(() => store.getTrackedJob(jobId.value))
  const preview = computed(() => trackedJobToPreviewJob(job.value))
  const batch = computed(() => job.value?.status === 'SUCCESS' ? job.value.batch : null)

  function show(existingJobId = '') {
    jobId.value = existingJobId
    clearError()
    open.value = true
  }

  function discard() {
    if (jobId.value) store.dismiss(jobId.value)
    jobId.value = ''
  }

  function minimize() {
    if (jobId.value) store.minimizePreviewJob(jobId.value)
    open.value = false
    jobId.value = ''
  }

  async function close() {
    const running = job.value
    open.value = false
    jobId.value = ''
    if (running && !running.terminal && !await store.cancelPreviewJob(running.jobId)) {
      ElMessage.error(t('provisioning.preview_cancel_failed'))
    }
  }

  async function requestPreview(payload: RequirementPreviewPayload) {
    const wsId = workspaceId()
    try {
      const response = await createRequirementImportPreviewJob(wsId, payload)
      if (!response) return
      store.trackRequirementPreviewJob({
        jobId: response.job_id,
        workspaceId: response.workspace_id || wsId,
        kind: 'requirement_import_preview',
      })
      jobId.value = response.job_id
    } catch (cause) {
      ElMessage.error(formatApiError(cause, t('workspace_assets.requirements.preview_progress.create_failed'), t))
    }
  }

  async function confirm(payload: RequirementImportConfirmPayload) {
    if (!batch.value) return
    const result = await confirmRequirementImport(workspaceId(), batch.value.id, payload)
    if (!result) return
    discard()
    open.value = false
    await onCreated({ batch: result })
  }

  async function manual(payload: RequirementMutationPayload) {
    const result = await createRequirement(workspaceId(), payload)
    if (!result) return
    open.value = false
    await onCreated({ requirementId: result.requirement.id })
  }

  async function direct(payload: RequirementDirectImportPayload) {
    const result = await directImportRequirement(workspaceId(), payload)
    if (!result) return
    open.value = false
    await onCreated({ requirementId: result.requirement.id })
  }

  return { open, loading, error, preview, batch, show, close, minimize, discard, requestPreview, confirm, manual, direct }
}
