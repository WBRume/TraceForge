import { describe, expect, it } from 'vitest'
import { acceptsJobSnapshot, isJobTerminal } from '@/utils/jobSnapshot'

describe('job snapshot ordering', () => {
  it('accepts a new attempt with reset progress through its version', () => {
    expect(acceptsJobSnapshot({ version: 9, attempt_count: 1, status: 'RUNNING' },
      { version: 10, attempt_count: 2, status: 'RUNNING' })).toBe(true)
  })

  it('ignores old and duplicate callbacks regardless of their terminal state', () => {
    expect(acceptsJobSnapshot({ version: 10, status: 'RUNNING' }, { version: 9, status: 'SUCCESS' })).toBe(false)
    expect(acceptsJobSnapshot({ version: 10, status: 'SUCCESS' }, { version: 10, status: 'SUCCESS' })).toBe(false)
  })

  it('does not let unversioned updates replace a versioned snapshot', () => {
    expect(acceptsJobSnapshot({ version: 10, status: 'RUNNING' }, { status: 'SUCCESS' })).toBe(false)
  })

  it('keeps stop requests and uncertain cleanup active', () => {
    expect(isJobTerminal('TERMINATING')).toBe(false)
    expect(isJobTerminal('ORPHANED')).toBe(false)
    expect(isJobTerminal('CANCELLED')).toBe(true)
  })
})
