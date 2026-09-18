import { ref } from 'vue'
import api from '@/utils/api'
import type { ChatAiJob, ChatAiJobStatus } from '../types'

/** 活跃 AI job 生命周期状态（排队/执行中/HITL 挂起/中断）。 */
export const isJobActive = (status?: ChatAiJobStatus) => (
  status === 'PENDING' || status === 'RUNNING' || status === 'WAITING_HITL' || status === 'INTERRUPTED'
)

/** 引擎实际执行中（不含已中断）。 */
export const isJobExecuting = (status?: ChatAiJobStatus) => (
  status === 'PENDING' || status === 'RUNNING' || status === 'WAITING_HITL'
)

/**
 * 活跃 AI job 登记：task 级 job 表（PENDING/RUNNING/WAITING_HITL/INTERRUPTED 保持在表内，
 * 终态移出）。纯状态存储；job 变更的跨域反应（HITL 卡收敛、引擎态、诊断刷新）见 jobIngest。
 */
export function useChatJobs(options: {
  getWorkspaceId: () => string
  getTaskId: () => string
  getSignal: () => AbortSignal | undefined
  onLoaded: (taskId: string, items: ChatAiJob[]) => boolean
}) {
  const activeChatJobs = ref<Record<string, ChatAiJob>>({})
  // 请求代次：新 job 事件或新请求都会使更早的在途快照失效
  let requestSeq = 0

  const jobList = () => Object.values(activeChatJobs.value)

  const hasExecutingJob = () => jobList().some(job => isJobExecuting(job.status))

  const upsert = (job: ChatAiJob) => {
    requestSeq += 1
    if (!job?.id) return
    const nextJobs = { ...activeChatJobs.value }
    if (isJobActive(job.status)) {
      nextJobs[job.id] = job
    } else {
      delete nextJobs[job.id]
    }
    activeChatJobs.value = nextJobs
  }

  const reset = () => {
    activeChatJobs.value = {}
  }

  /** 拉取当前活跃 job 列表并整体重建；onLoaded 由组合根注入（运行面板收敛）。 */
  const loadActive = async (taskId: string): Promise<boolean> => {
    const seq = ++requestSeq
    try {
      const res = await api.get(`/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/ai-jobs`, {
        params: { active_only: true },
        signal: options.getSignal(),
      })
      const items = (res.data?.items || []) as ChatAiJob[]
      if (
        seq !== requestSeq
        || options.getTaskId() !== String(taskId)
      ) return false
      activeChatJobs.value = {}
      for (const job of items) {
        upsert(job)
      }
      return options.onLoaded(taskId, items)
    } catch (e) {
      if (!isCanceledRequestError(e)) console.warn('Failed to load active AI jobs', e)
      return false
    }
  }

  return {
    activeChatJobs,
    jobList,
    hasExecutingJob,
    upsert,
    reset,
    loadActive,
  }
}

const isCanceledRequestError = (error: unknown): boolean => (
  (error as { code?: string })?.code === 'ERR_CANCELED'
  || (error as { name?: string })?.name === 'CanceledError'
)
