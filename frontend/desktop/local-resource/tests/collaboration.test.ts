import { afterEach, beforeEach, describe, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { CollaborationRuntime } from '../collaboration'
import { applyFile } from '../collaboration-write'
import { SyncObjects, type SyncManifest } from '../collaboration-store'
import { git, hash } from '../filesystem'
import { expandManifest, expandStatus, manifestDelta } from '../../../shared/collaboration-delta'

let root: string, runtime: CollaborationRuntime, prepared: any
const task = 'task1'
beforeEach(() => {
  root = fs.mkdtempSync(path.join(tmpdir(), 'tf-collaboration-'))
  runtime = new CollaborationRuntime(path.join(root, 'state'), () => [root])
  const repositories = ['api', 'web'].map((name, index) => {
    const local = path.join(root, name); fs.mkdirSync(local)
    git(local, 'init', '-b', 'main'); git(local, 'config', 'user.name', 'Test'); git(local, 'config', 'user.email', 'test@example.com')
    git(local, 'config', 'core.autocrlf', 'false')
    fs.writeFileSync(path.join(local, 'shared.txt'), 'base ' + name)
    fs.writeFileSync(path.join(local, 'deleted.txt'), 'old')
    git(local, 'add', '.'); git(local, 'commit', '-m', 'base ' + name)
    const base_commit_sha = git(local, 'rev-parse', 'HEAD')
    fs.writeFileSync(path.join(local, 'shared.txt'), 'tip ' + name)
    git(local, 'add', '.'); git(local, 'commit', '-m', 'new tip')
    fs.writeFileSync(path.join(local, 'shared.txt'), 'original dirty ' + name)
    const url = `https://example.com/personal/${name}.git`; git(local, 'remote', 'add', 'mine', url)
    return { task_repository_id: name, repository_id: 'r' + index, rel_path: name, repo_url: url,
      repo_slug: name, branch_name: index ? 'feature/login' : 'release/2.x', base_commit_sha,
      local_path: local, configured_git_url: url }
  })
  prepared = runtime.execute('prepare', { task_id: task, binding_id: 'binding1', workspace_root: path.join(root, 'tasks'),
    repositories, session_generation: 1, session_revision: 1, repository_set_digest: 'set', workspace_revision: 1 })
}, 60_000)
afterEach(() => { runtime.close(); fs.rmSync(root, { recursive: true, force: true }) })
const worktree = (repo = 'api') => prepared.repositories.find((item: any) => item.task_repository_id === repo).local_worktree_path
function target(version = 1): SyncManifest {
  return { ...structuredClone(prepared.baseline), snapshot_id: 'snapshot' + version, workspace_revision: version, source: 'AGENT_OUTPUT' }
}
function setFile(manifest: SyncManifest, repo: string, name: string, content: string | null) {
  const repository = manifest.repositories.find(item => item.task_repository_id === repo)!
  repository.files = repository.files.filter(file => file.path !== name)
  if (content !== null) repository.files.push({ path: name, sha256: runtime.objects.put(Buffer.from(content)), size: Buffer.byteLength(content), mode: '100644' })
}
function deliver(manifest: SyncManifest, operation_id = 'delivery1', preview = false) {
  return runtime.execute('reconcile', { task_id: task, operation_id, target: manifest, preview })
}

describe('embedded local collaboration with real Git worktrees', () => {
  test('keeps file backups readable after disconnecting without reconnecting or scanning code', () => {
    const final = target(); setFile(final, 'api', 'shared.txt', 'delivered result')
    deliver(final, 'backup-delivery')
    const before = runtime.execute('backups', { task_id:task })
    expect(before.backups.length).toBeGreaterThan(0)
    const backup = before.backups.find((file: any) => file.task_repository_id === 'api' && file.path === 'shared.txt')
    expect(runtime.objects.get(backup.sha256).toString()).toBe('base api')
    runtime.execute('suspend', { task_id:task, binding_id:'binding1' })
    runtime.index.scan = () => { throw new Error('Backup listing must not scan code') }
    expect(runtime.execute('backups', { task_id:task })).toEqual(before)
    expect(runtime.execute('binding', { task_id:task }).released).toBe(true)
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('delivered result')
  })
  test('delta IPC fences status, freezes input retries and falls back after renderer or worker restart', async () => {
    const base = target()
    let current = await runtime.executeAsync('reconcile', { task_id: task, operation_id: 'init-delta', target: base, delta_transport: true })
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'human delta')
    fs.unlinkSync(path.join(worktree('web'), 'deleted.txt'))
    const capture = await runtime.executeAsync('capture', { task_id: task, operation_id: 'delta-input', include_objects: false, delta_transport: true, status_token: current.transport.token })
    expect(capture.manifest.delta.base_snapshot_id).toBe(base.snapshot_id)
    expect(capture.manifest.repositories[0].files.map((file: any) => file.path)).toEqual(['shared.txt'])
    expect(capture.manifest.repositories[1].files).toEqual([])
    expect(capture.manifest.repositories[1].deleted).toEqual(['deleted.txt'])
    expect(capture.status.transport.base_token).toBe(current.transport.token)
    current = expandStatus(current, capture.status)
    const accepted = { ...expandManifest(base, capture.manifest), snapshot_id: 'accepted-delta', workspace_revision: base.workspace_revision + 1 }
    const receipt = await runtime.executeAsync('accept_input', { task_id: task, operation_id: 'delta-input', target: manifestDelta(base, accepted), delta_transport: true, status_token: current.transport.token })
    current = expandStatus(current, receipt)
    expect(current.local_changes).toEqual([])
    const retry = await runtime.executeAsync('capture', { task_id: task, operation_id: 'delta-input', include_objects: false, delta_transport: true, status_token: current.transport.token })
    expect(retry.manifest).toEqual(capture.manifest)
    expect(() => runtime.execute('reconcile', { task_id: task, target: { ...capture.manifest, delta: { base_snapshot_id: 'wrong' } } })).toThrow('DELTA_BASE_MISMATCH')
    const reconnect = await runtime.executeAsync('status', { task_id: task, delta_transport: true, status_token: 'lost-renderer' })
    expect(reconnect.transport.base_token).toBeUndefined()
    expect(reconnect.baseline.delta).toBeUndefined()
    runtime.close(); runtime = new CollaborationRuntime(path.join(root, 'state'), () => [root])
    const restarted = await runtime.executeAsync('status', { task_id: task, delta_transport: true, status_token: reconnect.transport.token })
    expect(restarted.transport.base_token).toBeUndefined()
    expect(restarted.baseline.snapshot_id).toBe(accepted.snapshot_id)
    expect(restarted.scan_metrics.every((scan: any) => scan.full_inventory)).toBe(true)
  }, 60_000)
  test('explicit comparison verification sees disk edits before watcher invalidation is delivered', () => {
    runtime.execute('status', { task_id: task, background: true })
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'latest comparison content')
    const checked = runtime.execute('status', { task_id: task, verify: true })
    expect(checked.manifest.repositories[0].files.find((file: any) => file.path === 'shared.txt').sha256).toBe(hash('latest comparison content'))
    expect(checked.local_changes.some((file: any) => file.path === 'shared.txt')).toBe(true)
  })
  test('isolates two task repositories at their exact bases, preserving dirty original checkouts and fork branches', () => {
    expect(prepared.repositories).toHaveLength(2)
    for (const repo of prepared.repositories) {
      expect(git(repo.local_worktree_path, 'rev-parse', 'HEAD')).toBe(repo.base_commit_sha)
      expect(git(repo.mapped_repo_root, 'branch', '--show-current')).toBe('main')
      expect(fs.readFileSync(path.join(repo.mapped_repo_root, 'shared.txt'), 'utf8')).toBe('original dirty ' + repo.task_repository_id)
      expect(fs.readFileSync(path.join(repo.local_worktree_path, 'shared.txt'), 'utf8')).toBe('base ' + repo.task_repository_id)
    }
  })
  test('captures raw bytes and local changes without waiting for a save event; rejects changed worktree identity', () => {
    fs.writeFileSync(path.join(worktree(), 'binary.dat'), Buffer.from([0, 255, 13, 10]))
    fs.writeFileSync(path.join(worktree(), '.env'), 'secret')
    const captured = runtime.execute('capture', { task_id: task })
    expect(captured.manifest.repositories[0].files.some((file: any) => file.path === '.env')).toBe(false)
    expect(captured.objects.find((item: any) => item.sha256 === hash(Buffer.from([0, 255, 13, 10]))).content).toBe('AP8NCg==')
    git(worktree(), 'checkout', '-b', 'user-switched')
    expect(() => runtime.execute('capture', { task_id: task })).toThrow('IDENTITY_CHANGED')
  })
  test('previews without writes, applies cloud-only changes/deletes, preserves local-only changes and requires final conflicts', () => {
    const final = target()
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'human')
    fs.writeFileSync(path.join(worktree(), 'local.txt'), 'keep me')
    setFile(final, 'api', 'shared.txt', 'cloud'); setFile(final, 'api', 'deleted.txt', null)
    setFile(final, 'web', 'shared.txt', 'cloud web')
    const preview = deliver(final, 'preview', true)
    expect(preview.preview_conflicts).toHaveLength(1)
    expect(fs.existsSync(path.join(worktree(), 'deleted.txt'))).toBe(true)
    const delivered = deliver(final)
    expect(delivered.state).toBe('CONFLICT_PENDING')
    expect(delivered.conflicts.map((item: any) => item.task_repository_id + '/' + item.path)).toEqual(['api/shared.txt'])
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('human')
    expect(fs.readFileSync(path.join(worktree('web'), 'shared.txt'), 'utf8')).toBe('cloud web')
    expect(fs.existsSync(path.join(worktree(), 'deleted.txt'))).toBe(false)
    expect(() => runtime.execute('capture', { task_id: task })).toThrow('DELIVERY_REQUIRED')
    const restored = runtime.execute('restore', { task_id: task, operation_id: 'restore1', conflict_set_id: delivered.conflict_set_id,
      selected: [{ task_repository_id: 'api', path: 'shared.txt', expected_sha256: hash('human') }] })
    expect(restored.state).toBe('READY')
    expect(restored.scan_metrics).toEqual([])
    expect(restored.local_changes.map((item: any) => item.path)).toEqual(['local.txt'])
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('cloud')
    expect(runtime.objects.get(hash('human')).toString()).toBe('human')
    expect(fs.readFileSync(path.join(worktree(), 'local.txt'), 'utf8')).toBe('keep me')
  })
  test('rejects stale conflict confirmation after a new local write and retains both copies', () => {
    const final = target(); setFile(final, 'api', 'shared.txt', 'cloud')
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'human')
    const pending = deliver(final)
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'new human')
    const failed = runtime.execute('restore', { task_id: task, operation_id: 'restore-stale', conflict_set_id: pending.conflict_set_id,
      selected: [{ task_repository_id: 'api', path: 'shared.txt', expected_sha256: hash('human') }] })
    expect(failed.state).toBe('RECOVERY_REQUIRED')
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('new human')
    const rechecked = deliver(final, 'recheck')
    expect(rechecked.conflicts[0].expected_sha256).toBe(hash('new human'))
    expect(rechecked.conflict_set_id).not.toBe(pending.conflict_set_id)
  })
  test('keeping one conflict preserves disk content and leaves an independent local edit after restart', () => {
    const final = target()
    for (const repo of ['api', 'web']) {
      setFile(final, repo, 'shared.txt', 'cloud ' + repo)
      fs.writeFileSync(path.join(worktree(repo), 'shared.txt'), 'human ' + repo)
    }
    const pending = deliver(final)
    const first = runtime.execute('restore', { task_id: task, operation_id: 'keep-api', decision: 'keep', conflict_set_id: pending.conflict_set_id,
      selected: [{ task_repository_id: 'api', path: 'shared.txt', expected_sha256: hash('human api') }] })
    expect(first.conflicts.map((row: any) => row.task_repository_id)).toEqual(['web'])
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('human api')
    runtime.close(); runtime = new CollaborationRuntime(path.join(root, 'state'), () => [root])
    const rechecked = deliver(final, 'after-keep-restart')
    expect(rechecked.conflicts.map((row: any) => row.task_repository_id)).toEqual(['web'])
    const ready = runtime.execute('restore', { task_id: task, operation_id: 'keep-web', decision: 'keep', conflict_set_id: rechecked.conflict_set_id,
      selected: [{ task_repository_id: 'web', path: 'shared.txt', expected_sha256: hash('human web') }] })
    expect(ready.state).toBe('READY')
    expect(ready.local_changes.filter((row: any) => row.path === 'shared.txt')).toHaveLength(2)
    const captured = runtime.execute('capture', { task_id: task })
    expect(captured.manifest.repositories[0].files.find((row: any) => row.path === 'shared.txt').sha256).toBe(hash('human api'))
    expect(() => runtime.execute('restore', { task_id: task, operation_id: 'repeat', decision: 'keep', conflict_set_id: rechecked.conflict_set_id,
      selected: [{ task_repository_id: 'web', path: 'shared.txt', expected_sha256: hash('human web') }] })).toThrow('CONFIRMATION_EXPIRED')
  }, 60_000)
  test('keeping a conflict refuses a new save after the displayed comparison', () => {
    const final = target(); setFile(final, 'api', 'shared.txt', 'cloud')
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'human')
    const pending = deliver(final)
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'new human')
    const failed = runtime.execute('restore', { task_id: task, operation_id: 'keep-stale', decision: 'keep', conflict_set_id: pending.conflict_set_id,
      selected: [{ task_repository_id: 'api', path: 'shared.txt', expected_sha256: hash('human') }] })
    expect(failed.state).toBe('RECOVERY_REQUIRED')
    expect(failed.conflicts).toHaveLength(1)
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('new human')
  }, 60_000)
  test('selected restore refuses a changed task branch without scanning repository contents', () => {
    const final = target(); setFile(final, 'api', 'shared.txt', 'cloud')
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'human')
    const pending = deliver(final)
    git(worktree(), 'checkout', '-b', 'changed-task-branch')
    runtime.index.scan = () => { throw new Error('restore must not scan the repository') }
    expect(() => runtime.execute('restore', { task_id: task, operation_id: 'changed-branch', conflict_set_id: pending.conflict_set_id,
      selected: [{ task_repository_id: 'api', path: 'shared.txt', expected_sha256: hash('human') }] })).toThrow('IDENTITY_CHANGED')
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('human')
  })
  test('rebinds an equivalent duplicate FINAL while expiring prior conflict confirmation', () => {
    const final = target(); setFile(final, 'api', 'shared.txt', 'cloud')
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'human')
    fs.writeFileSync(path.join(worktree(), 'local-only.txt'), 'keep')
    const pending = deliver(final)
    const duplicate = structuredClone(final); duplicate.snapshot_id = 'equivalent-final'
    duplicate.repositories.reverse(); duplicate.repositories.forEach(repo => repo.files.reverse())
    const rebound = deliver(duplicate, 'equivalent-delivery')
    expect(rebound.target.snapshot_id).toBe('equivalent-final')
    expect(rebound.conflict_set_id).not.toBe(pending.conflict_set_id)
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('human')
    expect(fs.readFileSync(path.join(worktree(), 'local-only.txt'), 'utf8')).toBe('keep')
    expect(() => runtime.execute('restore', { task_id: task, operation_id: 'old-confirmation', conflict_set_id: pending.conflict_set_id,
      selected: [{ task_repository_id: 'api', path: 'shared.txt', expected_sha256: hash('human') }] })).toThrow('CONFIRMATION_EXPIRED')
    const different = structuredClone(duplicate); different.snapshot_id = 'different-final'; setFile(different, 'api', 'shared.txt', 'other')
    expect(() => deliver(different, 'different-delivery')).toThrow('PENDING_TARGET_REQUIRED')
    const newer = { ...duplicate, snapshot_id: 'newer-final', workspace_revision: duplicate.workspace_revision + 1 }
    expect(() => deliver(newer, 'newer-delivery')).toThrow('PENDING_TARGET_REQUIRED')
  })
  test('restores only selected files across restart and does not replay completed writes over later edits', () => {
    const final = target()
    for (const repo of ['api', 'web']) {
      fs.writeFileSync(path.join(worktree(repo), 'shared.txt'), 'human ' + repo)
      setFile(final, repo, 'shared.txt', 'cloud ' + repo)
    }
    const pending = deliver(final)
    runtime.close(); runtime = new CollaborationRuntime(path.join(root, 'state'), () => [root])
    const partial = runtime.execute('restore', { task_id: task, operation_id: 'restore-partial', conflict_set_id: pending.conflict_set_id,
      selected: [{ task_repository_id: 'api', path: 'shared.txt', expected_sha256: hash('human api') }] })
    expect(partial.state).toBe('CONFLICT_PENDING')
    expect(partial.conflicts[0].task_repository_id).toBe('web')
    expect(fs.readFileSync(path.join(worktree('web'), 'shared.txt'), 'utf8')).toBe('human web')
  })
  test('refuses traversal, duplicate repository entries and missing objects before any application', () => {
    const invalid = target(); invalid.repositories[0].files[0].path = '../escape'
    expect(() => deliver(invalid)).toThrow('INVALID_COLLABORATION_PATH')
    const missing = target(); missing.repositories[0].files[0].sha256 = 'a'.repeat(64)
    expect(() => deliver(missing)).toThrow()
    const duplicate = target(); duplicate.repositories[1] = duplicate.repositories[0]
    expect(() => deliver(duplicate)).toThrow('REPOSITORY_SET_MISMATCH')
  })
  test('freezes one handoff across retries and accepts its receipt without overwriting post-cut local edits', () => {
    deliver(target(), 'initial')
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'captured input')
    const captured = runtime.execute('capture', { task_id: task, operation_id: 'handoff:submission', include_objects: false })
    expect(captured.objects).toEqual([])
    expect(captured.input_cut_seq).toBeGreaterThan(0)
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'after capture')
    const repeated = runtime.execute('capture', { task_id: task, operation_id: 'handoff:submission' })
    expect(repeated.manifest).toEqual(captured.manifest)
    expect(repeated.input_cut_seq).toBe(captured.input_cut_seq)
    const accepted = { ...captured.manifest, snapshot_id: 'human1', source: 'HUMAN_HANDOFF', workspace_revision: 2 }
    const state = runtime.execute('accept_input', { task_id: task, operation_id: 'handoff:submission', target: accepted })
    expect(state.state).toBe('READY')
    expect(state.local_changes[0].local.sha256).toBe(hash('after capture'))
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('after capture')
  })
  test('persists progressive P, preserves subsequent local edits and handles final cloud reverts', () => {
    deliver(target(), 'initial')
    const candidate = target(2); setFile(candidate, 'api', 'shared.txt', 'candidate')
    runtime.execute('reconcile', { task_id: task, operation_id: 'progress1', target: candidate, preview: true, progressive: true })
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'edited candidate')
    const completed = deliver(candidate, 'final-same')
    expect(completed.state).toBe('READY')
    expect(completed.local_changes[0].local.sha256).toBe(hash('edited candidate'))
    const reverted = target(3)
    expect(deliver(reverted, 'reverted').state).toBe('CONFLICT_PENDING')
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('edited candidate')
  })
  test('groups file-directory collisions and restores related paths without removing unrelated files', () => {
    deliver(target(), 'initial')
    fs.mkdirSync(path.join(worktree(), 'nested'))
    fs.writeFileSync(path.join(worktree(), 'nested/local.txt'), 'nested local')
    const final = target(2); setFile(final, 'api', 'nested', 'cloud flat file')
    const blocked = deliver(final, 'structural')
    expect(blocked.state).toBe('CONFLICT_PENDING')
    expect(blocked.conflicts.map((file: any) => file.path).sort()).toEqual(['nested', 'nested/local.txt'])
    expect(() => runtime.execute('restore', { task_id: task, operation_id: 'incomplete-group', conflict_set_id: blocked.conflict_set_id,
      selected: [{ task_repository_id: 'api', path: 'nested', expected_sha256: null }] })).toThrow('RELATED_PATHS_REQUIRED')
    const restored = runtime.execute('restore', { task_id: task, operation_id: 'restore-group', conflict_set_id: blocked.conflict_set_id,
      selected: blocked.conflicts.map((file: any) => ({ task_repository_id: file.task_repository_id, path: file.path, expected_sha256: file.expected_sha256 })) })
    expect(restored.state).toBe('READY')
    expect(fs.readFileSync(path.join(worktree(), 'nested'), 'utf8')).toBe('cloud flat file')
    expect(runtime.objects.get(hash('nested local')).toString()).toBe('nested local')
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('base api')
  })
  test('reenables the same directories only with an explicit previous binding and preserves edits', () => {
    deliver(target(), 'initial')
    fs.writeFileSync(path.join(worktree(), 'shared.txt'), 'edit while disabled')
    const input = { ...prepared, binding_id: 'newbinding', workspace_root: path.join(root, 'tasks') }
    expect(() => runtime.execute('prepare', input)).toThrow('BINDING_CONFLICT')
    const rebound = runtime.execute('prepare', { ...input, previous_binding_id: 'binding1' })
    expect(rebound.binding_id).toBe('newbinding')
    expect(rebound.baseline.snapshot_id).toBe('snapshot1')
    expect(rebound.repositories[0].local_worktree_path).toBe(worktree())
    expect(fs.readFileSync(path.join(worktree(), 'shared.txt'), 'utf8')).toBe('edit while disabled')
  })
})

