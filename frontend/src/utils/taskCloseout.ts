import { TASK_CLOSEOUT_OPTIONS } from '@/types/taskCloseout'

export type CloseoutOptionKind = keyof typeof TASK_CLOSEOUT_OPTIONS.DEVELOPMENT

export function getCloseoutOptions(taskType?: string) {
  return TASK_CLOSEOUT_OPTIONS[taskType === 'DIAGNOSIS' ? 'DIAGNOSIS' : 'DEVELOPMENT']
}

export function isDiagnosisLandingMethod(value?: string): boolean {
  return (TASK_CLOSEOUT_OPTIONS.DIAGNOSIS.landing as readonly string[]).includes(value || '')
}

/** Resolve saved values as well as form options, preserving historical development labels. */
export function closeoutOptionLabelKey(kind: CloseoutOptionKind, value: string): string | null {
  if ((TASK_CLOSEOUT_OPTIONS.DEVELOPMENT[kind] as readonly string[]).includes(value)) {
    return `chat.closeout.${kind}.${value.toLowerCase()}`
  }
  if ((TASK_CLOSEOUT_OPTIONS.DIAGNOSIS[kind] as readonly string[]).includes(value)) {
    return `chat.closeout.diagnosis.${kind}.${value.toLowerCase()}`
  }
  return null
}
