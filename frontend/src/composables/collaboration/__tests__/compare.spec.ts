import { describe, expect, it } from 'vitest'
import { changedFiles, collaborationFileKey, localFiles, manifestFiles } from '../compare'
import type { CollaborationManifest } from '@/types/collaboration'

const snapshot = (values: [string, string, string][]): CollaborationManifest => ({
  protocol_version: 1, snapshot_id: 's1', task_id: 'task', source: 'INITIAL', workspace_revision: 1, session_generation: 1, session_revision: 1, repository_set_digest: 'digest',
  repositories: values.map(([repository, path, sha256]) => ({ task_repository_id: repository, repository_id: repository, repo_url: repository, repo_slug: repository, rel_path: repository, branch_name: 'main', base_commit_sha: 'sha', files: [{ path, sha256, size: 1, mode: '100644' }] })),
})

describe('collaboration comparison sources', () => {
  it('keeps identical paths in separate repositories independent, including deletion', () => {
    const before = manifestFiles(snapshot([['api', 'index.ts', 'a'], ['web', 'index.ts', 'b']]))
    const after = manifestFiles(snapshot([['web', 'index.ts', 'c']]))
    expect(changedFiles(before, after).map(file => file.key)).toEqual([collaborationFileKey('api', 'index.ts'), collaborationFileKey('web', 'index.ts')])
  })
  it('compares real scanned content without dropping independent local-only changes', () => {
    const baseline = snapshot([['api', 'index.ts', 'a']])
    const manifest = snapshot([['api', 'index.ts', 'b'], ['web', 'theme.css', 'c']])
    const current = localFiles({ task_id: 'task', baseline, manifest })
    expect(current.get(collaborationFileKey('api', 'index.ts'))?.sha256).toBe('b')
    expect(changedFiles(manifestFiles(baseline), current)).toHaveLength(2)
  })
  it('retains a deletion when the fallback scan carries no full manifest', () => {
    const baseline = snapshot([['api', 'index.ts', 'a']])
    const current = localFiles({ task_id: 'task', baseline, local_changes: [{ task_repository_id: 'api', path: 'index.ts', base: baseline.repositories[0]!.files[0]!, local: null }] })
    expect(current.size).toBe(0)
    expect(changedFiles(manifestFiles(baseline), current)[0]?.path).toBe('index.ts')
  })
})
