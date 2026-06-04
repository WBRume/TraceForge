export type SkillRuntimeEventType =
  | 'ENTRY_READ'
  | 'FILE_READ'
  | 'DIR_LIST'
  | 'FILE_SEARCH'
  | 'SCRIPT_EXEC'
  | 'FILE_WRITE'
  | 'TOOL_RESULT'
  | 'USAGE_CONFIRMED'

export type SkillRuntimeEvidenceLevel = 'EXACT_PATH' | 'COMMAND_PATH' | 'RESULT_LINKED'

export type SkillRuntimeEvent = {
  id: string
  workspace_id: string
  task_id: string
  skill_id?: string | null
  ai_job_id?: string | null
  tool_use_id?: string | null
  event_type: SkillRuntimeEventType
  evidence_level: SkillRuntimeEvidenceLevel
  materialized_dir?: string | null
  matched_path?: string | null
  relative_path?: string | null
  tool_name?: string | null
  tool_input_json?: unknown
  tool_result_preview?: string | null
  status: string
  confidence: number
  created_at: string
}
