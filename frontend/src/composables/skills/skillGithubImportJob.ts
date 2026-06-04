import api from '@/utils/api'

export type SkillImportProvisionJob = {
  job_id: string
  job_type: string
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'
  progress: number
  stage: string
  message?: string | null
  error_message?: string | null
  workspace_id?: string | null
  result_json?: {
    skill_id?: string | null
    skill_name?: string | null
    workspace_id?: string | null
    dimension?: string | null
  } | null
}

export type SkillImportWaitResult =
  | { state: 'success'; job: SkillImportProvisionJob; skillId: string }
  | { state: 'failed'; job: SkillImportProvisionJob; message: string }
  | { state: 'timeout'; job: SkillImportProvisionJob | null }

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

const terminalResultFromJob = (job: SkillImportProvisionJob): SkillImportWaitResult | null => {
  if (job.status === 'SUCCESS') {
    const skillId = String(job.result_json?.skill_id || '').trim()
    if (skillId) {
      return { state: 'success', job, skillId }
    }
    return {
      state: 'failed',
      job,
      message: 'Skill import completed without skill_id',
    }
  }
  if (job.status === 'FAILED') {
    return {
      state: 'failed',
      job,
      message: String(job.error_message || job.message || 'Skill import failed'),
    }
  }
  return null
}

export const fetchSkillImportJob = async (jobId: string): Promise<SkillImportProvisionJob> => {
  const normalizedJobId = String(jobId || '').trim()
  const res = await api.get<SkillImportProvisionJob>(`/provision-jobs/${normalizedJobId}`)
  return res.data
}

export const waitForSkillImportJob = async (
  jobId: string,
  {
    timeoutMs = 8500,
    intervalMs = 1000,
  }: {
    timeoutMs?: number
    intervalMs?: number
  } = {},
): Promise<SkillImportWaitResult> => {
  const normalizedJobId = String(jobId || '').trim()
  if (!normalizedJobId) {
    return { state: 'timeout', job: null }
  }

  const deadlineAt = Date.now() + Math.max(0, timeoutMs)
  let lastJob: SkillImportProvisionJob | null = null
  while (true) {
    lastJob = await fetchSkillImportJob(normalizedJobId)
    const terminalResult = terminalResultFromJob(lastJob)
    if (terminalResult) return terminalResult

    const remainingMs = deadlineAt - Date.now()
    if (remainingMs <= 0) {
      return { state: 'timeout', job: lastJob }
    }
    await sleep(Math.min(Math.max(1, intervalMs), remainingMs))
  }
}
