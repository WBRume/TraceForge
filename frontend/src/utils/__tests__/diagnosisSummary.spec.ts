import { describe, expect, it } from 'vitest'
import {
  isDiagnosisSummaryActive,
  isDiagnosisSummaryActiveForTask,
  isDiagnosisSummaryJob,
  resolveDiagnosisSummaryStartedMs,
  type DiagnosisSummaryJobLite,
  type DiagnosisSummaryJobStatus,
} from '@/utils/diagnosisSummary'

const summaryJob = (
  status: DiagnosisSummaryJobStatus,
  taskId = 'task-1',
  jobKind = 'DIAGNOSIS_SUMMARY',
): DiagnosisSummaryJobLite => ({
  id: 'job-1',
  task_id: taskId,
  status,
  context_json: { job_kind: jobKind },
})

describe('isDiagnosisSummaryJob', () => {
  it('recognizes DIAGNOSIS_SUMMARY jobs (case-insensitive)', () => {
    expect(isDiagnosisSummaryJob(summaryJob('RUNNING'))).toBe(true)
    expect(isDiagnosisSummaryJob(summaryJob('RUNNING', 'task-1', 'diagnosis_summary'))).toBe(true)
    expect(isDiagnosisSummaryJob(summaryJob('RUNNING', 'task-1', 'THREAD_AI_REPLY'))).toBe(false)
    expect(isDiagnosisSummaryJob(null)).toBe(false)
    expect(isDiagnosisSummaryJob({ status: 'RUNNING', context_json: null })).toBe(false)
  })
})

describe('isDiagnosisSummaryActive', () => {
  it('is active only while PENDING/RUNNING', () => {
    expect(isDiagnosisSummaryActive(summaryJob('PENDING'))).toBe(true)
    expect(isDiagnosisSummaryActive(summaryJob('RUNNING'))).toBe(true)
    expect(isDiagnosisSummaryActive(summaryJob('SUCCESS'))).toBe(false)
    expect(isDiagnosisSummaryActive(summaryJob('FAILED'))).toBe(false)
    expect(isDiagnosisSummaryActive(summaryJob('CANCELLED'))).toBe(false)
    expect(isDiagnosisSummaryActive(summaryJob('INTERRUPTED'))).toBe(false)
    expect(isDiagnosisSummaryActive(summaryJob('WAITING_HITL'))).toBe(false)
  })
})

describe('isDiagnosisSummaryActiveForTask', () => {
  it('scopes by task id and supports Record or array input', () => {
    const array = [
      summaryJob('SUCCESS', 'task-1'),
      summaryJob('RUNNING', 'task-2'),
    ]
    expect(isDiagnosisSummaryActiveForTask(array, 'task-2')).toBe(true)
    expect(isDiagnosisSummaryActiveForTask(array, 'task-1')).toBe(false)
    expect(isDiagnosisSummaryActiveForTask(array, 'task-3')).toBe(false)

    const record = { 'job-1': summaryJob('PENDING', 'task-1') }
    expect(isDiagnosisSummaryActiveForTask(record, 'task-1')).toBe(true)
    expect(isDiagnosisSummaryActiveForTask(record, 'task-2')).toBe(false)
  })

  it('returns false for empty or null task id', () => {
    expect(isDiagnosisSummaryActiveForTask([], 'task-1')).toBe(false)
    expect(isDiagnosisSummaryActiveForTask([], null)).toBe(false)
    expect(isDiagnosisSummaryActiveForTask([], undefined)).toBe(false)
  })
})

describe('resolveDiagnosisSummaryStartedMs', () => {
  const created = '2026-08-28T06:00:00.000Z'
  const started = '2026-08-28T06:01:00.000Z'

  it('prefers created_at over started_at (发起时刻跨 session 恒定)', () => {
    const job = { ...summaryJob('RUNNING'), created_at: created, started_at: started }
    expect(resolveDiagnosisSummaryStartedMs([job], 'task-1')).toBe(Date.parse(created))
  })

  it('falls back to started_at when created_at is missing', () => {
    const job = { ...summaryJob('RUNNING'), started_at: started }
    expect(resolveDiagnosisSummaryStartedMs([job], 'task-1')).toBe(Date.parse(started))
  })

  it('returns 0 when no timestamp, not active, or not the target task', () => {
    expect(resolveDiagnosisSummaryStartedMs([summaryJob('RUNNING')], 'task-1')).toBe(0)
    expect(resolveDiagnosisSummaryStartedMs([{ ...summaryJob('SUCCESS'), created_at: created }], 'task-1')).toBe(0)
    expect(
      resolveDiagnosisSummaryStartedMs([{ ...summaryJob('RUNNING', 'other'), created_at: created }], 'task-1'),
    ).toBe(0)
    expect(resolveDiagnosisSummaryStartedMs([], 'task-1')).toBe(0)
  })

  it('supports Record input', () => {
    const record = { 'job-1': { ...summaryJob('PENDING'), created_at: created } }
    expect(resolveDiagnosisSummaryStartedMs(record, 'task-1')).toBe(Date.parse(created))
  })
})