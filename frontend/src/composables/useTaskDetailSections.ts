import { reactive, shallowRef } from 'vue'
import api from '@/utils/api'
import type {
  Clarification,
  Decision,
  DecisionLight,
  Evidence,
  EvidenceLight,
  HumanDeltaLight,
  HumanReview,
  TaskDetailSummaryResponse,
  TaskFinalSummary,
  TaskFileDiffResponse,
  TaskFileItemLight,
  TaskProcessAuditLog,
  TaskProcessAuditLogLight,
  TaskWorkbenchSectionKey,
  WorkbenchDelta,
} from '@/types/workspaceAssets'

type SectionDataMap = {
  taskFile: TaskFileItemLight[]
  finalWorkflow: null
  humanDelta: HumanDeltaLight[]
  evidence: EvidenceLight[]
  decisions: DecisionLight[]
  processAudit: TaskProcessAuditLogLight[]
}

type SectionState<T> = {
  data: T | null
  loaded: boolean
  loading: boolean
  error: string | null
  total: number
  page: number
  pageSize: number
}

type SectionStates = {
  [K in TaskWorkbenchSectionKey]: SectionState<SectionDataMap[K]>
}

function createSectionState<T>(): SectionState<T> {
  return {
    data: null,
    loaded: false,
    loading: false,
    error: null,
    total: 0,
    page: 1,
    pageSize: 10,
  }
}

const sectionEndpointMap: Record<TaskWorkbenchSectionKey, string> = {
  taskFile: 'files',
  finalWorkflow: 'final-workflow',
  humanDelta: 'human-deltas',
  evidence: 'evidence',
  decisions: 'decisions',
  processAudit: 'process-audit',
}

export function useTaskDetailSections() {
  const summaryLoading = shallowRef(false)
  const summaryError = shallowRef<string | null>(null)
  const summary = shallowRef<TaskDetailSummaryResponse | null>(null)

  const sections = reactive<SectionStates>({
    taskFile: createSectionState<TaskFileItemLight[]>(),
    finalWorkflow: createSectionState<null>(),
    humanDelta: createSectionState<HumanDeltaLight[]>(),
    evidence: createSectionState<EvidenceLight[]>(),
    decisions: createSectionState<DecisionLight[]>(),
    processAudit: createSectionState<TaskProcessAuditLogLight[]>(),
  })

  async function loadSummary(workspaceId: string, taskId: string): Promise<TaskDetailSummaryResponse | null> {
    summaryLoading.value = true
    summaryError.value = null
    try {
      const response = await api.get<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/summary`,
      )
      summary.value = response.data
      return response.data
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load task summary'
      summaryError.value = message
      return null
    } finally {
      summaryLoading.value = false
    }
  }

  async function refreshSummary(workspaceId: string, taskId: string): Promise<TaskDetailSummaryResponse | null> {
    return loadSummary(workspaceId, taskId)
  }

  async function loadSection<K extends TaskWorkbenchSectionKey>(
    workspaceId: string,
    taskId: string,
    sectionKey: K,
    options?: { force?: boolean; page?: number; pageSize?: number },
  ): Promise<SectionDataMap[K] | null> {
    const state = sections[sectionKey]
    if (state.loaded && !options?.force) {
      return state.data as SectionDataMap[K]
    }
    if (state.loading) {
      return state.data as SectionDataMap[K]
    }

    state.loading = true
    state.error = null
    if (options?.page) state.page = options.page
    if (options?.pageSize) state.pageSize = options.pageSize

    const endpoint = sectionEndpointMap[sectionKey]
    if (sectionKey === 'finalWorkflow') {
      state.data = null
      state.loaded = true
      state.total = 0
      state.loading = false
      return state.data as SectionDataMap[K]
    }
    const isPaginated = true

    try {
      const params: Record<string, number> = {}
      if (isPaginated) {
        params.page = state.page
        params.page_size = state.pageSize
      }

      const response = await api.get(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/${endpoint}`,
        { params },
      )
      const responseData = response.data as { items: unknown[]; total: number; page: number; page_size: number }
      state.data = responseData.items as SectionDataMap[K]
      state.total = responseData.total
      state.page = responseData.page
      state.pageSize = responseData.page_size
      state.loaded = true
      return state.data as unknown as SectionDataMap[K]
    } catch (err) {
      const message = err instanceof Error ? err.message : `Failed to load ${sectionKey}`
      state.error = message
      return null
    } finally {
      state.loading = false
    }
  }

  async function refreshSection<K extends TaskWorkbenchSectionKey>(
    workspaceId: string,
    taskId: string,
    sectionKey: K,
  ): Promise<SectionDataMap[K] | null> {
    return loadSection(workspaceId, taskId, sectionKey, { force: true })
  }

  function invalidateSection(sectionKey: TaskWorkbenchSectionKey): void {
    const state = sections[sectionKey]
    state.loaded = false
    state.data = null
  }

  function invalidateAllSections(): void {
    for (const key of Object.keys(sections) as TaskWorkbenchSectionKey[]) {
      invalidateSection(key)
    }
  }

  // Detail loaders for individual items (full data with large fields)
  async function loadFileDetail(workspaceId: string, taskId: string, fileId: string) {
    const response = await api.get(
      `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/files/${fileId}`,
    )
    return response.data
  }

  async function loadFileDiff(workspaceId: string, taskId: string, fileId: string): Promise<TaskFileDiffResponse> {
    const response = await api.get<TaskFileDiffResponse>(
      `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/files/${fileId}/diff`,
    )
    return response.data
  }

  async function loadReviewDetail(workspaceId: string, taskId: string, reviewId: string): Promise<HumanReview> {
    const response = await api.get<HumanReview>(
      `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/human-reviews/${reviewId}`,
    )
    return response.data
  }

  async function loadWorkbenchDelta(workspaceId: string, taskId: string, deltaId: string): Promise<WorkbenchDelta> {
    const response = await api.get<WorkbenchDelta>(
      `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/human-deltas/${deltaId}/workbench`,
    )
    return response.data
  }

  async function loadEvidenceDetail(workspaceId: string, taskId: string, evidenceId: string): Promise<Evidence> {
    const response = await api.get<Evidence>(
      `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/evidence/${evidenceId}`,
    )
    return response.data
  }

  async function loadDecisionDetail(workspaceId: string, taskId: string, decisionId: string): Promise<Decision> {
    const response = await api.get<Decision>(
      `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/decisions/${decisionId}`,
    )
    return response.data
  }

  async function loadClarificationDetail(workspaceId: string, taskId: string, clarificationId: string): Promise<Clarification> {
    const response = await api.get<Clarification>(
      `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/clarifications/${clarificationId}`,
    )
    return response.data
  }

  async function loadAuditLogDetail(workspaceId: string, taskId: string, logId: string): Promise<TaskProcessAuditLog> {
    const response = await api.get<TaskProcessAuditLog>(
      `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/process-audit/${logId}`,
    )
    return response.data
  }

  async function loadFinalSummary(workspaceId: string, taskId: string): Promise<TaskFinalSummary> {
    const response = await api.get<TaskFinalSummary>(
      `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/final-summary`,
    )
    return response.data
  }

  return {
    summary,
    summaryLoading,
    summaryError,
    sections,
    loadSummary,
    refreshSummary,
    loadSection,
    refreshSection,
    invalidateSection,
    invalidateAllSections,
    loadFileDetail,
    loadFileDiff,
    loadReviewDetail,
    loadWorkbenchDelta,
    loadEvidenceDetail,
    loadDecisionDetail,
    loadClarificationDetail,
    loadAuditLogDetail,
    loadFinalSummary,
  }
}
