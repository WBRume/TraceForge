import type { MemberWorkload, WorkloadKind } from '@/types/workload'

export const pendingKinds: WorkloadKind[] = ['reply', 'check', 'acceptance', 'failure']
export const countsFor = (member: MemberWorkload) => {
  const items = (kind: WorkloadKind) => member.items.filter(item => item.kind === kind).length
  return {
    pending: member.items.filter(item => pendingKinds.includes(item.kind)).length,
    overdue: member.items.filter(item => item.overdue).length,
    background: member.executions.filter(run => run.slot === 'background').length,
    interactive: member.executions.filter(run => run.slot === 'interactive').length,
    incomplete: member.executions.filter(run => run.slot === 'incomplete').length,
    uncertain: member.executions.filter(run => run.slot === 'uncertain').length,
    active: member.executions.filter(run => run.slot !== 'uncertain').length,
    expected: items('expected_check'),
    paused: items('paused_check'),
    ongoing: items('ongoing'),
    planned: items('planned'),
    pendingByKind: pendingKinds.map(kind => ({ kind, count: items(kind) })).filter(item => item.count > 0),
  }
}
