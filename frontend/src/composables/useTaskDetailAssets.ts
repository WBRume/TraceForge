import { readonly, shallowRef } from 'vue'
import api from '@/utils/api'
import type {
  ClarificationMutationPayload,
  DecisionMutationPayload,
  EvidenceMutationPayload,
  HumanDeltaMutationPayload,
  HumanDeltaSuggestionsResponse,
  HumanReviewCommentPayload,
  HumanReviewMutationPayload,
  TaskDetailSummaryResponse,
  TaskFinalSummaryPayload,
} from '@/types/workspaceAssets'

type TaskDetailMutation<T> = () => Promise<T>

export function useTaskDetailAssets() {
  const saving = shallowRef(false)
  const error = shallowRef<string | null>(null)

  async function mutate(loader: TaskDetailMutation<TaskDetailSummaryResponse>): Promise<TaskDetailSummaryResponse | null> {
    saving.value = true
    error.value = null
    try {
      return await loader()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Task Detail update failed'
      return null
    } finally {
      saving.value = false
    }
  }

  async function createHumanReview(
    workspaceId: string,
    taskId: string,
    payload: HumanReviewMutationPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.post<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/human-reviews`,
        payload,
      )
      return response.data
    })
  }

  async function updateHumanReview(
    workspaceId: string,
    taskId: string,
    reviewId: string,
    payload: HumanReviewMutationPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.patch<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/human-reviews/${reviewId}`,
        payload,
      )
      return response.data
    })
  }

  async function createHumanReviewComment(
    workspaceId: string,
    taskId: string,
    reviewId: string,
    payload: HumanReviewCommentPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.post<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/human-reviews/${reviewId}/comments`,
        payload,
      )
      return response.data
    })
  }

  async function createHumanDelta(
    workspaceId: string,
    taskId: string,
    payload: HumanDeltaMutationPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.post<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/human-deltas`,
        payload,
      )
      return response.data
    })
  }

  async function updateHumanDelta(
    workspaceId: string,
    taskId: string,
    deltaId: string,
    payload: HumanDeltaMutationPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.patch<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/human-deltas/${deltaId}`,
        payload,
      )
      return response.data
    })
  }

  async function createEvidence(
    workspaceId: string,
    taskId: string,
    payload: EvidenceMutationPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.post<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/evidence`,
        payload,
      )
      return response.data
    })
  }

  async function updateEvidence(
    workspaceId: string,
    taskId: string,
    evidenceId: string,
    payload: EvidenceMutationPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.patch<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/evidence/${evidenceId}`,
        payload,
      )
      return response.data
    })
  }

  async function createDecision(
    workspaceId: string,
    taskId: string,
    payload: DecisionMutationPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.post<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/decisions`,
        payload,
      )
      return response.data
    })
  }

  async function updateDecision(
    workspaceId: string,
    taskId: string,
    decisionId: string,
    payload: DecisionMutationPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.patch<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/decisions/${decisionId}`,
        payload,
      )
      return response.data
    })
  }

  async function createClarification(
    workspaceId: string,
    taskId: string,
    payload: ClarificationMutationPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.post<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/clarifications`,
        payload,
      )
      return response.data
    })
  }

  async function updateClarification(
    workspaceId: string,
    taskId: string,
    clarificationId: string,
    payload: ClarificationMutationPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.patch<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/clarifications/${clarificationId}`,
        payload,
      )
      return response.data
    })
  }

  async function upsertFinalSummary(
    workspaceId: string,
    taskId: string,
    payload: TaskFinalSummaryPayload,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.put<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/final-summary`,
        payload,
      )
      return response.data
    })
  }

  async function suggestDeltas(
    workspaceId: string,
    taskId: string,
  ): Promise<HumanDeltaSuggestionsResponse | null> {
    try {
      const response = await api.get<HumanDeltaSuggestionsResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/human-deltas/suggestions`,
      )
      return response.data
    } catch {
      return null
    }
  }

  async function compareDelta(
    workspaceId: string,
    taskId: string,
    deltaId: string,
  ): Promise<TaskDetailSummaryResponse | null> {
    return mutate(async () => {
      const response = await api.post<TaskDetailSummaryResponse>(
        `/workspaces/${workspaceId}/workspace-assets/tasks/${taskId}/human-deltas/${deltaId}/compare`,
      )
      return response.data
    })
  }

  return {
    saving: readonly(saving),
    error: readonly(error),
    createHumanReview,
    updateHumanReview,
    createHumanReviewComment,
    createHumanDelta,
    updateHumanDelta,
    suggestDeltas,
    compareDelta,
    createEvidence,
    updateEvidence,
    createDecision,
    updateDecision,
    createClarification,
    updateClarification,
    upsertFinalSummary,
  }
}
