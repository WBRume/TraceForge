import { describe, expect, it, vi } from 'vitest'
import { createChatJobIngest } from '../jobs/jobIngest'
import type { ChatAiJob } from '../types'

const job = (overrides: Partial<ChatAiJob>): ChatAiJob => ({
  id: 'j1',
  task_id: 't1',
  status: 'PENDING',
  progress: 0,
  ...overrides,
})

const createStores = () => {
  const activeJobs: Record<string, ChatAiJob> = {}
  const jobs = {
    upsert: (next: ChatAiJob) => {
      if (['PENDING', 'RUNNING', 'WAITING_HITL', 'INTERRUPTED'].includes(next.status)) activeJobs[next.id] = next
      else delete activeJobs[next.id]
    },
  }
  const marked: Array<{ jobId: string; status: string }> = []
  const cards = {
    markAnsweredForJob: (jobId: string, status: string) => marked.push({ jobId, status }),
  }
  const engineSync = vi.fn()
  const terminalUpdates: ChatAiJob[] = []
  return { activeJobs, jobs, cards, marked, engineSync, terminalUpdates }
}

describe('createChatJobIngest', () => {
  it('applies the same cross-domain reactions for every job source', () => {
    const { activeJobs, jobs, cards, marked, engineSync, terminalUpdates } = createStores()
    const ingest = createChatJobIngest({
      jobs,
      cards,
      syncEngineFromJobs: engineSync,
      onJobUpdate: (next) => terminalUpdates.push(next),
    })

    ingest(job({ id: 'j1', status: 'RUNNING' }))
    expect(activeJobs.j1?.status).toBe('RUNNING')
    // 非 WAITING_HITL 的推进都会收敛未答复的 HITL 卡（进行中给「已提交」文案）
    expect(marked).toEqual([{ jobId: 'j1', status: 'RUNNING' }])
    expect(engineSync).toHaveBeenCalledTimes(1)
    expect(terminalUpdates).toHaveLength(1)

    ingest(job({ id: 'j1', status: 'WAITING_HITL' }))
    expect(marked).toHaveLength(1) // WAITING_HITL：等待用户输入，不收敛卡片
    expect(engineSync).toHaveBeenCalledTimes(2)

    ingest(job({ id: 'j1', status: 'FAILED' }))
    expect(activeJobs.j1).toBeUndefined() // 终态移出活跃表
    expect(marked).toEqual([
      { jobId: 'j1', status: 'RUNNING' },
      { jobId: 'j1', status: 'FAILED' },
    ])
    expect(engineSync).toHaveBeenCalledTimes(3)
    expect(terminalUpdates).toHaveLength(3)
  })

  it('ignores malformed jobs without an id', () => {
    const { engineSync, jobs, cards, marked, terminalUpdates } = createStores()
    const ingest = createChatJobIngest({
      jobs,
      cards,
      syncEngineFromJobs: engineSync,
      onJobUpdate: (next) => terminalUpdates.push(next),
    })
    ingest(job({ id: '' } as Partial<ChatAiJob> as ChatAiJob))
    expect(engineSync).not.toHaveBeenCalled()
    expect(marked).toEqual([])
    expect(terminalUpdates).toEqual([])
  })
})
