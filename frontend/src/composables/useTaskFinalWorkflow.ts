import { computed, readonly, shallowRef } from 'vue'
import api from '@/utils/api'
import type {
  ClarificationMessagePayload,
  FinalWorkflowClarificationPayload,
  FinalWorkflowReviewPayload,
  ReviewTargetPreviewResponse,
  ReviewTargetRef,
  TaskFinalWorkflowResponse,
  TaskFinalSummaryPayload,
} from '@/types/workspaceAssets'

type WorkflowMutation = () => Promise<TaskFinalWorkflowResponse>

export function useTaskFinalWorkflow() {
  const workflow = shallowRef<TaskFinalWorkflowResponse | null>(null)
  const loading = shallowRef(false)
  const saving = shallowRef(false)
  const error = shallowRef<string | null>(null)
  const lockMessage = shallowRef<string | null>(null)
  const targetPreviewCache = shallowRef(new Map<string, ReviewTargetPreviewResponse>())

  const readonlyState = computed(() => Boolean(workflow.value?.readonly || workflow.value?.task.status === 'BASELINED'))
  const canWriteFinalWorkflow = computed(() => Boolean(!readonlyState.value && workflow.value?.can_write_final_workflow))
  const canResolveClarification = computed(() => Boolean(!readonlyState.value && workflow.value?.can_resolve_clarification))
  const blockingChecklist = computed(() => workflow.value?.checklist.filter((item) => item.blocking) ?? [])

  function normalizeError(err: unknown): string {
    if (err instanceof Error) return err.message
    return 'Final workflow request failed'
  }

  function recordError(err: unknown): string {
    const message = normalizeError(err)
    error.value = message
    if (message.includes('BASELINED') || message.includes('403')) {
      lockMessage.value = 'Task is baselined and read-only.'
    }
    return message
  }

  async function load(workspaceId: string, taskId: string): Promise<TaskFinalWorkflowResponse | null> {
    loading.value = true
    error.value = null
    try {
      const response = await api.get<TaskFinalWorkflowResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/final-workflow`,
      )
      workflow.value = response.data
      lockMessage.value = response.data.readonly ? 'Task is baselined and read-only.' : null
      return response.data
    } catch (err) {
      recordError(err)
      return null
    } finally {
      loading.value = false
    }
  }

  async function mutate(loader: WorkflowMutation): Promise<TaskFinalWorkflowResponse | null> {
    saving.value = true
    error.value = null
    try {
      const next = await loader()
      workflow.value = next
      lockMessage.value = next.readonly ? 'Task is baselined and read-only.' : null
      return next
    } catch (err) {
      recordError(err)
      return null
    } finally {
      saving.value = false
    }
  }

  async function createReview(workspaceId: string, taskId: string, payload: FinalWorkflowReviewPayload) {
    return mutate(async () => {
      const response = await api.post<TaskFinalWorkflowResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/final-workflow/reviews`,
        payload,
      )
      return response.data
    })
  }

  async function updateReview(
    workspaceId: string,
    taskId: string,
    reviewId: string,
    payload: FinalWorkflowReviewPayload,
  ) {
    return mutate(async () => {
      const response = await api.put<TaskFinalWorkflowResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/final-workflow/reviews/${reviewId}`,
        payload,
      )
      return response.data
    })
  }

  async function createClarification(workspaceId: string, taskId: string, payload: FinalWorkflowClarificationPayload) {
    return mutate(async () => {
      const response = await api.post<TaskFinalWorkflowResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/final-workflow/clarifications`,
        payload,
      )
      return response.data
    })
  }

  async function addClarificationMessage(
    workspaceId: string,
    taskId: string,
    clarificationId: string,
    payload: ClarificationMessagePayload,
  ) {
    return mutate(async () => {
      const response = await api.post<TaskFinalWorkflowResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/final-workflow/clarifications/${clarificationId}/messages`,
        payload,
      )
      return response.data
    })
  }

  async function generateDraft(workspaceId: string, taskId: string) {
    return mutate(async () => {
      const response = await api.post<TaskFinalWorkflowResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/final-workflow/final-summary/draft`,
        {},
      )
      return response.data
    })
  }

  async function upsertFinalSummary(workspaceId: string, taskId: string, payload: TaskFinalSummaryPayload) {
    return mutate(async () => {
      const response = await api.put<TaskFinalWorkflowResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/final-workflow/final-summary`,
        payload,
      )
      return response.data
    })
  }

  async function baseline(workspaceId: string, taskId: string) {
    return mutate(async () => {
      const response = await api.post<TaskFinalWorkflowResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/final-workflow/baseline`,
      )
      return response.data
    })
  }

  async function loadReviewTargetPreview(
    workspaceId: string,
    taskId: string,
    target: Pick<ReviewTargetRef, 'target_type' | 'target_id'>,
  ): Promise<ReviewTargetPreviewResponse> {
    const cacheKey = `${target.target_type}:${target.target_id}`
    const cached = targetPreviewCache.value.get(cacheKey)
    if (cached) return cached

    const response = await api.get<ReviewTargetPreviewResponse>(
      `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/final-workflow/review-targets/${encodeURIComponent(target.target_type)}/${encodeURIComponent(target.target_id)}/preview`,
    )
    const next = new Map(targetPreviewCache.value)
    next.set(cacheKey, response.data)
    targetPreviewCache.value = next
    return response.data
  }

  return {
    workflow,
    loading: readonly(loading),
    saving: readonly(saving),
    error: readonly(error),
    lockMessage: readonly(lockMessage),
    readonlyState,
    canWriteFinalWorkflow,
    canResolveClarification,
    blockingChecklist,
    load,
    createReview,
    updateReview,
    createClarification,
    addClarificationMessage,
    generateDraft,
    upsertFinalSummary,
    baseline,
    loadReviewTargetPreview,
  }
}
