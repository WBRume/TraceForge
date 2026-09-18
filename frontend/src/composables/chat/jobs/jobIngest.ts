import type { ChatAiJob } from '../types'

type JobStore = {
  upsert: (job: ChatAiJob) => void
}

type CardStore = {
  markAnsweredForJob: (jobId: string, status: string) => void
}

/**
 * job 摄取管线：任何来源（WS 事件 / REST 快照 / 诊断总结轮询）写入 job 都走这里，
 * 统一触发跨域反应——HITL 卡收敛、引擎运行态跟随、终端态回调（诊断结果刷新等）。
 */
export function createChatJobIngest(deps: {
  jobs: JobStore
  cards: CardStore
  syncEngineFromJobs: () => void
  onJobUpdate: (job: ChatAiJob) => void
}) {
  return (job: ChatAiJob) => {
    if (!job?.id) return
    deps.jobs.upsert(job)
    if (job.status !== 'WAITING_HITL') {
      deps.cards.markAnsweredForJob(job.id, job.status)
    }
    deps.syncEngineFromJobs()
    deps.onJobUpdate(job)
  }
}
