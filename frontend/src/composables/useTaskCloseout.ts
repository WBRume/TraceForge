import { readonly, shallowRef } from 'vue'
import api from '@/utils/api'
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

function errorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response
    if (response?.data?.detail) return response.data.detail
  }
  return error instanceof Error ? error.message : 'Task closeout failed'
}

export function useTaskCloseout() {
  const saving = shallowRef(false)
  const error = shallowRef<string | null>(null)

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
      error.value = errorMessage(err)
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
      error.value = errorMessage(err)
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
