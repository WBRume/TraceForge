export type LandingMethod =
  | 'AI_IMPLEMENTED'
  | 'HUMAN_ADJUSTED'
  | 'AI_REWRITTEN'
  | 'AI_REFERENCE_ONLY'

export type FailureStage =
  | 'AI_SOLUTION'
  | 'CODING'
  | 'COMPILE'
  | 'PACKAGE'
  | 'DEVICE_TEST'
  | 'INTEGRATION'
  | 'REQUIREMENT_CLARIFICATION'
  | 'OTHER'

export type FailureReason =
  | 'AI_DIRECTION_WRONG'
  | 'PROJECT_CONTEXT_INSUFFICIENT'
  | 'COMPILE_ERROR'
  | 'PACKAGE_ERROR'
  | 'DEVICE_TEST_FAILED'
  | 'API_UNCLEAR'
  | 'REQUIREMENT_UNCLEAR'
  | 'ENVIRONMENT_ISSUE'
  | 'OTHER'

export type CloseoutEvidenceAttachment = {
  filename: string
  source_uri?: string | null
  source_path?: string | null
  source_label?: string | null
  content_type?: string | null
  size?: number | null
}

export type CompleteCloseoutPayload = {
  completion_summary: string
  landing_method: LandingMethod
  commit_id?: string | null
  pr_url?: string | null
  local_ref?: string | null
  evidence_attachments: CloseoutEvidenceAttachment[]
}

export type FailCloseoutPayload = {
  failure_stage: FailureStage
  failure_reason: FailureReason
  failure_summary: string
  evidence_attachments: CloseoutEvidenceAttachment[]
}

export type TaskCloseoutResponse = {
  task_id: string
  workspace_id: string
  status: string
  evidence_ids: string[]
  final_summary_id?: string | null
}
