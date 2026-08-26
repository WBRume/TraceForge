import api from '@/utils/api'
import type {
  RagQueueCasePageResponse,
  RagQueuePageResponse,
  RagQueueStatus,
  RagSyncQueueItem,
} from '@/types/rag'

export type RagQueueListParams = {
  workspace_id?: string
  status?: RagQueueStatus
  page?: number
  page_size?: number
}

export type RagQueueCasesParams = {
  page?: number
  page_size?: number
}

/**
 * 案例同步队列：分页加载队列批次（运行中 / 已消费）。
 */
export const fetchRagQueues = async (
  params: RagQueueListParams,
): Promise<RagQueuePageResponse> => {
  const res = await api.get<RagQueuePageResponse>('/rag/queues', { params })
  return res.data
}

/**
 * 队列详情（含案例数 / 已导出数）。
 */
export const fetchRagQueue = async (queueId: string): Promise<RagSyncQueueItem> => {
  const res = await api.get<RagSyncQueueItem>(`/rag/queues/${queueId}`)
  return res.data
}

/**
 * 队列内案例清单（分页）。
 */
export const fetchRagQueueCases = async (
  queueId: string,
  params?: RagQueueCasesParams,
): Promise<RagQueueCasePageResponse> => {
  const res = await api.get<RagQueueCasePageResponse>(`/rag/queues/${queueId}/cases`, {
    params,
  })
  return res.data
}

const saveBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * 下载整个同步队列的案例 MD ZIP。
 * 首次成功下载后队列将锁定为「已消费」终态；终态后仍可重复下载（幂等重新打包）。
 */
export const downloadRagQueueZip = async (
  queueId: string,
  queueName = 'rag-case-queue',
): Promise<void> => {
  const res = await api.get<Blob>(`/rag/queues/${queueId}/export.zip`, {
    responseType: 'blob',
  })
  saveBlob(new Blob([res.data], { type: 'application/zip' }), `${queueName}.zip`)
}

/**
 * 下载队列内单个案例 MD；下载成功后该案例锁定标记为「已导出」（可重下）。
 */
export const downloadRagQueueCase = async (
  queueId: string,
  caseId: string,
  filename = 'case.md',
): Promise<void> => {
  const res = await api.get<Blob>(
    `/rag/queues/${queueId}/cases/${caseId}/export.md`,
    { responseType: 'blob' },
  )
  saveBlob(new Blob([res.data], { type: 'text/markdown' }), filename)
}