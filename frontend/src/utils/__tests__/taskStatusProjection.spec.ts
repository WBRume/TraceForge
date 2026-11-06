import { describe, expect, it } from 'vitest'
import { applyTaskStatusSnapshot, mergeTaskSnapshot } from '../taskStatusProjection'

describe('authoritative task status projection', () => {
  it('applies only a strictly newer server snapshot and ignores reordered REST/WS duplicates', () => {
    const task = { id: 't', status: 'RUNNING', status_seq: '10' }
    expect(applyTaskStatusSnapshot(task, { task_id: 't', status: 'AWAITING_INPUT', status_seq: '12' })).toBe(true)
    expect(applyTaskStatusSnapshot(task, { task_id: 't', status: 'RUNNING', status_seq: '11' })).toBe(false)
    expect(applyTaskStatusSnapshot(task, { task_id: 't', status: 'RUNNING', status_seq: '12' })).toBe(false)
    mergeTaskSnapshot(task, { id: 't', name: 'updated', status: 'RUNNING', status_seq: '9' })
    expect(task).toMatchObject({ name: 'updated', status: 'AWAITING_INPUT', status_seq: '12' })
  })
  it('does not infer status from provider results, job statuses or unversioned responses', () => {
    const task = { id: 't', status: 'RUNNING', status_seq: '5' }
    for (const payload of [
      { task_id: 't', status: 'ROUND_COMPLETED' }, { task_id: 't', success: true },
      { task_id: 't', status: 'SUCCESS', status_seq: '6' },
      { task_id: 'other', status: 'COMPLETED', status_seq: '6' },
    ]) expect(applyTaskStatusSnapshot(task, payload)).toBe(false)
    expect(task.status).toBe('RUNNING')
  })
  it('preserves exact ordering above the JavaScript number precision limit', () => {
    const task = { id: 't', status: 'RUNNING', status_seq: '9007199254740992' }
    expect(applyTaskStatusSnapshot(task, { task_id: 't', status: 'COMPLETED', status_seq: '9007199254740993' })).toBe(true)
    expect(applyTaskStatusSnapshot(task, { task_id: 't', status: 'RUNNING', status_seq: 9007199254740994 })).toBe(false)
  })
  it('fences generation and revision with their authoritative status snapshot', () => {
    const task = { id: 't', status: 'RUNNING', status_seq: '10', session_generation: 3, session_revision: 4 }
    mergeTaskSnapshot(task, { status: 'INTERRUPTED', status_seq: '9', session_generation: 2, session_revision: 1 })
    expect(task).toMatchObject({ status: 'RUNNING', session_generation: 3, session_revision: 4 })
    mergeTaskSnapshot(task, { status: 'ROUND_COMPLETED', status_seq: '11', session_generation: 3, session_revision: 5 })
    expect(task).toMatchObject({ status: 'ROUND_COMPLETED', session_generation: 3, session_revision: 5 })
  })
})
