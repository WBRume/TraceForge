/**
 * 「一键总结问题案例」后台 job 的判定工具（纯函数，便于单测）。
 * 数据来源：TASK_CHAT 频道的 AI job（status + context_json.job_kind）。
 */

// Keep this boundary open to the unified AI-job status vocabulary.  The
// diagnosis helper only cares about PENDING/RUNNING; task-chat jobs can also
// legitimately arrive here with statuses such as REVERTED.
export type DiagnosisSummaryJobStatus = string

export interface DiagnosisSummaryJobLite {
  id?: string | null
  task_id?: string | null
  status: DiagnosisSummaryJobStatus
  context_json?: Record<string, any> | null
  created_at?: string | null
  started_at?: string | null
}

export const DIAGNOSIS_SUMMARY_JOB_KIND = 'DIAGNOSIS_SUMMARY'

export const isDiagnosisSummaryJob = (job: DiagnosisSummaryJobLite | undefined | null): boolean =>
  Boolean(job && String(job.context_json?.job_kind || '').toUpperCase() === DIAGNOSIS_SUMMARY_JOB_KIND)

/** 一键总结仍在进行中（PENDING/RUNNING 才算，终态/中断不计入加载态）。 */
export const isDiagnosisSummaryActive = (job: DiagnosisSummaryJobLite | undefined | null): boolean =>
  isDiagnosisSummaryJob(job) && (job?.status === 'PENDING' || job?.status === 'RUNNING')

/** 指定任务是否存在进行中的一键总结 job（jobs 支持 Record 或数组两种形态）。 */
export const isDiagnosisSummaryActiveForTask = (
  jobs: Record<string, DiagnosisSummaryJobLite> | DiagnosisSummaryJobLite[],
  taskId: string | undefined | null,
): boolean => {
  if (!taskId) return false
  const list = Array.isArray(jobs) ? jobs : Object.values(jobs)
  return list.some((job) => String(job?.task_id || '') === String(taskId) && isDiagnosisSummaryActive(job))
}

/**
 * 解析当前任务正在进行的总结 job 的发起时刻（毫秒）。
 * 优先 created_at（点击发起时刻），started_at 兜底；跨 session/重新挂载保持不变，
 * 因此「已等待」时长以后端时间为准，不随组件生命周期重置。
 * 无可用时间戳时返回 0（调用方应退化为不显示时长）。
 */
export const resolveDiagnosisSummaryStartedMs = (
  jobs: Record<string, DiagnosisSummaryJobLite> | DiagnosisSummaryJobLite[],
  taskId: string | undefined | null,
): number => {
  const tid = taskId ? String(taskId) : ''
  const list = Array.isArray(jobs) ? jobs : Object.values(jobs)
  for (const job of list) {
    if (!isDiagnosisSummaryActive(job)) continue
    if (tid && String(job?.task_id || '') !== tid) continue
    const iso = job?.created_at || job?.started_at || ''
    if (!iso) return 0
    const t = Date.parse(iso)
    return Number.isFinite(t) ? t : 0
  }
  return 0
}
