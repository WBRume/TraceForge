import type { RequirementEditableStatus } from '@/types/workspaceAssets'

export const editableRequirementStatuses: readonly RequirementEditableStatus[] = [
  'DRAFT', 'READY', 'IN_PROGRESS', 'ARCHIVED', 'ACTIVE', 'WAITING_SOURCE',
]

export const requirementStatuses = [
  ...editableRequirementStatuses, 'PENDING_ACCEPTANCE', 'VERIFIED', 'REJECTED',
]

export function canSubmitRequirementAcceptance(status: string) {
  return ['DRAFT', 'READY', 'IN_PROGRESS', 'ACTIVE', 'REJECTED'].includes(status)
}

export function requirementStatusKey(status: string) {
  return 'workspace_assets.requirements.status_labels.' +
    (requirementStatuses.includes(status) ? status : 'unknown')
}

export function requirementCoverageKey(status?: string) {
  const labels = ['not_available', 'waiting_evidence', 'waiting_human_confirmation', 'verified']
  return `workspace_assets.task_detail.coverage_status.${status && labels.includes(status) ? status : 'not_available'}`
}
