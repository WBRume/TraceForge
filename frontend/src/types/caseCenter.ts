export interface CaseListFilters {
  keyword: string
  category: string
  status: string
  priority: string
  product_name: string
  product_version: string
  site_name: string
  creator_name: string
  created_from: string
  created_to: string
  has_playbook: 'ALL' | 'true' | 'false'
  sort_by: 'updated_at' | 'created_at' | 'priority' | 'title'
  sort_order: 'asc' | 'desc'
}

export type CaseSort = Pick<CaseListFilters, 'sort_by' | 'sort_order'>

export const createCaseListFilters = (): CaseListFilters => ({
  keyword: '', category: 'ALL', status: 'ALL', priority: 'ALL',
  product_name: '', product_version: '', site_name: '', creator_name: '',
  created_from: '', created_to: '', has_playbook: 'ALL',
  sort_by: 'updated_at', sort_order: 'desc',
})
export interface CaseListItem {
  id: string
  workspace_id: string
  title: string
  problem_description?: string | null
  category: string
  priority: string
  status: string
  product_name?: string | null
  product_version?: string | null
  site_name?: string | null
  workspace_name?: string | null
  source_task_name?: string | null
  creator_name?: string | null
  my_can_manage: boolean
  has_playbook: boolean
  review_round: number
  created_at: string
  updated_at?: string | null
}

