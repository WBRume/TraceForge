export interface PlaybookHypothesis {
  id: string
  claim: string
  predictions: string[]
  falsifiers: string[]
  state: string
  reason?: string
}
export interface GuideObservation { reference: string; observation: string }
export interface GuideHypothesis {
  id: string; claim: string; prediction: string; falsifier: string
  evidence: GuideObservation[]; state: 'PROPOSED' | 'APPROVED' | 'EXCLUDED'; decided_by?: string
  verdict?: 'UNTESTED' | 'SUPPORTED' | 'REFUTED' | 'INCONCLUSIVE'
  verdict_reason?: string
}
export interface GuideReport {
  phase: string; findings: string; evidence: GuideObservation[]; code: string; language: string
  outcome: 'NOT_RUN' | 'OBSERVED' | 'FAILED'; ready_for_review: boolean; job_id: string
}
export interface GuideSession {
  task_id: string; version: number; session_generation: number; active_phase: string; completed: boolean
  guide: { title: string; version: string; context: Record<string, unknown>; steps: { id: string; objective: string }[] }
  reports: Record<string, GuideReport>; hypotheses: GuideHypothesis[]
  confirmations: Record<string, { user_id: string; report_digest: string }>; error: string | null
  auto_run?: boolean; auto_pause_reason?: string | null
}
export interface PlaybookRun {
  id: string
  task_id: string
  workspace_id?: string
  run_epoch: number
  state_version: number
  event_seq: number
  phase: string
  state: string
  active_step: string
  title: string
  spec_version: string
  enforcement?: string
  missing_facts?: string[]
  case_candidates?: { id: string; title: string }[]
  stages: { id: string; phase: string; objective: string }[]
  hypotheses: PlaybookHypothesis[]
  gate_decisions: { step_id: string; run_epoch: number; verdict: string; execution_id: string }[]
  evidence: EvidenceReceipt[]
  projection?: { case_id: string; revision_id: string }
}
export interface EvidenceReceipt {
  execution_id: string
  exit_code: number
  termination: string
  timed_out: boolean
  receipt_digest: string
  facts: Record<string, unknown>
  argv: string[]
  step_id?: string
  run_epoch?: number
  artifacts?: { name: string; digest: string; size: number }[]
}
export interface PlaybookSpec {
  workspace_id?: string
  execution_mode?: 'ANALYSIS_GUIDE' | 'PHYSICAL_VERIFICATION'
  spec_key?: string
  id: string
  title: string
  version: string
  validation_state: string
  inputs: Record<string, { type: string; required?: boolean; default?: unknown }>
  match: { symptoms?: string[]; requiredFacts?: Record<string, unknown> }
  environment?: { allowAdvisory?: boolean }
  source_case_refs?: string[]
  statistics?: { run_count: number; sampled_runs: number; physical_runs: number; verified_runs: number; physical_pass_rate: number | null; average_verified_duration_seconds: number | null }
}
