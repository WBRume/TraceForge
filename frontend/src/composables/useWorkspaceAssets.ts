import { computed, readonly, shallowRef } from 'vue'
import api from '@/utils/api'
import type {
  RequirementDetail,
  RequirementImportBatch,
  RequirementImportConfirmPayload,
  RequirementListQuery,
  RequirementMutationPayload,
  RequirementPreviewJob,
  RequirementSplitPayload,
  RequirementTaskLinkPayload,
  TaskDetail,
  TaskListQuery,
  WorkspaceAssetConnectionStatus,
  WorkspaceAssetsKnowledge,
  WorkspaceAssetsOverview,
  WorkspaceAssetsRequirements,
  WorkspaceAssetsTasks,
  WorkspaceAssetsTraceability,
} from '@/types/workspaceAssets'

export const WORKSPACE_ASSET_TASK_DETAIL_SKELETON_ID = '__task_detail_skeleton__'

export const isWorkspaceAssetTaskDetailSkeleton = (taskId: string): boolean =>
  taskId === WORKSPACE_ASSET_TASK_DETAIL_SKELETON_ID

const emptyConnectionStatus: WorkspaceAssetConnectionStatus[] = []
const previewFinalStatuses = new Set(['SUCCESS', 'FAILED', 'CANCELLED'])
type RequirementPreviewJobUpdate = (job: RequirementPreviewJob) => void

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms))
}

