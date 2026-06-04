import { describe, expect, it } from 'vitest'
import { normalizeRemoteUrl, redactLog, remoteUrlsMatch } from '@/composables/local-agent/localAgentUtils'

describe('localAgentUtils', () => {
  it('normalizes https and ssh remotes for matching', () => {
    expect(remoteUrlsMatch('https://github.com/acme/repo.git', 'git@github.com:acme/repo.git')).toBe(true)
    expect(normalizeRemoteUrl('https://github.com/acme/repo/')).toBe('github.com/acme/repo')
  })

  it('redacts tokens from logs', () => {
    expect(redactLog('Authorization: Bearer abc.def.ghi token=secret')).toContain('Bearer [REDACTED]')
    expect(redactLog('Authorization: Bearer abc.def.ghi token=secret')).toContain('token=[REDACTED]')
  })
})
