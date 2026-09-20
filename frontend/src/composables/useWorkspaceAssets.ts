import { computed, readonly, shallowRef } from 'vue'
import api from '@/utils/api'
import type {
  RequirementDetail,
  RequirementImportBatch,
  RequirementImportConfirmPayload,
  RequirementListQuery,
  RequirementMutationPayload,
  RequirementPreviewJob,
  RequirementSplitDraft,
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
    // 不走 mutate()：AI CLI 执行是分钟级后台作业，轮询进度由右下角浮窗
    // （provisioning store）负责，绝不能让全局 loading 一直为 true。
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

  async function fetchRequirementPreviewJob(
    workspaceId: string,
    jobId: string,
  ): Promise<RequirementPreviewJob> {
    const response = await api.get<RequirementPreviewJob>(
      `/workspaces/${workspaceId}/workspace-assets/requirements/preview-jobs/${jobId}`,
    )
    return response.data
  }

  /**
   * 当前用户名下未终态（PENDING/RUNNING）的 requirement preview 作业。
   * 「拆分」入口用于服务端兜底回绑：store 里没有记录（刷新/卡片被清理）
   * 时，只要后端仍有该需求的进行中作业就复用，绝不重复发起新 CLI。
   */
  async function listActiveRequirementPreviewJobs(): Promise<RequirementPreviewJob[]> {
    const response = await api.get<RequirementPreviewJob[]>('/requirement-preview-jobs/active')
    return Array.isArray(response.data) ? response.data : []
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

  async function createRequirementSplitPreviewJob(
    workspaceId: string,
    requirementId: string,
    changeReason?: string | null,
  ): Promise<RequirementPreviewJob | null> {
    // 不走 mutate()：理由同 createRequirementImportPreviewJob。
    const response = await api.post<RequirementPreviewJob>(
      `/workspaces/${workspaceId}/workspace-assets/requirements/${requirementId}/split-preview`,
      { change_reason: changeReason || undefined },
    )
    return response.data
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

  async function loadImportBatch(
    workspaceId: string,
    batchId: string,
  ): Promise<RequirementImportBatch | null> {
    return mutate(async () => {
      const response = await api.get<RequirementImportBatch>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/import-batches/${batchId}`,
      )
      return response.data
    })
  }

  /**
   * 拆分评审页草稿自动保存。不接 mutate()：自动保存是击键级防抖的高频请求，
   * 不应翻转页面级 loading/error 状态；失败只影响草稿指示灯，不打断编辑。
   */
  async function saveRequirementSplitDraft(
    workspaceId: string,
    batchId: string,
    payload: RequirementSplitDraft,
  ): Promise<boolean> {
    try {
      await api.put(
        `/workspaces/${workspaceId}/workspace-assets/requirements/import-batches/${batchId}/draft`,
        payload,
      )
      return true
    } catch {
      return false
    }
  }

  /** 删除拆分评审页草稿（「取消」= 删除草稿；失败返回 false 由调用方提示重试）。 */
  async function clearRequirementSplitDraft(
    workspaceId: string,
    batchId: string,
  ): Promise<boolean> {
    try {
      await api.delete(
        `/workspaces/${workspaceId}/workspace-assets/requirements/import-batches/${batchId}/draft`,
      )
      return true
    } catch {
      return false
    }
  }

  /**
   * 「拆分」入口草稿回绑：该需求最近一个带未提交草稿的 PREVIEW 拆分批次。
   * 无草稿（404）或查询失败都返回 null，入口退回原有作业绑定/新发起流程。
   */
  async function findRequirementSplitDraft(
    workspaceId: string,
    requirementId: string,
  ): Promise<RequirementImportBatch | null> {
    try {
      const response = await api.get<RequirementImportBatch>(
        `/workspaces/${workspaceId}/workspace-assets/requirements/${requirementId}/split-draft`,
      )
      return response.data
    } catch {
      return null
    }
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
    createRequirementImportPreviewJob,
    fetchRequirementPreviewJob,
    listActiveRequirementPreviewJobs,
    directImportRequirement,
    confirmRequirementImport,
    createRequirementSplitPreviewJob,
    confirmRequirementSplit,
    loadImportBatch,
    saveRequirementSplitDraft,
    clearRequirementSplitDraft,
    findRequirementSplitDraft,
    loadTasks,
    loadTaskDetail,
    loadTraceability,
    loadKnowledgeAssets,
  }
}
