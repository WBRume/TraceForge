import { shallowRef } from 'vue'

import api from '@/utils/api'

type WorkspaceIdGetter = () => string

interface UseTaskSessionControlsOptions {
  getWorkspaceId: WorkspaceIdGetter
}

interface ResumeInterruptedOptions {
  prompt?: string
  confirmContinue?: boolean
  clientMessageId?: string
}

export function useTaskSessionControls(options: UseTaskSessionControlsOptions) {
  const interruptingTask = shallowRef(false)
  const resumingInterruptedTask = shallowRef(false)

  const taskUrl = (taskId: string, action: string) => {
    const wsId = options.getWorkspaceId()
    return `/workspaces/${wsId}/tasks/${taskId}/${action}`
  }

  const interruptTask = async (taskId: string, reason?: string) => {
    interruptingTask.value = true
    try {
      const res = await api.post(taskUrl(taskId, 'interrupt'), {
        reason: String(reason || '').trim() || undefined,
      })
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
      })
      return res.data
    } finally {
      resumingInterruptedTask.value = false
    }
  }

  return {
    interruptingTask,
    resumeInterruptedTask,
    resumingInterruptedTask,
    interruptTask,
  }
}
