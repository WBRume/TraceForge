import { describe, expect, it } from 'vitest'
import { expandManifest, expandStatus, manifestDelta, statusDelta } from '../../../../shared/collaboration-delta'

const base = { task_id: 'task', snapshot_id: 'base', repository_set_digest: 'set', repositories: [{ task_repository_id: 'r', branch_name: 'feature/test', base_commit_sha: 'abc', files: [{ path: 'file', sha256: 'old', size: 3, mode: '100644' }] }] }
describe('collaboration delta transport', () => {
  it('a new target or preview reuses the prior baseline instead of transferring another full manifest', () => {
    const target = { ...base, snapshot_id: 'cloud', repositories: [{ ...base.repositories[0], files: [...base.repositories[0].files, { path: 'new', sha256: 'new', size: 3, mode: '100644' }] }] }
    const previous = { baseline: base, target: null, transport: { token: 'old-token' } }
    const wire = statusDelta(previous, { baseline: base, target, preview: target }, 'new-token', 'old-token')
    expect(wire.target.repositories[0].files.map((file: any) => file.path)).toEqual(['new'])
    expect(wire.preview.repositories[0].files.map((file: any) => file.path)).toEqual(['new'])
    const hydrated = expandStatus(previous, wire)
    expect(hydrated.target).toEqual(target)
    expect(hydrated.preview).toEqual(target)
    expect(() => expandStatus({ ...previous, transport: { token: 'lost' } }, wire)).toThrow('STATUS_BASE_MISMATCH')
  })
  it('rejects a wrong base, different branch and duplicate or ambiguous paths', () => {
    const wire = manifestDelta(base, base)
    expect(() => expandManifest({ ...base, snapshot_id: 'wrong' }, wire)).toThrow('DELTA_BASE_MISMATCH')
    expect(() => expandManifest(base, { ...wire, repositories: [{ ...wire.repositories[0], branch_name: 'other' }] })).toThrow('DELTA_REPOSITORY_MISMATCH')
    const duplicate = { ...wire, repositories: [{ ...wire.repositories[0], deleted: ['file', 'file'] }] }
    expect(() => expandManifest(base, duplicate)).toThrow('DELTA_PATH_MISMATCH')
    const removed = manifestDelta(base, { ...base, repositories: [{ ...base.repositories[0], files: [] }] })
    expect(expandManifest(base, removed).repositories[0].files).toEqual([])
  })
})
