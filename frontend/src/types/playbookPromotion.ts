import type { RequirementPreviewJob } from './workspaceAssets'
export interface PromotionCandidate {
  title: string
  source_case_ids: string[]
  symptoms: string[]
  summary: string
  steps: string[]
}
export interface PromotionDraft { playbooks: PromotionCandidate[]; grouping_reason: string }
export type PromotionJob = RequirementPreviewJob & {
  cases?: { id: string; title: string }[]
  result?: {
    review_state?: 'PENDING' | 'CONFIRMED' | 'DISCARDED'
    draft_revision?: string
    draft?: PromotionDraft
    spec_ids?: string[]
    replacement_job_id?: string
  }
}
