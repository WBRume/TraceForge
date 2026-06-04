import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import api from '@/utils/api'
import { waitForSkillImportJob } from '../skillGithubImportJob'

vi.mock('@/utils/api', () => ({
  default: {
    get: vi.fn(),
  },
}))

const apiGetMock = vi.mocked(api.get)

describe('skillGithubImportJob', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    apiGetMock.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('checks the job one final time before returning timeout', async () => {
    apiGetMock
      .mockResolvedValueOnce({
        data: {
          job_id: 'job-1',
          job_type: 'IMPORT_SKILL',
          status: 'RUNNING',
          progress: 20,
          stage: 'CLONING_REPOSITORY',
        },
      })
      .mockResolvedValueOnce({
        data: {
          job_id: 'job-1',
          job_type: 'IMPORT_SKILL',
          status: 'SUCCESS',
          progress: 100,
          stage: 'COMPLETED',
          result_json: { skill_id: 'skill-1' },
        },
      })

    const resultPromise = waitForSkillImportJob('job-1', {
      timeoutMs: 50,
      intervalMs: 1000,
    })

    await vi.advanceTimersByTimeAsync(50)
    const result = await resultPromise

    expect(result).toMatchObject({ state: 'success', skillId: 'skill-1' })
    expect(apiGetMock).toHaveBeenCalledTimes(2)
  })

  it('still returns timeout when the final check is not terminal', async () => {
    apiGetMock.mockResolvedValue({
      data: {
        job_id: 'job-1',
        job_type: 'IMPORT_SKILL',
        status: 'RUNNING',
        progress: 20,
        stage: 'CLONING_REPOSITORY',
      },
    })

    const resultPromise = waitForSkillImportJob('job-1', {
      timeoutMs: 50,
      intervalMs: 1000,
    })

    await vi.advanceTimersByTimeAsync(50)
    const result = await resultPromise

    expect(result.state).toBe('timeout')
    expect(result.job?.status).toBe('RUNNING')
    expect(apiGetMock).toHaveBeenCalledTimes(2)
  })
})
