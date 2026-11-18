import type { WorkloadCounts, WorkloadDetails, WorkloadKind } from '@/types/workload'

export const pendingKinds: WorkloadKind[] = ['reply', 'check', 'acceptance', 'failure']

export function countsFromSummary(summary: WorkloadCounts) {
  const items = (kind: WorkloadKind) => summary.items[kind] ?? 0
  const { background = 0, interactive = 0, incomplete = 0, uncertain = 0 } = summary.slots
  const pendingByKind = pendingKinds.map(kind => ({ kind, count: items(kind) })).filter(item => item.count > 0)
  return {
    pending: pendingByKind.reduce((total, item) => total + item.count, 0),
    overdue: summary.overdue,
    background,
    interactive,
    incomplete,
    uncertain,
    active: background + interactive + incomplete,
    expected: items('expected_check'),
    paused: items('paused_check'),
    ongoing: items('ongoing'),
    planned: items('planned'),
    pendingByKind,
  }
}

export function countsFor(member: WorkloadDetails) {
  const summary: WorkloadCounts = { slots: {}, items: {}, overdue: 0 }
  for (const run of member.executions) {
    summary.slots[run.slot] = (summary.slots[run.slot] ?? 0) + 1
  }
  for (const item of member.items) {
    summary.items[item.kind] = (summary.items[item.kind] ?? 0) + 1
    if (item.overdue) summary.overdue++
  }
  return countsFromSummary(summary)
}
