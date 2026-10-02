export interface RequirementOption {
  id: string
  title: string
  status: string
  source_ref?: string | null
  parent_requirement_id?: string | null
  parent_title?: string | null
  child_count?: number
  can_link_task?: boolean
}

export type TaskRailView = 'all' | 'following' | 'independent' | 'requirement'

export function requirementLabel(requirement: RequirementOption): string {
  return requirement.title
}

export function requirementMark(requirement: RequirementOption): string {
  return Array.from(requirement.title.trim()).slice(0, 2).join('')
}
