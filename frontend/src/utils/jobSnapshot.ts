export type VersionedJob = { version?: number; attempt_count?: number; status?: string }

export const isJobTerminal = (status?: string): boolean =>
  ['SUCCESS', 'FAILED', 'CANCELLED', 'REVERTED'].includes(status || '')

export const acceptsJobSnapshot = (current: VersionedJob | undefined | null, incoming: VersionedJob): boolean => {
  if (!current) return true
  if (current.version != null || incoming.version != null) {
    return (incoming.version ?? 0) > (current.version ?? 0)
  }
  return !isJobTerminal(current.status)
}