describe('no-clobber file replacement boundary', () => {
  test('captures an edit arriving between digest check and displacement and safely puts it back', () => {
    const directory = worktree(), objects = new SyncObjects(path.join(root, 'write-state'))
    const expected = { path: 'shared.txt', sha256: objects.put(Buffer.from('base api')), size: 8, mode: '100644' as const }
    const targetFile = { ...expected, sha256: objects.put(Buffer.from('cloud')), size: 5 }
    expect(() => applyFile({ state: path.join(root, 'write-state'), operation_id: 'race1', task_repository_id: 'api', root: directory,
      relative: 'shared.txt', expected, target: targetFile, objects,
      beforeMove: () => fs.writeFileSync(path.join(directory, 'shared.txt'), 'race edit') })).toThrow('REPLACEMENT_BOUNDARY')
    expect(fs.readFileSync(path.join(directory, 'shared.txt'), 'utf8')).toBe('race edit')
    expect(objects.get(hash('race edit')).toString()).toBe('race edit')
  })
  test('never overwrites a destination recreated after displacement, preserving displaced backup', () => {
    const directory = worktree(), objects = new SyncObjects(path.join(root, 'write-state'))
    const expected = { path: 'shared.txt', sha256: objects.put(Buffer.from('base api')), size: 8, mode: '100644' as const }
    const targetFile = { ...expected, sha256: objects.put(Buffer.from('cloud')), size: 5 }
    expect(() => applyFile({ state: path.join(root, 'write-state'), operation_id: 'race2', task_repository_id: 'api', root: directory,
      relative: 'shared.txt', expected, target: targetFile, objects,
      afterMove: () => fs.writeFileSync(path.join(directory, 'shared.txt'), 'new destination') })).toThrow('REPLACEMENT_BOUNDARY')
    expect(fs.readFileSync(path.join(directory, 'shared.txt'), 'utf8')).toBe('new destination')
    expect(objects.get(hash('base api')).toString()).toBe('base api')
  })
})
