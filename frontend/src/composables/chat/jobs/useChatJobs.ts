import { ref } from 'vue'
import api from '@/utils/api'
import { acceptsJobSnapshot } from '@/utils/jobSnapshot'
import type { ChatAiJob, ChatAiJobStatus } from '../types'

/** 活跃 AI job 生命周期状态（排队/执行中/HITL 挂起/中断）。 */
export const isJobActive = (status?: ChatAiJobStatus) => (
  status === 'PENDING' || status === 'RUNNING' || status === 'WAITING_HITL' || status === 'INTERRUPTED' || status === 'TERMINATING' || status === 'ORPHANED'
)

/** 引擎实际执行中（不含已中断）。 */
export const isJobExecuting = (status?: ChatAiJobStatus) => (
  status === 'PENDING' || status === 'RUNNING' || status === 'WAITING_HITL' || status === 'TERMINATING' || status === 'ORPHANED'
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
  let observation = 0
  let resetAt = 0
  let lastSnapshotCursor = 0
  const observed = new Map<string, { job: ChatAiJob; at: number }>()

  const jobList = () => Object.values(activeChatJobs.value)

  const hasExecutingJob = () => jobList().some(job => isJobExecuting(job.status))

  const upsert = (job: ChatAiJob) => {
    if (!job?.id || !acceptsJobSnapshot(observed.get(job.id)?.job, job)) return false
    observed.set(job.id, { job, at: ++observation })
    if (isJobActive(job.status)) {
      activeChatJobs.value = { ...activeChatJobs.value, [job.id]: job }
    } else if (activeChatJobs.value[job.id]) {
      const nextJobs = { ...activeChatJobs.value }
      delete nextJobs[job.id]
      activeChatJobs.value = nextJobs
    }
    return true
  }

  const reset = () => {
    resetAt = ++observation
    activeChatJobs.value = {}
    observed.clear()
  }

  const snapshotCursor = () => ++observation

  /** 同 ID 比作业版本；缺席只移除在请求发出后没有更新过的活跃作业。 */
  const mergeSnapshot = (items: ChatAiJob[], cursor: number, generation?: number) => {
    if (cursor < resetAt) return null
    if (cursor < lastSnapshotCursor) return { accepted: [], items: jobList() }
    lastSnapshotCursor = cursor
    const current = activeChatJobs.value
    let next = current
    const present = new Set<string>()
    const accepted: ChatAiJob[] = []
    const isPreviousGeneration = (job: ChatAiJob) => generation != null
      && job.session_generation != null && job.session_generation < generation

    for (const job of items) {
      if (!job?.id || isPreviousGeneration(job)) continue
      present.add(job.id)
      const prior = observed.get(job.id)
      if (!acceptsJobSnapshot(prior?.job, job)) {
        // 已被较早快照移出，但当前快照确认了该版本仍在活跃集合中。
        if (!next[job.id] && prior && prior.job.version === job.version && isJobActive(prior.job.status)) {
          if (next === current) next = { ...current }
          next[job.id] = prior.job
        }
        continue
      }
      observed.set(job.id, { job, at: ++observation })
      accepted.push(job)
      if (isJobActive(job.status)) {
        if (next === current) next = { ...current }
        next[job.id] = job
      } else if (next[job.id]) {
        if (next === current) next = { ...current }
        delete next[job.id]
      }
    }
    for (const [id, job] of Object.entries(current)) {
      if (!isPreviousGeneration(job) && (present.has(id) || (observed.get(id)?.at ?? 0) > cursor)) continue
      if (next === current) next = { ...current }
      delete next[id]
    }
    if (next !== current) activeChatJobs.value = next
    return { accepted, items: jobList() }
  }

  const loadActive = async (taskId: string): Promise<boolean> => {
    const cursor = snapshotCursor()
    try {
      const res = await api.get(`/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/ai-jobs`, {
        params: { active_only: true },
        signal: options.getSignal(),
      })
      const items = (res.data?.items || []) as ChatAiJob[]
      if (options.getTaskId() !== String(taskId)) return false
      const merged = mergeSnapshot(items, cursor)
      return merged !== null && options.onLoaded(taskId, merged.items)
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
    snapshotCursor,
    mergeSnapshot,
    loadActive,
  }
}

const isCanceledRequestError = (error: unknown): boolean => (
  (error as { code?: string })?.code === 'ERR_CANCELED'
  || (error as { name?: string })?.name === 'CanceledError'
)
