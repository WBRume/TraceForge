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
type WorkloadMember = {
  user_id: string
  display_name: string
  role: string
  avatar_url?: string | null
  limits: WorkloadLimits
}
export type WorkloadDetails = {
  executions: WorkloadExecution[]
  items: WorkloadItem[]
}
export type MemberWorkload = WorkloadMember & WorkloadDetails
export type WorkloadCounts = {
  slots: Partial<Record<WorkloadSlot, number>>
  items: Partial<Record<WorkloadKind, number>>
  overdue: number
}
export type WorkloadSource = {
  workspace_id: string
  workspace_name: string
  counts: WorkloadCounts
  details: WorkloadDetails | null
}
export type MemberWorkloadOverview = WorkloadMember & {
  counts: WorkloadCounts
  sources: WorkloadSource[]
}
type WorkloadSnapshot = {
  graph_version: number
  as_of: string
  next_evaluate_at: string | null
  can_edit_limits: boolean
  unassigned: WorkloadItem[]
  observation_gaps: number
}
export type WorkspaceWorkload = WorkloadSnapshot & { members: MemberWorkload[] }
export type WorkspaceMemberWorkload = WorkloadSnapshot & { members: MemberWorkloadOverview[] }
