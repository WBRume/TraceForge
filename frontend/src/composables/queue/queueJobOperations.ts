import { parseContract } from '../../../shared/contracts/validate'
import type { Router } from 'vue-router'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type {
  QueueJobActionResponse,
  QueueJobItem,
  QueueJobListResponse,
  QueueSource,
  QueueStatus,
  QueueView,
} from '@/types/queue'

type PendingTaskSpec = {
  workspaceId: string
  taskId: string
  file: File
}

type ProvisioningStoreLike = {
  consumePendingTaskSpec: (jobId: string) => PendingTaskSpec | null
}

type TranslateFn = (key: string, ...args: any[]) => string

export type QueueListParams = {
  view: QueueView
  page: number
  page_size: number
  source?: QueueSource
  status?: QueueStatus
  workspace_id?: string
}

export const fetchQueueJobs = async (params: QueueListParams): Promise<QueueJobListResponse> => {
  const res = await api.get<QueueJobListResponse>('/queue/jobs', { params })
  return res.data
}

export const fetchQueueJob = async (source: QueueSource, jobId: string): Promise<QueueJobItem> => {
  const normalizedJobId = String(jobId || '').trim()
  const res = await api.get<QueueJobItem>(`/queue/jobs/${source}/${normalizedJobId}`)
  return res.data
}

export const runQueueJobAction = async (
  source: QueueSource,
  jobId: string,
  action: 'stop' | 'retry',
  version: number,
): Promise<QueueJobActionResponse> => {
  const normalizedJobId = String(jobId || '').trim()
  const command = { contract_version: 2, command_id: crypto.randomUUID(), expected_version: version }
  parseContract('queueJobCommand', command)
  const res = await api.post<unknown>(`/queue/jobs/${source}/${normalizedJobId}/${action}`, command)
  const receipt = parseContract<QueueJobActionResponse>('queueJobActionResponse', res.data)
  if (receipt.command_id !== command.command_id || receipt.job_id !== normalizedJobId || receipt.action !== action || receipt.source !== source) {
    throw new Error('QUEUE_COMMAND_RECEIPT_MISMATCH')
  }
  return receipt
}

export const openQueueJobTarget = async (
  item: QueueJobItem,
  deps: {
    router: Router
    provisioningStore: ProvisioningStoreLike
    t: TranslateFn
    isCurrent?: () => boolean
  },
): Promise<{ warningMessage?: string }> => {
  const targetPath = String(item.target_path || '').trim()
  if (!targetPath) return {}

  let warningMessage = ''
  if (item.source === 'provision' && item.job_type === 'CREATE_TASK' && item.status === 'SUCCESS') {
    const pendingSpec = deps.provisioningStore.consumePendingTaskSpec(item.job_id)
    if (pendingSpec?.file) {
      try {
        const formData = new FormData()
        formData.append('file', pendingSpec.file)
        await api.post(
          `/workspaces/${pendingSpec.workspaceId}/tasks/${pendingSpec.taskId}/upload-spec`,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' } },
        )
      } catch (err) {
        warningMessage = formatApiError(err, deps.t('provisioning.spec_upload_failed'), deps.t)
      }
    }
  }

  if (deps.isCurrent?.() === false) return {}
  await deps.router.push(targetPath)
  return warningMessage ? { warningMessage } : {}
}

