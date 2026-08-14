export type AgentTask = {
  id: string
  workspace_id: string
  creator_id: string
  name: string
  description?: string | null
  git_repo_url?: string | null
  status: string
  current_phase?: string | null
  error_message?: string | null
  created_at: string
  updated_at?: string | null
  latest_change_proposal_id?: string | null
}

export type AgentTaskListResponse = {
  items: AgentTask[]
  total: number
  page: number
  page_size: number
}

export type ChangeProposalRepo = {
  id: string
  proposal_id: string
  repository_id?: string | null
  repo_url?: string | null
  repo_name: string
  repo_slug: string
  base_branch: string
  base_commit_sha: string
  cloud_task_branch: string
  cloud_head_sha?: string | null
  changed_files_count: number
  insertions: number
  deletions: number
  patch_asset_id?: string | null
  patch_asset_version_id?: string | null
  created_at: string
}

export type ChangeProposalRepoPatch = ChangeProposalRepo & {
  patch_text: string
}

export type ChangeProposalRepoPatchListResponse = {
  proposal_id: string
  items: ChangeProposalRepoPatch[]
  total: number
}

export type ChangeProposal = {
  id: string
  task_id: string
  workspace_id: string
  proposal_no: number
  patch_set_no: number
  status: string
  base_repo_url?: string | null
  base_branch: string
  base_commit_sha: string
  cloud_task_branch: string
  cloud_head_sha?: string | null
  changed_files_count: number
  insertions: number
  deletions: number
  summary?: string | null
  risk_notes?: string | null
  patch_asset_id?: string | null
  patch_asset_version_id?: string | null
  repositories?: ChangeProposalRepo[]
  created_at: string
  updated_at?: string | null
}

export type ChangeProposalFile = {
  id: string
  proposal_id: string
  file_path: string
  old_path?: string | null
  new_path?: string | null
  repository_id?: string | null
  proposal_repo_id?: string | null
  change_type: 'added' | 'modified' | 'deleted' | 'renamed' | string
  insertions: number
  deletions: number
  diff_excerpt?: string | null
  is_binary: boolean
  created_at: string
}

export type ChangeProposalFileListResponse = {
  items: ChangeProposalFile[]
  total: number
}

export type ApplyResultStatus = 'applied' | 'conflict' | 'rejected'

export type VerificationRunStatus = 'running' | 'success' | 'failed' | 'conflict' | 'cancelled'

export type VerificationRun = {
  id: string
  task_id: string
  workspace_id: string
  proposal_id: string
  user_id: string
  agent_id?: string | null
  machine_name?: string | null
  os_name?: string | null
  command?: string | null
  status: VerificationRunStatus | string
  duration_ms?: number | null
  base_commit_sha: string
  local_head_sha?: string | null
  log_excerpt?: string | null
  log_asset_id?: string | null
  log_asset_version_id?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at: string
}

export type ConflictReport = {
  id: string
  task_id: string
  workspace_id: string
  proposal_id: string
  user_id: string
  agent_id?: string | null
  machine_name?: string | null
  base_commit_sha: string
  local_head_sha?: string | null
  conflicted_files_json?: unknown
  git_apply_stderr?: string | null
  conflict_excerpt?: string | null
  report_asset_id?: string | null
  report_asset_version_id?: string | null
  created_at: string
}
