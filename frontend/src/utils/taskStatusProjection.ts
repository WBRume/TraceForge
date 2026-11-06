import { TASK_STATUSES } from './taskStatus'

export type TaskStatusSnapshot = {
  task_id: string
  status: string
  status_seq: string | number
  session_generation?: number
  session_revision?: number
}

function sequence(value: unknown): bigint | null {
  if (typeof value === 'number' && (!Number.isSafeInteger(value) || value < 0)) return null
  if (!/^(0|[1-9]\d*)$/.test(String(value))) return null
  return BigInt(String(value))
}

/** The only task status mutation on the client: apply a server snapshot by version. */
export function applyTaskStatusSnapshot(target: any, payload: unknown): boolean {
  if (!target || !payload || typeof payload !== 'object') return false
  const snapshot = payload as TaskStatusSnapshot
  if (snapshot.task_id !== target.id) return false
  if (![...TASK_STATUSES, 'PROVISIONING'].includes(snapshot.status as any)) return false
  const next = sequence(snapshot.status_seq)
  const current = sequence(target.status_seq)
  if (next === null || (current !== null && next <= current)) return false
  target.status = snapshot.status
  target.status_seq = String(snapshot.status_seq)
  return true
}

/** REST/list refreshes use the same version fence as WebSocket delivery. */
export function mergeTaskSnapshot(target: any, payload: Record<string, any>): void {
  const { status, status_seq, session_generation, session_revision, ...other } = payload
  Object.assign(target, other)
  if (applyTaskStatusSnapshot(target, { task_id: target.id, status, status_seq })) {
    if (Number.isSafeInteger(session_generation)) target.session_generation = session_generation
    if (Number.isSafeInteger(session_revision)) target.session_revision = session_revision
  }
}
