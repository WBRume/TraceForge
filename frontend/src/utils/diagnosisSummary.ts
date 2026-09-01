/**
 * 「一键总结问题案例」后台 job 的判定工具（纯函数，便于单测）。
 * 数据来源：TASK_CHAT 频道的 AI job（status + context_json.job_kind）。
 */

// Keep this boundary open to the unified AI-job status vocabulary.  The
// diagnosis helper only cares about PENDING/RUNNING; task-chat jobs can also
// legitimately arrive here with statuses such as REVERTED.
export type DiagnosisSummaryJobStatus = string

export interface DiagnosisSummaryJobLite {
  task_id?: string | null
  status: DiagnosisSummaryJobStatus
  context_json?: Record<string, any> | null
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
