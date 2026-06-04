export type SkillAnalysisStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'
export type SkillAnalysisRefKind = 'WORKTREE' | 'LATEST' | 'VERSION'
export type SkillAnalysisLevel = 'LOW' | 'MEDIUM' | 'HIGH'

export type SkillAnalysisKeyFile = {
  path: string
  role?: string
  risk_level?: SkillAnalysisLevel
  size?: number
  [key: string]: unknown
}

export type SkillAnalysisRiskItem = {
  id?: string
  risk_type: string
  risk_level: SkillAnalysisLevel
  file_path: string
  line_start?: number | null
  line_end?: number | null
  title?: string
  description?: string
  evidence_summary?: string
  evidence_detail?: string
  matched_text?: string
  recommendation?: string
  source?: string
  confidence?: number
  [key: string]: unknown
}

export type SkillAnalysis = {
  id: string
  workspace_id: string
  skill_id: string
  version_id?: string | null
  commit_sha?: string | null
  ref_kind: SkillAnalysisRefKind
  status: SkillAnalysisStatus
  progress: number
  message?: string | null
  error_message?: string | null
  risk_level?: SkillAnalysisLevel | null
  complexity?: SkillAnalysisLevel | null
  review_priority?: SkillAnalysisLevel | null
  file_stats: Record<string, unknown>
  file_type_distribution: Record<string, number>
  key_files: SkillAnalysisKeyFile[]
  risk_items: SkillAnalysisRiskItem[]
  review_suggestions: string[]
  created_by_id: string
  started_at?: string | null
  finished_at?: string | null
  created_at: string
  updated_at?: string | null
}
