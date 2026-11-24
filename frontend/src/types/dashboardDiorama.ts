export interface DioramaFileItem {
  path: string
  name: string
  loc: number
  lang: string
  commits: number
  added: number
  deleted: number
  last_date: string
  is_aggregate: boolean
  file_count: number
}

export interface DioramaCommitItem {
  hash: string
  date: string
  subject: string
  added: number
  deleted: number
  modules: string[]
}

export interface DioramaModuleItem {
  id: string
  repo_id: string
  name: string
  loc: number
  file_count: number
  commits: number
  added: number
  deleted: number
  recent_commits: DioramaCommitItem[]
  files: DioramaFileItem[]
}

export interface DioramaRepoItem {
  id: string
  name: string
  slug: string
  branch: string
  state: string
  color: string
  loc: number
  file_count: number
  module_count: number
  available: boolean
  modules: DioramaModuleItem[]
}

export interface DioramaMemberItem {
  id: string
  display_name: string
  email?: string | null
  avatar_url?: string | null
  avatar_svg?: string | null
  role: string
  color: string
}

export interface DioramaTaskItem {
  id: string
  name: string
  status: string
  interrupt_kind?: string | null
  task_type: string
  creator_id: string
  creator_name?: string | null
  requirement_ids: string[]
  requirement_titles: string[]
  repos: string[]
  modules: string[]
  primary_modules: string[]
  files: string[]
  added: number
  deleted: number
  updated_at?: string | null
}

export interface DioramaDayHeat {
  commits: number
  added: number
  deleted: number
}

export interface DioramaTimelineDay {
  date: string
  commit_count: number
  total_churn: number
  commits: DioramaCommitItem[]
  module_heat: Record<string, DioramaDayHeat>
  repo_heat?: Record<string, DioramaDayHeat>
}

export interface DioramaPeriod {
  days: number
  date_range: string[]
  total_loc: number
  total_files: number
  total_modules: number
  total_commits: number
  repos: DioramaRepoItem[]
  tasks: DioramaTaskItem[]
  timeline: DioramaTimelineDay[]
}

export interface DashboardDioramaPayload extends DioramaPeriod {
  workspace_id: string
  workspace_name: string
  members: DioramaMemberItem[]
  generated_at: string
}

export interface DashboardDioramaResponse extends DashboardDioramaPayload {
  windows?: Partial<Record<DioramaDays, DioramaPeriod>>
}

export type DioramaDays = 14 | 30 | 60
export type DioramaMetric = 'heat' | 'loc' | 'impact'
export type DioramaIsoMode = '3d' | 'top'
export type DioramaWindowMode = 'cumulative' | 'day'

export interface DioramaHit {
  kind: 'repo' | 'module'
  id: string
  repo: DioramaRepoItem
  module?: DioramaModuleItem
}

export interface DioramaDrillState {
  repo: DioramaRepoItem
  module: DioramaModuleItem | null
}

export interface DioramaModuleHeatStats {
  commits: number
  added: number
  deleted: number
  score: number
}

export interface DioramaSearchEntry {
  kind: 'module' | 'file'
  moduleId: string
  name: string
  path: string
  loc: number
  commits: number
}
