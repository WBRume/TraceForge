export type CollaborationFile = { path: string; sha256: string; size: number; mode: '100644' | '100755' | '120000' }
export type CollaborationHumanChange = {
  id: string; delta_id: string | null; actor_name: string | null; submission_id: string | null
  created_at: string; changed_files_count: number; repository_count: number
}
export type CollaborationHumanChangePage = { items: CollaborationHumanChange[]; total: number; page: number; page_size: number }
export type CollaborationHumanChangeDetail = {
  id: string; base_snapshot_id: string; input_snapshot_id: string; created_at: string
  files: Array<{ task_repository_id: string; repo_slug: string; branch_name: string; path: string; before: CollaborationFile | null; after: CollaborationFile | null }>
}
export type CollaborationRepository = {
  task_repository_id: string; repository_id: string; repo_url: string; repo_slug: string
  rel_path: string; branch_name: string; base_commit_sha: string; files: CollaborationFile[]; deleted?: string[]
}
export type CollaborationManifest = {
  protocol_version: 1; snapshot_id: string; task_id: string; workspace_revision: number
  session_generation: number; session_revision: number; repository_set_digest: string
  source: string; repositories: CollaborationRepository[]
  session_turn_id?: string; turn_index?: number; turn_title?: string; turn_created_at?: string
  delta?: { base_snapshot_id: string }
}
export type CollaborationConflict = {
  task_repository_id: string; path: string; local_sha256?: string | null
  expected_sha256?: string | null; cloud_sha256?: string | null
  local?: CollaborationFile | null; base?: CollaborationFile | null; cloud?: CollaborationFile | null; reason?: string
}
export type CollaborationState = {
  capabilities?: { manifest_delta?: number }
  input_mode?: 'LOCAL' | 'CLOUD'
  enabled: boolean; sync_phase: string; state_version: number; workspace_revision: number
  snapshot_id: string | null; input_snapshot_id: string | null; progress_snapshot_id: string | null
  lease_epoch: number; lease_expires_at?: string; driver_user_id?: string
  driver_client_id?: string; driver_instance_id?: string; binding_id: string
  client_id?: string; instance_id?: string; pending_submission_id?: string | null; input_submission_id?: string | null
  recovery_kind?: string | null; recovery_message?: string | null; driver_connected?: boolean
  recovery_operation_id?: string | null
  session_generation: number; session_revision: number; repository_set_digest: string
  repositories: CollaborationRepository[]; conflicts: CollaborationConflict[]
  preparation?: { submission_id: string; operation_id: string } | null
  progress_seq?: number; progress_epoch?: string; final_progress_seq?: number
}
export type LocalCollaborationStatus = {
  released?: boolean; suspended?: boolean
  directory_mode?: 'MAPPED'
  transport?: { token: string; base_token?: string; bases?: Record<string, string> }
  task_id: string; binding_id?: string; task_root?: string
  repositories?: Array<CollaborationRepository & { local_worktree_path: string; mapped_repo_root: string }>
  manifest?: CollaborationManifest; baseline?: CollaborationManifest; target?: CollaborationManifest
  received?: CollaborationManifest
  conflict_set_id?: string; conflicts?: CollaborationConflict[]
  preview_conflicts?: CollaborationConflict[]
  local_changes?: Array<{ task_repository_id: string; path: string; base: CollaborationFile | null; local: CollaborationFile | null }>
  state?: string; errors?: string[]
  workspace_root?: string; applied_snapshot_id?: string
}
export type CollaborationCapture = {
  manifest: CollaborationManifest; objects: Array<{ sha256: string; content: string }>; status: LocalCollaborationStatus; input_cut_seq?: number
}
export type CollaborationBackup = {
  operation_id: string; task_repository_id: string; path: string; sha256: string | null; state: string; backup_path: string | null
  created_at?: string
  context?: {
    task_id: string; snapshot_id: string; workspace_revision: number; session_generation: number; session_revision: number
    session_turn_id?: string; turn_index?: number; turn_title?: string; turn_created_at?: string; source: string; kind: 'receive' | 'restore'
    repo_slug: string; branch_name: string
  }
}
export type CollaborationMappingCheck = {
  task_repository_id: string; local_path: string; expected_head: string; local_head?: string; local_branch?: string
  clean?: boolean; changes: string[]; errors: string[]
}
