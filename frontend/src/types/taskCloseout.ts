export const TASK_CLOSEOUT_OPTIONS = {
  DEVELOPMENT: {
    landing: ['AI_IMPLEMENTED', 'HUMAN_ADJUSTED', 'AI_REWRITTEN', 'AI_REFERENCE_ONLY'],
    failure_stage_options: ['AI_SOLUTION', 'CODING', 'COMPILE', 'PACKAGE', 'DEVICE_TEST', 'INTEGRATION', 'REQUIREMENT_CLARIFICATION', 'OTHER'],
    failure_reason_options: ['AI_DIRECTION_WRONG', 'PROJECT_CONTEXT_INSUFFICIENT', 'COMPILE_ERROR', 'PACKAGE_ERROR', 'DEVICE_TEST_FAILED', 'API_UNCLEAR', 'REQUIREMENT_UNCLEAR', 'ENVIRONMENT_ISSUE', 'OTHER'],
  },
  DIAGNOSIS: {
    landing: ['AI_DIAGNOSED', 'HUMAN_ASSISTED_DIAGNOSIS', 'HUMAN_DIAGNOSED', 'AI_CLUE_ONLY'],
    failure_stage_options: ['INFORMATION_COLLECTION', 'HYPOTHESIS_ANALYSIS', 'REPRODUCTION', 'ROOT_CAUSE_CONFIRMATION', 'FIX_VERIFICATION', 'OTHER'],
    failure_reason_options: ['INSUFFICIENT_EVIDENCE', 'NOT_REPRODUCIBLE', 'HYPOTHESES_REFUTED', 'ROOT_CAUSE_UNCONFIRMED', 'FIX_NOT_VERIFIED', 'ENVIRONMENT_ISSUE', 'OTHER'],
  },
} as const

type CloseoutOptions = typeof TASK_CLOSEOUT_OPTIONS[keyof typeof TASK_CLOSEOUT_OPTIONS]
export type LandingMethod = CloseoutOptions['landing'][number]
export type FailureStage = CloseoutOptions['failure_stage_options'][number]
export type FailureReason = CloseoutOptions['failure_reason_options'][number]

export type CloseoutEvidenceAttachment = {
  filename: string
  source_uri?: string | null
  source_path?: string | null
  source_label?: string | null
  content_type?: string | null
  size?: number | null
}

export type CompleteCloseoutPayload = {
  requirement_id?: string
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
  business_state: 'TASK_IN_PROGRESS' | 'TASK_COMPLETED' | 'TASK_FAILED'
  evidence_ids: string[]
  final_summary_id?: string | null
}
