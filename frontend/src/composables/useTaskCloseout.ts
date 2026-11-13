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

type CloseoutPayload = Omit<CompleteCloseoutPayload, 'evidence_attachments'> | Omit<FailCloseoutPayload, 'evidence_attachments'>

export function useTaskCloseout() {
  const { t } = useI18n()
  const saving = shallowRef(false)
  const error = shallowRef<string | null>(null)
  const uploadedFiles = new WeakMap<File, { task: string; reference: CloseoutEvidenceAttachment }>()

  function closeoutError(reason: unknown): string {
    const code = (reason as { response?: { data?: { detail?: { code?: string } } } } | null)
      ?.response?.data?.detail?.code
    if (code === 'CLOSEOUT_AGENT_ACTIVE') return t('chat.closeout.availability.agent_active')
    if (code === 'CLOSEOUT_COLLABORATION_CONNECTED') return t('chat.closeout.availability.connection_changed')
    return formatApiError(reason, t('chat.closeout.errors.submit_failed'), t)
  }

  async function uploadEvidenceFiles(task: string, files: File[]): Promise<CloseoutEvidenceAttachment[]> {
    const attachments: CloseoutEvidenceAttachment[] = []
    for (const file of files) {
      const uploaded = uploadedFiles.get(file)
      if (uploaded?.task === task) {
        attachments.push(uploaded.reference)
        continue
      }
      const form = new FormData()
      form.append('file', file)
      const response = await api.post<{ id: string }>(`${task}/attachments`, form)
      const attachment = { attachment_id: response.data.id }
      uploadedFiles.set(file, { task, reference: attachment })
      attachments.push(attachment)
    }
    return attachments
  }

  async function submitCloseout(
    workspaceId: string,
    taskId: string,
    action: 'complete' | 'fail',
    payload: CloseoutPayload,
    files: File[],
  ): Promise<TaskCloseoutResponse | null> {
    if (saving.value) return null
    saving.value = true
    error.value = null
    try {
      const task = `/workspaces/${workspaceId}/tasks/${taskId}/closeout`
      const evidence_attachments = await uploadEvidenceFiles(task, files)
      const response = await api.post<TaskCloseoutResponse>(
        `${task}/${action}`,
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

  function completeTask(
    workspaceId: string,
    taskId: string,
    payload: Omit<CompleteCloseoutPayload, 'evidence_attachments'>,
    files: File[],
  ) {
    return submitCloseout(workspaceId, taskId, 'complete', payload, files)
  }

  function failTask(
    workspaceId: string,
    taskId: string,
    payload: Omit<FailCloseoutPayload, 'evidence_attachments'>,
    files: File[],
  ) {
    return submitCloseout(workspaceId, taskId, 'fail', payload, files)
  }

  return {
    saving: readonly(saving),
    error: readonly(error),
    completeTask,
    failTask,
  }
}
