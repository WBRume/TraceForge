import { readonly, shallowRef } from 'vue'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type { Decision } from '@/types/workspaceAssets'

export type ChatDecisionPayload = {
  title: string
  body?: string | null
  impact_scope?: string | null
  requirement_id?: string | null
  promote_candidate?: boolean
  change_reason?: string | null
}

export function useChatDecision() {
  const saving = shallowRef(false)
  const error = shallowRef<string | null>(null)

  async function markMessageAsDecision(
    workspaceId: string,
    taskId: string,
    messageId: string,
    payload: ChatDecisionPayload,
  ): Promise<Decision | null> {
    saving.value = true
    error.value = null
    try {
      const response = await api.post<Decision>(
        `/workspaces/${workspaceId}/tasks/${taskId}/messages/${messageId}/decision`,
        payload,
      )
      return response.data
    } catch (err) {
      error.value = formatApiError(err, 'Decision save failed')
      return null
    } finally {
      saving.value = false
    }
  }

  return {
    saving: readonly(saving),
    error: readonly(error),
    markMessageAsDecision,
  }
}
