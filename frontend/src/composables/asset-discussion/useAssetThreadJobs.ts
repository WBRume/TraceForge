import { ref } from 'vue'
import api from '@/utils/api'
import type { AssetAiJob, ThreadJobKind } from './types'
import type { AssetRequestOwner, AssetRequestScope } from './requestScope'

export const isThreadJobActive = (status?: string | null) => (
  status === 'PENDING' || status === 'RUNNING' || status === 'WAITING_HITL'
)

export const resolveThreadJobKind = (job: AssetAiJob): ThreadJobKind => {
  const kind = String(job.context_json?.job_kind || '').trim().toUpperCase()
  return kind === 'RESOLUTION_REWRITE' || kind === 'RESOLUTION_PROPOSAL' ? kind : 'THREAD_AI_REPLY'
}

export function useAssetThreadJobs(
  scope: AssetRequestScope,
  fetchThread: (threadId: string, owner: AssetRequestOwner) => Promise<unknown>,
) {
  const assistantJobMap = ref<Record<string, AssetAiJob>>({})
  const proposalJobMap = ref<Record<string, AssetAiJob>>({})
  const polls = new Map<string, { timer?: number; controller: AbortController; owner: AssetRequestOwner }>()

  const stopPolling = (threadId: string) => {
    const poll = polls.get(threadId)
    if (!poll) return
    polls.delete(threadId)
    if (poll.timer !== undefined) window.clearTimeout(poll.timer)
    poll.controller.abort()
  }

  const clearJobMaps = (threadId: string) => {
    delete assistantJobMap.value[threadId]
    delete proposalJobMap.value[threadId]
  }

  const schedulePolling = (threadId: string) => {
    const resource = scope.capture()
    if (polls.has(threadId) || !resource?.isCurrent()) return
    const controller = new AbortController()
    const owner: AssetRequestOwner = {
      ...resource,
      signal: controller.signal,
      isCurrent: () => resource.isCurrent() && !controller.signal.aborted && polls.get(threadId) === poll,
    }
    const poll = { timer: undefined as number | undefined, controller, owner }
    polls.set(threadId, poll)
    const stop = () => stopPolling(threadId)
    resource.signal.addEventListener('abort', stop, { once: true })
    controller.signal.addEventListener('abort', () => resource.signal.removeEventListener('abort', stop), { once: true })

    const tick = async () => {
      if (!owner.isCurrent()) return
      poll.timer = undefined
      try {
        const items = await loadThreadJobs(threadId, true, owner, true)
        if (!owner.isCurrent()) return
        if (items && !items.some(item => isThreadJobActive(item.status))) {
          if (!items.length) {
            try { await fetchThread(threadId, owner) } catch { /* Retry through later synchronization. */ }
          }
          if (owner.isCurrent()) stopPolling(threadId)
          return
        }
      } catch {
        // Retry transient failures while this poll still owns the resource.
      } finally {
        if (owner.isCurrent()) poll.timer = window.setTimeout(tick, 1800)
      }
    }
    poll.timer = window.setTimeout(tick, 1800)
  }

  const setThreadJob = (job: AssetAiJob, owner = scope.capture(), trackPolling = true) => {
    if (!owner?.isCurrent() || !job.thread_id || job.workspace_id !== owner.wsId || job.asset_id !== owner.assetId) return
    const target = resolveThreadJobKind(job) === 'THREAD_AI_REPLY' ? assistantJobMap : proposalJobMap
    target.value[job.thread_id] = job
    if (!trackPolling) return
    const active = [assistantJobMap.value[job.thread_id], proposalJobMap.value[job.thread_id]]
      .some(item => isThreadJobActive(item?.status))
    if (active) schedulePolling(job.thread_id)
    else stopPolling(job.thread_id)
  }

  const clearThreadJobByKind = (threadId: string, kind: ThreadJobKind) => {
    const target = kind === 'THREAD_AI_REPLY' ? assistantJobMap : proposalJobMap
    delete target.value[threadId]
  }

  const loadThreadJobs = (threadId: string, activeOnly = true, owner = scope.capture(), fromPoll = false) => (
    scope.run<AssetAiJob[] | null>(`jobs:${threadId}`, threadId ? owner : undefined, async (request) => {
      const res = await api.get(`${request.baseUrl}/threads/${threadId}/ai-jobs`, {
        params: { active_only: activeOnly }, signal: request.signal,
      })
      if (!request.isCurrent()) return null
      const items = ((res.data?.items || []) as AssetAiJob[]).filter(item => (
        item.workspace_id === request.wsId && item.asset_id === request.assetId && item.thread_id === threadId
      ))
      if (activeOnly) clearJobMaps(threadId)
      for (const item of items) setThreadJob(item, owner, false)
      if (!fromPoll) {
        if (items.some(item => isThreadJobActive(item.status))) schedulePolling(threadId)
        else stopPolling(threadId)
      }
      return items
    }, null)
  )

  const refreshThreadJobs = async (threadIds: string[], owner: AssetRequestOwner) => {
    await Promise.all(threadIds.map(async (threadId) => {
      try { await loadThreadJobs(threadId, true, owner) } catch { /* Keep discussion available. */ }
    }))
  }

  const cancelAiJob = (jobId: string) => scope.run<AssetAiJob | null>(
    null, jobId ? scope.capture() : undefined, async (request) => {
      const res = await api.post(`/workspaces/${request.wsId}/ai-jobs/${jobId}/cancel`, undefined, { signal: request.signal })
      if (!request.isCurrent()) return null
      const job = res.data as AssetAiJob
      setThreadJob(job, request)
      return job
    }, null,
  )

  const reset = () => {
    for (const threadId of polls.keys()) stopPolling(threadId)
    assistantJobMap.value = {}
    proposalJobMap.value = {}
  }

  return {
    assistantJobMap, proposalJobMap, setThreadJob, clearThreadJobByKind,
    loadThreadJobs, refreshThreadJobs, cancelAiJob, reset,
  }
}

export type AssetThreadJobsModel = ReturnType<typeof useAssetThreadJobs>
