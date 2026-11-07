import { describe, expect, it } from 'vitest'
import { domainMilestones } from '../domainMilestones'

describe('domain milestones', () => {
  it('keeps validation and persistence distinct and deduplicates replay', () => {
    const accepted = { run_id: 'r', call_id: 'call-1', tool: 'submit', sequence: 2, stage: 'accepted', message: '已校验', timestamp: 2, issues: [] }
    const repaired = { ...accepted, sequence: 1, stage: 'repairing', message: '正在修正', timestamp: 1, issues: ['priority invalid'] }
    expect(domainMilestones([accepted, repaired, accepted]).map(e => e.stage)).toEqual(['repairing', 'accepted'])
    expect(domainMilestones([null, {}, 'text'])).toEqual([])
  })
})
