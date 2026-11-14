import { shallowRef } from 'vue'

import api from '@/utils/api'
import { generateClientMessageId } from './chat/shared/messageIdentity'

type WorkspaceIdGetter = () => string

interface UseTaskSessionControlsOptions {
  getWorkspaceId: WorkspaceIdGetter
  getSubmissionMetadata?: () => Record<string, unknown>
}

interface ResumeInterruptedOptions {
  agentModel?: import('@/composables/useAgentModels').AgentModelSelection
  prompt?: string
  confirmContinue?: boolean
  clientMessageId?: string
  newAgentSession?: boolean
}

interface UndoMessageOptions {
  operationId: string
}

export function useTaskSessionControls(options: UseTaskSessionControlsOptions) {
  const interruptingTask = shallowRef(false)
  const resumingInterruptedTask = shallowRef(false)
  const undoingTaskMessage = shallowRef(false)

  const taskUrl = (taskId: string, action: string) => {
    const wsId = options.getWorkspaceId()
    return `/workspaces/${wsId}/tasks/${taskId}/${action}`
  }

  const pendingInterrupts = new Map<string, string>()
  const interruptTask = async (taskId: string, reason?: string) => {
    const commandId = pendingInterrupts.get(taskId) || generateClientMessageId()
    pendingInterrupts.set(taskId, commandId)
    interruptingTask.value = true
    try {
      const res = await api.post(taskUrl(taskId, 'interrupt'), {
        reason: String(reason || '').trim() || undefined,
        command_id: commandId,
      })
      pendingInterrupts.delete(taskId)
      return res.data
    } finally {
      interruptingTask.value = false
    }
  }

  const resumeInterruptedTask = async (taskId: string, resumeOptions: ResumeInterruptedOptions) => {
    resumingInterruptedTask.value = true
    try {
      const res = await api.post(taskUrl(taskId, 'resume-interrupted'), {
        prompt: String(resumeOptions.prompt || '').trim() || undefined,
        confirm_continue: Boolean(resumeOptions.confirmContinue),
        client_message_id: String(resumeOptions.clientMessageId || '').trim() || undefined,
        agent_model: resumeOptions.agentModel,
        ...(resumeOptions.newAgentSession ? { new_agent_session: true } : {}),
        metadata: options.getSubmissionMetadata?.(),
      })
      return res.data
    } finally {
      resumingInterruptedTask.value = false
    }
  }

  const undoTaskMessage = async (taskId: string, messageId: string, undoOptions: UndoMessageOptions) => {
    undoingTaskMessage.value = true
    try {
      const res = await api.post(
        `${taskUrl(taskId, `messages/${encodeURIComponent(messageId)}/undo`)}`,
        { operation_id: undoOptions.operationId },
        // Undo returns only after restore/verification. A client-side deadline
        // cannot cancel those writes and would falsely report failure.
        { timeout: 0 },
      )
      return res.data
    } finally {
      undoingTaskMessage.value = false
    }
  }

  return {
    interruptingTask,
    resumeInterruptedTask,
    resumingInterruptedTask,
    undoingTaskMessage,
    interruptTask,
    undoTaskMessage,
  }
}
