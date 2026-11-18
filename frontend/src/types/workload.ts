export type WorkloadLimits = Record<'background' | 'interactive' | 'ongoing', number | null>
export type WorkloadSlot = 'background' | 'interactive' | 'incomplete' | 'uncertain'
export type WorkloadKind = 'reply' | 'check' | 'acceptance' | 'failure' | 'expected_check' | 'paused_check' | 'ongoing' | 'planned'
export type WorkloadItem = {
  id: string
  kind: WorkloadKind
  title: string
  task_id?: string | null
  requirement_id?: string | null
  since?: string | null
  overdue: boolean
}
export type WorkloadExecution = {
  id: string
  task_id: string
  title: string
  slot: WorkloadSlot
  reason: 'running' | 'started' | 'reply' | 'recent_activity' | 'incomplete' | 'uncertain'
  since?: string | null
}
export type MemberWorkload = {
  user_id: string
  display_name: string
  role: string
  avatar_url?: string | null
  limits: WorkloadLimits
  executions: WorkloadExecution[]
  items: WorkloadItem[]
}
export type WorkspaceWorkload = {
  graph_version: number
  as_of: string
  next_evaluate_at: string | null
  can_edit_limits: boolean
  members: MemberWorkload[]
  unassigned: WorkloadItem[]
  observation_gaps: number
}
