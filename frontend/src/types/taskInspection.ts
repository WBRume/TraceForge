export interface GitCommitInfo {
  sha: string
  author_name: string
  author_email: string
  authored_at: string
  committer_name: string
  committer_email: string
  committed_at: string
  message: string
}

export interface TaskRepositoryDetail {
  id: string
  repository_id: string | null
  repo_name: string
  repo_url: string
  branch_name: string | null
  task_branch: string | null
  rel_path: string
  worktree_path: string | null
  state: string
  error_message: string | null
  base_commit_sha: string | null
  base_commit: GitCommitInfo | null
}

export interface TaskInspection {
  task: {
    id: string
    name: string
    description: string | null
    status: string
    task_type: string
    creator_id: string
    creator_name: string | null
    execution_location: string
    created_at: string
  }
  project_path: string | null
  repositories: TaskRepositoryDetail[]
}
