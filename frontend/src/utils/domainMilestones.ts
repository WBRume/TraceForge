export type DomainMilestone = {
  run_id: string
  call_id: string
  sequence: number
  tool: string
  stage: 'started' | 'validating' | 'repairing' | 'accepted' | 'persisted' | 'failed'
  message: string
  timestamp: number
  issues: string[]
}

const stages = new Set(['started', 'validating', 'repairing', 'accepted', 'persisted', 'failed'])

export function domainMilestones(value: unknown): DomainMilestone[] {
  if (!Array.isArray(value)) return []
  const events = new Map<string, DomainMilestone>()
  for (const item of value) {
    if (!item || typeof item !== 'object' || typeof item.run_id !== 'string'
      || typeof item.message !== 'string' || !Number.isInteger(item.sequence) || item.sequence < 1
      || typeof item.tool !== 'string' || typeof item.call_id !== 'string'
      || typeof item.timestamp !== 'number' || !Number.isFinite(item.timestamp) || !stages.has(item.stage)) continue
    events.set(`${item.run_id}:${item.sequence}`, {
      ...item, issues: Array.isArray(item.issues) ? item.issues.filter((v: unknown) => typeof v === 'string') : [],
    })
  }
  return [...events.values()].sort((a, b) => a.timestamp - b.timestamp || a.sequence - b.sequence)
}