export function useWorkspaceAssets() {
  const loading = shallowRef(false)
  const error = shallowRef<string | null>(null)
  const overview = shallowRef<WorkspaceAssetsOverview | null>(null)
  const requirements = shallowRef<WorkspaceAssetsRequirements | null>(null)
  const tasks = shallowRef<WorkspaceAssetsTasks | null>(null)
  const taskDetail = shallowRef<TaskDetail | null>(null)
  const traceability = shallowRef<WorkspaceAssetsTraceability | null>(null)
  const knowledgeAssets = shallowRef<WorkspaceAssetsKnowledge | null>(null)

  const connectionStatus = computed<WorkspaceAssetConnectionStatus[]>(() => (
    taskDetail.value?.connection_status
    || traceability.value?.connection_status
    || knowledgeAssets.value?.connection_status
    || tasks.value?.connection_status
    || requirements.value?.connection_status
    || overview.value?.connection_status
    || emptyConnectionStatus
  ))

  const isEmpty = computed(() => {
    if (taskDetail.value) {
      const detail = taskDetail.value
      const emptyLists = [
        detail.requirement_links,
        detail.task_files,
        detail.specs,
        detail.plans,
        detail.plan_nodes,
        detail.ai_runs,
        detail.ai_outputs,
        detail.human_reviews,
        detail.human_deltas,
        detail.evidence,
        detail.decisions,
        detail.clarifications,
        detail.process_audit_logs,
      ].every((items) => items.length === 0)
      return emptyLists && !detail.final_summary
    }
    return Boolean(
      requirements.value?.state.empty
      || tasks.value?.state.empty
      || knowledgeAssets.value?.state.empty
      || traceability.value?.views.every((view) => view.state.empty)
    )
  })

  async function request<T>(loader: () => Promise<T>, assign: (value: T) => void): Promise<T | null> {
    loading.value = true
    error.value = null
    try {
      const value = await loader()
      assign(value)
      return value
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Workspace Assets request failed'
      error.value = message
      return null
    } finally {
      loading.value = false
    }
  }

  async function mutate<T>(loader: () => Promise<T>): Promise<T | null> {
    loading.value = true
    error.value = null
    try {
      return await loader()
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Workspace Assets request failed'
      error.value = message
      return null
    } finally {
      loading.value = false
    }
  }

  async function loadOverview(workspaceId: string): Promise<WorkspaceAssetsOverview | null> {
    return request(
      async () => {
        const response = await api.get<WorkspaceAssetsOverview>(`/workspaces/${workspaceId}/workspace-assets/overview`)
        return response.data
      },
      (value) => {
        overview.value = value
      },
    )
  }

  async function loadRequirements(
    workspaceId: string,
    query?: RequirementListQuery,
  ): Promise<WorkspaceAssetsRequirements | null> {
    return request(
      async () => {
        const url = `/workspaces/${workspaceId}/workspace-assets/requirements`
        const response = query
          ? await api.get<WorkspaceAssetsRequirements>(url, { params: query })
          : await api.get<WorkspaceAssetsRequirements>(url)
        return response.data
      },
      (value) => {
        requirements.value = value
      },
    )
  }

  async function loadRequirementDetail(
    workspaceId: string,
    requirementId: string,
  ): Promise<RequirementDetail | null> {
    return mutate(async () => {
      const response = await api.get<RequirementDetail>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/${requirementId}`,
      )
      return response.data
    })
  }

  async function createRequirement(
    workspaceId: string,
    payload: RequirementMutationPayload,
  ): Promise<RequirementDetail | null> {
    return mutate(async () => {
      const response = await api.post<RequirementDetail>(
        `/workspaces/${workspaceId}/workspace-assets/requirements`,
        payload,
      )
      return response.data
    })
  }

  async function updateRequirement(
    workspaceId: string,
    requirementId: string,
    payload: RequirementMutationPayload,
  ): Promise<RequirementDetail | null> {
    return mutate(async () => {
      const response = await api.patch<RequirementDetail>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/${requirementId}`,
        payload,
      )
      return response.data
    })
  }

  async function linkRequirementTask(
    workspaceId: string,
    requirementId: string,
    payload: RequirementTaskLinkPayload,
  ): Promise<RequirementDetail | null> {
    return mutate(async () => {
      const response = await api.post<RequirementDetail>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/${requirementId}/tasks`,
        payload,
      )
      return response.data
    })
  }

  async function unlinkRequirementTask(
    workspaceId: string,
    requirementId: string,
    taskId: string,
    changeReason?: string | null,
  ): Promise<RequirementDetail | null> {
    return mutate(async () => {
      const response = await api.delete<RequirementDetail>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/${requirementId}/tasks/${taskId}`,
        { params: { change_reason: changeReason || undefined } },
      )
      return response.data
    })
  }

  async function createRequirementImportPreview(
    workspaceId: string,
    payload: {
      file?: File | null
      text?: string | null
      source_kind?: string | null
      source_uri?: string | null
      source_ref?: string | null
    },
    onJobUpdate?: RequirementPreviewJobUpdate,
  ): Promise<RequirementImportBatch | null> {
    return mutate(async () => {
      const form = new FormData()
      if (payload.file) {
        form.append('file', payload.file)
      } else if (payload.text) {
        form.append('text', payload.text)
      }
      if (payload.source_kind) form.append('source_kind', payload.source_kind)
      if (payload.source_uri) form.append('source_uri', payload.source_uri)
      if (payload.source_ref) form.append('source_ref', payload.source_ref)
      const response = await api.post<RequirementPreviewJob>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/imports`,
        form,
      )
      onJobUpdate?.(response.data)
      const job = await waitRequirementPreviewJob(workspaceId, response.data, onJobUpdate)
      if (job.status === 'FAILED' || job.status === 'CANCELLED') {
        throw new Error(job.error || job.message || 'Requirement AI preview failed')
      }
      return job.batch || null
    })
  }

  async function directImportRequirement(
    workspaceId: string,
    payload: {
      file?: File | null
      text?: string | null
      source_kind?: string | null
      source_uri?: string | null
      source_ref?: string | null
      change_reason?: string | null
    },
  ): Promise<RequirementDetail | null> {
    return mutate(async () => {
      const form = new FormData()
      if (payload.file) {
        form.append('file', payload.file)
      } else if (payload.text) {
        form.append('text', payload.text)
      }
      if (payload.source_kind) form.append('source_kind', payload.source_kind)
      if (payload.source_uri) form.append('source_uri', payload.source_uri)
      if (payload.source_ref) form.append('source_ref', payload.source_ref)
      if (payload.change_reason) form.append('change_reason', payload.change_reason)
      const response = await api.post<RequirementDetail>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/imports/direct`,
        form,
      )
      return response.data
    })
  }

  async function getRequirementPreviewJob(
    workspaceId: string,
    jobId: string,
  ): Promise<RequirementPreviewJob | null> {
    return mutate(async () => {
      return fetchRequirementPreviewJob(workspaceId, jobId)
    })
  }

  async function fetchRequirementPreviewJob(
    workspaceId: string,
    jobId: string,
  ): Promise<RequirementPreviewJob> {
    const response = await api.get<RequirementPreviewJob>(
      `/workspaces/${workspaceId}/workspace-assets/requirements/preview-jobs/${jobId}`,
    )
    return response.data
  }

  async function waitRequirementPreviewJob(
    workspaceId: string,
    initialJob: RequirementPreviewJob,
    onJobUpdate?: RequirementPreviewJobUpdate,
  ): Promise<RequirementPreviewJob> {
    let job = initialJob
    onJobUpdate?.(job)
    for (let attempt = 0; attempt < 60 && !previewFinalStatuses.has(job.status); attempt += 1) {
      await wait(1000)
      job = await fetchRequirementPreviewJob(workspaceId, job.job_id)
      onJobUpdate?.(job)
    }
    return job
  }

  async function createRequirementImportPreviewJob(
    workspaceId: string,
    payload: {
      file?: File | null
      text?: string | null
      source_kind?: string | null
      source_uri?: string | null
      source_ref?: string | null
    },
  ): Promise<RequirementPreviewJob | null> {
    return mutate(async () => {
      const form = new FormData()
      if (payload.file) {
        form.append('file', payload.file)
      } else if (payload.text) {
        form.append('text', payload.text)
      }
      if (payload.source_kind) form.append('source_kind', payload.source_kind)
      if (payload.source_uri) form.append('source_uri', payload.source_uri)
      if (payload.source_ref) form.append('source_ref', payload.source_ref)
      const response = await api.post<RequirementPreviewJob>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/imports`,
        form,
      )
      return response.data
    })
  }

  async function confirmRequirementImport(
    workspaceId: string,
    batchId: string,
    payload: RequirementImportConfirmPayload,
  ): Promise<RequirementImportBatch | null> {
    return mutate(async () => {
      const response = await api.post<RequirementImportBatch>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/imports/${batchId}/confirm`,
        payload,
      )
      return response.data
    })
  }

  async function createRequirementSplitPreview(
    workspaceId: string,
    requirementId: string,
    changeReason?: string | null,
    onJobUpdate?: RequirementPreviewJobUpdate,
  ): Promise<RequirementImportBatch | null> {
    return mutate(async () => {
      const response = await api.post<RequirementPreviewJob>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/${requirementId}/split-preview`,
        { change_reason: changeReason || undefined },
      )
      onJobUpdate?.(response.data)
      const job = await waitRequirementPreviewJob(workspaceId, response.data, onJobUpdate)
      if (job.status === 'FAILED' || job.status === 'CANCELLED') {
        throw new Error(job.error || job.message || 'Requirement split preview failed')
      }
      return job.batch || null
    })
  }

  async function createRequirementSplitPreviewJob(
    workspaceId: string,
    requirementId: string,
    changeReason?: string | null,
  ): Promise<RequirementPreviewJob | null> {
    return mutate(async () => {
      const response = await api.post<RequirementPreviewJob>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/${requirementId}/split-preview`,
        { change_reason: changeReason || undefined },
      )
      return response.data
    })
  }

  async function confirmRequirementSplit(
    workspaceId: string,
    requirementId: string,
    payload: RequirementSplitPayload,
  ): Promise<RequirementImportBatch | null> {
    return mutate(async () => {
      const response = await api.post<RequirementImportBatch>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/${requirementId}/split`,
        payload,
      )
      return response.data
    })
  }

  async function loadTasks(
    workspaceId: string,
    query?: TaskListQuery,
  ): Promise<WorkspaceAssetsTasks | null> {
    return request(
      async () => {
        const url = `/workspaces/${workspaceId}/workspace-assets/tasks`
        const response = query
          ? await api.get<WorkspaceAssetsTasks>(url, { params: query })
          : await api.get<WorkspaceAssetsTasks>(url)
        return response.data
      },
      (value) => {
        tasks.value = value
      },
    )
  }

  async function loadTaskDetail(workspaceId: string, taskId: string): Promise<TaskDetail | null> {
    if (isWorkspaceAssetTaskDetailSkeleton(taskId)) {
      taskDetail.value = null
      error.value = null
      return null
    }
    return request(
      async () => {
        const response = await api.get<TaskDetail>(`/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}`)
        return response.data
      },
      (value) => {
        taskDetail.value = value
      },
    )
  }

  async function loadTraceability(workspaceId: string): Promise<WorkspaceAssetsTraceability | null> {
    return request(
      async () => {
        const response = await api.get<WorkspaceAssetsTraceability>(
          `/workspaces/${workspaceId}/workspace-assets/traceability`,
        )
        return response.data
      },
      (value) => {
        traceability.value = value
      },
    )
  }

  async function loadKnowledgeAssets(workspaceId: string): Promise<WorkspaceAssetsKnowledge | null> {
    return request(
      async () => {
        const response = await api.get<WorkspaceAssetsKnowledge>(
          `/workspaces/${workspaceId}/workspace-assets/knowledge-assets`,
        )
        return response.data
      },
      (value) => {
        knowledgeAssets.value = value
      },
    )
  }

  return {
    loading: readonly(loading),
    error: readonly(error),
    overview: readonly(overview),
    requirements: readonly(requirements),
    tasks: readonly(tasks),
    taskDetail: readonly(taskDetail),
    traceability: readonly(traceability),
    knowledgeAssets: readonly(knowledgeAssets),
    connectionStatus,
    isEmpty,
    loadOverview,
    loadRequirements,
    loadRequirementDetail,
    createRequirement,
    updateRequirement,
    linkRequirementTask,
    unlinkRequirementTask,
    createRequirementImportPreview,
    createRequirementImportPreviewJob,
    getRequirementPreviewJob,
    waitRequirementPreviewJob,
    directImportRequirement,
    confirmRequirementImport,
    createRequirementSplitPreview,
    createRequirementSplitPreviewJob,
    confirmRequirementSplit,
    loadTasks,
    loadTaskDetail,
    loadTraceability,
    loadKnowledgeAssets,
  }
}
