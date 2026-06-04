import type {
  RequirementImportConfirmItem,
  RequirementMutationPayload,
} from '@/types/workspaceAssets'

export type RequirementCreateStep = 'method' | 'manual' | 'file' | 'source_link' | 'preview'
export type RequirementReturnStep = 'manual' | 'file'

export type RequirementDirectImportPayload = {
  file?: File | null
  text?: string | null
  source_kind?: string | null
  source_uri?: string | null
  source_ref?: string | null
  change_reason?: string | null
}

export type RequirementPreviewPayload = {
  file?: File | null
  text?: string | null
  source_kind?: string | null
  source_uri?: string | null
  source_ref?: string | null
}

export type RequirementManualPayload = RequirementMutationPayload

export type RequirementPreviewConfirmPayload = {
  items: RequirementImportConfirmItem[]
  change_reason?: string | null
}

export type EditableRequirementPreviewItem = RequirementImportConfirmItem & {
  originalTitle: string
  task_prompt?: string | null
}
