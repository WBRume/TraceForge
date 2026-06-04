import { defineStore } from 'pinia'

type PendingTaskSpecUpload = {
  workspaceId: string
  taskId: string
  file: File
}

const pendingSpecByJob = new Map<string, PendingTaskSpecUpload>()

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

  return {
    setPendingTaskSpec,
    consumePendingTaskSpec,
    clearPendingTaskSpec,
  }
})
