import { defineStore } from 'pinia'

type PendingTaskSpecUpload = {
  workspaceId: string
  taskId: string
  file: File
}

type PendingTaskDocsUpload = {
  workspaceId: string
  taskId: string
  files: File[]
}

const pendingSpecByJob = new Map<string, PendingTaskSpecUpload>()
const pendingDocsByJob = new Map<string, PendingTaskDocsUpload>()

export const useProvisioningStore = defineStore('provisioning', () => {
  const setPendingTaskSpec = (jobId: string, payload: PendingTaskSpecUpload) => {
    const normalizedJobId = String(jobId || '').trim()
    if (!normalizedJobId) return
    pendingSpecByJob.set(normalizedJobId, payload)
  }

  const consumePendingTaskSpec = (jobId: string): PendingTaskSpecUpload | null => {
    const normalizedJobId = String(jobId || '').trim()
    if (!normalizedJobId) return null
    const payload = pendingSpecByJob.get(normalizedJobId) || null
    if (payload) {
      pendingSpecByJob.delete(normalizedJobId)
    }
    return payload
  }

  const clearPendingTaskSpec = (jobId: string) => {
    const normalizedJobId = String(jobId || '').trim()
    if (!normalizedJobId) return
    pendingSpecByJob.delete(normalizedJobId)
  }

  /** 问题定位任务：暂存待上传的需求/日志文档（任务创建完成后由 Provisioning 页上传） */
  const setPendingTaskDocs = (jobId: string, payload: PendingTaskDocsUpload) => {
    const normalizedJobId = String(jobId || '').trim()
    if (!normalizedJobId || !payload.files || payload.files.length === 0) return
    pendingDocsByJob.set(normalizedJobId, payload)
  }

  const consumePendingTaskDocs = (jobId: string): PendingTaskDocsUpload | null => {
    const normalizedJobId = String(jobId || '').trim()
    if (!normalizedJobId) return null
    const payload = pendingDocsByJob.get(normalizedJobId) || null
    if (payload) {
      pendingDocsByJob.delete(normalizedJobId)
    }
    return payload
  }

  const clearPendingTaskDocs = (jobId: string) => {
    const normalizedJobId = String(jobId || '').trim()
    if (!normalizedJobId) return
    pendingDocsByJob.delete(normalizedJobId)
  }

  return {
    setPendingTaskSpec,
    consumePendingTaskSpec,
    clearPendingTaskSpec,
    setPendingTaskDocs,
    consumePendingTaskDocs,
    clearPendingTaskDocs,
  }
})
