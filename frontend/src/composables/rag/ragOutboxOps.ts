import api from '@/utils/api'
import { getSddDesktop } from '@/utils/runtime'
import type {
  RagQueueCaseItem,
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

export type SaveToDiskResult = {
  /** 文件是否已成功写入本地磁盘 */
  saved: boolean
  /** 用户取消了保存对话框（未保存，不应标记状态） */
  canceled: boolean
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

const anchorFallback = (blob: Blob, filename: string) => {
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
 * 浏览器（Chromium）走 File System Access API：
 * 弹出「另存为」对话框，用户确认保存位置并写入完成后才返回 true；
 * 用户取消（AbortError）返回 false 且 canceled=true。
 */
type SaveFilePickerWritable = {
  write: (data: Blob) => Promise<void>
  close: () => Promise<void>
}

type SaveFilePickerHandle = {
  createWritable: () => Promise<SaveFilePickerWritable>
}

const saveBlobViaFilePicker = async (blob: Blob, filename: string): Promise<SaveToDiskResult> => {
  const picker = (
    window as Window & {
      showSaveFilePicker?: (options: { suggestedName?: string }) => Promise<SaveFilePickerHandle>
    }
  ).showSaveFilePicker
  if (typeof picker !== 'function') {
    return { saved: false, canceled: false }
  }
  try {
    const handle = await picker.call(window, { suggestedName: filename })
    const writable = await handle.createWritable()
    await writable.write(blob)
    await writable.close()
    return { saved: true, canceled: false }
  } catch (err) {
    if ((err as DOMException)?.name === 'AbortError') {
      return { saved: false, canceled: true }
    }
    throw err
  }
}

/**
 * 将文件字节保存到本地磁盘：
 * 1. Electron 桌面端：原生「另存为」对话框，用户确认保存位置、写盘完成后才返回；
 * 2. 浏览器（Chromium）：showSaveFilePicker，同样在写盘完成后返回；
 * 3. 其他浏览器（Firefox/Safari 等）：降级为 <a download>，无法感知保存结果（尽力而为）。
 *
 * 返回 saved/canceled，调用方只有在 saved 时才应触发「标记已导出」确认接口。
 */
export const saveBlobToDisk = async (
  blob: Blob,
  filename: string,
): Promise<SaveToDiskResult> => {
  const desktop = getSddDesktop()
  if (desktop?.download) {
    try {
      const result = await desktop.download.save({
        suggestedName: filename,
        data: await blob.arrayBuffer(),
        mimeType: blob.type || undefined,
      })
      return { saved: Boolean(result.saved), canceled: Boolean(result.canceled) }
    } finally {
      /* Electron 主进程负责写盘；渲染进程无需额外处理 */
    }
  }

  const pickerResult = await saveBlobViaFilePicker(blob, filename)
  if (pickerResult.saved || pickerResult.canceled) return pickerResult

  anchorFallback(blob, filename)
  return { saved: true, canceled: false }
}

/**
 * 下载整个同步队列的案例 MD ZIP。
 * 仅拉取字节并保存到本地，**不标记任何状态**；
 * 保存成功（saved=true）后请调用 confirmRagQueueDownload 触发状态标记。
 */
export const downloadRagQueueZip = async (
  queueId: string,
  queueName = 'rag-case-queue',
): Promise<SaveToDiskResult> => {
  const res = await api.get<Blob>(`/rag/queues/${queueId}/export.zip`, {
    responseType: 'blob',
  })
  const blob = new Blob([res.data], { type: 'application/zip' })
  return saveBlobToDisk(blob, `${queueName}.zip`)
}

/**
 * 下载队列内单个案例 MD。
 * 仅拉取字节并保存到本地，**不标记任何状态**；
 * 保存成功（saved=true）后请调用 confirmRagQueueCaseDownload 触发状态标记。
 */
export const downloadRagQueueCase = async (
  queueId: string,
  caseId: string,
  filename = 'case.md',
): Promise<SaveToDiskResult> => {
  const res = await api.get<Blob>(
    `/rag/queues/${queueId}/cases/${caseId}/export.md`,
    { responseType: 'blob' },
  )
  const blob = new Blob([res.data], { type: 'text/markdown' })
  return saveBlobToDisk(blob, filename)
}

/**
 * 确认队列文件已成功保存到本地：首次确认时队列锁定为「已消费」终态（幂等，可重试）。
 */
export const confirmRagQueueDownload = async (queueId: string): Promise<RagSyncQueueItem> => {
  const res = await api.post<RagSyncQueueItem>(`/rag/queues/${queueId}/export/complete`)
  return res.data
}

/**
 * 确认单案例文件已成功保存到本地：标记该案例为「已导出」（幂等，可重下）。
 */
export const confirmRagQueueCaseDownload = async (
  queueId: string,
  caseId: string,
): Promise<RagQueueCaseItem> => {
  const res = await api.post<RagQueueCaseItem>(
    `/rag/queues/${queueId}/cases/${caseId}/export/complete`,
  )
  return res.data
}