import { readonly, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type {
  CloseoutEvidenceAttachment,
  CompleteCloseoutPayload,
  FailCloseoutPayload,
  TaskCloseoutResponse,
} from '@/types/taskCloseout'

type UploadResponse = {
  filename: string
  path: string
  url: string
}

export function useTaskCloseout() {
  const { t } = useI18n()
  const saving = shallowRef(false)
  const error = shallowRef<string | null>(null)

  function closeoutError(reason: unknown): string {
    const code = (reason as { response?: { data?: { detail?: { code?: string } } } } | null)
      ?.response?.data?.detail?.code
    if (code === 'CLOSEOUT_AGENT_ACTIVE') return t('chat.closeout.availability.agent_active')
    if (code === 'CLOSEOUT_COLLABORATION_CONNECTED') return t('chat.closeout.availability.connection_changed')
    return formatApiError(reason, t('chat.closeout.errors.submit_failed'), t)
  }

  async function uploadEvidenceFiles(files: File[]): Promise<CloseoutEvidenceAttachment[]> {
    const attachments: CloseoutEvidenceAttachment[] = []
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      const response = await api.post<UploadResponse>('/upload', form)
      attachments.push({
        filename: response.data.filename || file.name,
        source_uri: response.data.url,
        source_path: response.data.path,
        source_label: response.data.filename || file.name,
        content_type: file.type || null,
        size: file.size,
      })
    }
    return attachments
  }

  async function completeTask(
    workspaceId: string,
    taskId: string,
    payload: Omit<CompleteCloseoutPayload, 'evidence_attachments'>,
    files: File[],
  ): Promise<TaskCloseoutResponse | null> {
    saving.value = true
    error.value = null
    try {
      const evidence_attachments = await uploadEvidenceFiles(files)
      const response = await api.post<TaskCloseoutResponse>(
        `/workspaces/${workspaceId}/tasks/${taskId}/closeout/complete`,
        { ...payload, evidence_attachments },
      )
      return response.data
    } catch (err) {
      error.value = closeoutError(err)
      return null
    } finally {
      saving.value = false
    }
  }

  async function failTask(
    workspaceId: string,
    taskId: string,
    payload: Omit<FailCloseoutPayload, 'evidence_attachments'>,
    files: File[],
  ): Promise<TaskCloseoutResponse | null> {
    saving.value = true
    error.value = null
    try {
      const evidence_attachments = await uploadEvidenceFiles(files)
      const response = await api.post<TaskCloseoutResponse>(
        `/workspaces/${workspaceId}/tasks/${taskId}/closeout/fail`,
        { ...payload, evidence_attachments },
      )
      return response.data
    } catch (err) {
      error.value = closeoutError(err)
      return null
    } finally {
      saving.value = false
    }
  }

  return {
    saving: readonly(saving),
    error: readonly(error),
    completeTask,
    failTask,
    uploadEvidenceFiles,
  }
}
