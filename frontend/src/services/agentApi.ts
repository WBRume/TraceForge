import api from '@/utils/api'
import type {
  AgentTask,
  AgentTaskListResponse,
  ApplyResultStatus,
  ChangeProposal,
  ChangeProposalFileListResponse,
  ChangeProposalRepoPatchListResponse,
  ConflictReport,
  VerificationRun,
  VerificationRunStatus,
} from '@/types/agent'

const CHANGE_PROPOSAL_GENERATE_TIMEOUT_MS = 180_000

export const listAgentTasks = async (page = 1, pageSize = 50): Promise<AgentTaskListResponse> => {
  const res = await api.get('/agent/tasks', {
    params: { page, page_size: pageSize },
  })
  return res.data as AgentTaskListResponse
}

export const getAgentTask = async (taskId: string): Promise<AgentTask> => {
  const res = await api.get(`/agent/tasks/${taskId}`)
  return res.data as AgentTask
}

export const getLatestChangeProposal = async (taskId: string): Promise<ChangeProposal | null> => {
  const res = await api.get(`/agent/tasks/${taskId}/change-proposals/latest`)
  if (!res.data) return null
  return res.data as ChangeProposal
}

export const getChangeProposal = async (proposalId: string): Promise<ChangeProposal> => {
  const res = await api.get(`/agent/change-proposals/${proposalId}`)
  return res.data as ChangeProposal
}

export const createTaskChangeProposal = async (payload: {
  workspaceId: string
  taskId: string
  summary?: string | null
  riskNotes?: string | null
}): Promise<ChangeProposal> => {
  const res = await api.post(
    `/workspaces/${payload.workspaceId}/tasks/${payload.taskId}/change-proposals`,
    {
      summary: payload.summary || undefined,
      risk_notes: payload.riskNotes || undefined,
    },
    {
      timeout: CHANGE_PROPOSAL_GENERATE_TIMEOUT_MS,
    },
  )
  return res.data as ChangeProposal
}

export const downloadChangeProposalPatch = async (proposalId: string): Promise<string> => {
  const res = await api.get(`/agent/change-proposals/${proposalId}/patch`, {
    responseType: 'text',
    transformResponse: [(data) => data],
  })
  return String(res.data || '')
}

export const listChangeProposalRepoPatches = async (proposalId: string): Promise<ChangeProposalRepoPatchListResponse> => {
  const res = await api.get(`/agent/change-proposals/${proposalId}/repo-patches`)
  return res.data as ChangeProposalRepoPatchListResponse
}

export const listChangeProposalFiles = async (proposalId: string): Promise<ChangeProposalFileListResponse> => {
  const res = await api.get(`/agent/change-proposals/${proposalId}/files`)
  return res.data as ChangeProposalFileListResponse
}

export const submitApplyResult = async (payload: {
  taskId: string
  proposalId: string
  status: ApplyResultStatus
  baseCommitSha: string
  localHeadSha?: string | null
  message?: string | null
}) => {
  const res = await api.post(`/agent/tasks/${payload.taskId}/apply-results`, {
    proposal_id: payload.proposalId,
    status: payload.status,
    base_commit_sha: payload.baseCommitSha,
    local_head_sha: payload.localHeadSha || undefined,
    agent_id: 'sdd-desktop',
    message: payload.message || undefined,
  })
  return res.data as { proposal_id: string; status: string }
}

export const createVerificationRun = async (payload: {
  taskId: string
  proposalId: string
  command: string
  status: VerificationRunStatus
  durationMs: number
  baseCommitSha: string
  localHeadSha?: string | null
  logExcerpt?: string | null
  startedAt: string
  finishedAt: string
  osName?: string | null
}): Promise<VerificationRun> => {
  const res = await api.post(`/agent/tasks/${payload.taskId}/verification-runs`, {
    proposal_id: payload.proposalId,
    agent_id: 'sdd-desktop',
    machine_name: 'local-desktop',
    os_name: payload.osName || undefined,
    command: payload.command,
    status: payload.status,
    duration_ms: payload.durationMs,
    base_commit_sha: payload.baseCommitSha,
    local_head_sha: payload.localHeadSha || undefined,
    log_excerpt: payload.logExcerpt || undefined,
    started_at: payload.startedAt,
    finished_at: payload.finishedAt,
  })
  return res.data as VerificationRun
}

export const uploadVerificationLog = async (payload: {
  taskId: string
  runId: string
  logText: string
  logExcerpt?: string | null
}): Promise<VerificationRun> => {
  const form = new FormData()
  form.append('file', new Blob([payload.logText], { type: 'text/plain' }), `verification-${payload.runId}.log`)
  if (payload.logExcerpt) {
    form.append('log_excerpt', payload.logExcerpt)
  }
  const res = await api.post(`/agent/tasks/${payload.taskId}/verification-runs/${payload.runId}/logs`, form)
  return res.data as VerificationRun
}

export const createConflictReport = async (payload: {
  taskId: string
  proposalId: string
  baseCommitSha: string
  localHeadSha?: string | null
  conflictedFiles: string[]
  gitApplyStderr: string
  conflictExcerpt: string
}): Promise<ConflictReport> => {
  const form = new FormData()
  form.append('proposal_id', payload.proposalId)
  form.append('agent_id', 'sdd-desktop')
  form.append('machine_name', 'local-desktop')
  form.append('base_commit_sha', payload.baseCommitSha)
  if (payload.localHeadSha) {
    form.append('local_head_sha', payload.localHeadSha)
  }
  form.append('conflicted_files_json', JSON.stringify(payload.conflictedFiles))
  form.append('git_apply_stderr', payload.gitApplyStderr)
  form.append('conflict_excerpt', payload.conflictExcerpt)
  form.append(
    'file',
    new Blob([payload.conflictExcerpt], { type: 'text/plain' }),
    `conflict-${payload.proposalId}.log`,
  )
  const res = await api.post(`/agent/tasks/${payload.taskId}/conflict-reports`, form)
  return res.data as ConflictReport
}
