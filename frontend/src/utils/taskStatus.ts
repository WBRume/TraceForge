export const TASK_STATUSES = [
  'INITIALIZED', 'RUNNING', 'ROUND_COMPLETED', 'AWAITING_INPUT', 'INTERRUPTED', 'COMPLETED', 'FAILED',
] as const
export type TaskStatus = typeof TASK_STATUSES[number] | 'PROVISIONING'

export function normalizeTaskStatus(status: unknown): string {
  return String(status || '').toUpperCase()
}

export function taskStatusKey(status: unknown): string {
  const value = normalizeTaskStatus(status)
  return `chat.status.${[...TASK_STATUSES, 'PROVISIONING'].includes(value as TaskStatus) ? value : 'UNKNOWN'}`
}

export function isTerminalTaskStatus(status: unknown): boolean {
  return ['COMPLETED', 'FAILED'].includes(normalizeTaskStatus(status))
}

export function isActiveTaskStatus(status: unknown): boolean {
  return ['RUNNING', 'AWAITING_INPUT'].includes(normalizeTaskStatus(status))
}
