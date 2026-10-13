import { afterEach, beforeEach, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { CollaborationRuntime } from '../collaboration'
import { git, hash, resolved } from '../filesystem'

let root: string, runtime: CollaborationRuntime, repositories: any[], input: any
const head = (repo: any) => git(repo.local_path, 'rev-parse', 'HEAD')
const index = (repo: any) => fs.readFileSync(path.join(repo.local_path, '.git/index'))
beforeEach(() => {
  root = fs.mkdtempSync(path.join(tmpdir(), 'tf-mapped-'))
  repositories = ['api', 'web'].map((slug, i) => {
    const directory = path.join(root, 'user-repositories', slug); fs.mkdirSync(directory, { recursive: true })
    git(directory, 'init', '-b', i ? 'master' : 'main')
    git(directory, 'config', 'user.name', 'Test'); git(directory, 'config', 'user.email', 'test@example.com')
    git(directory, 'config', 'core.autocrlf', 'false'); git(directory, 'config', 'core.longpaths', 'true')
    git(directory, 'remote', 'add', 'origin', `https://example.invalid/${slug}.git`)
    fs.writeFileSync(path.join(directory, 'shared.txt'), slug + ':base\n')
    git(directory, 'add', '.'); git(directory, 'commit', '-m', 'base')
    return { task_repository_id: slug, repository_id: slug, repo_url: `https://example.invalid/${slug}.git`, repo_slug: slug,
      rel_path: slug, branch_name: i ? 'master' : 'main', base_commit_sha: git(directory, 'rev-parse', 'HEAD'), local_path: resolved(directory) }
  })
  runtime = new CollaborationRuntime(path.join(root, 'private'), () => [path.join(root, 'user-repositories')])
  input = { directory_mode: 'MAPPED', task_id: 'task', binding_id: 'binding', repositories,
    workspace_revision: 1, session_generation: 1, session_revision: 1, repository_set_digest: 'dual' }
}, 60_000)
afterEach(() => { runtime.close(); fs.rmSync(root, { recursive: true, force: true }) })

test('checks every repository and refuses HEAD mismatch and dirty files before any binding or checkout', () => {
  const [api, web] = repositories, originalHeads = repositories.map(head), originalIndexes = repositories.map(index)
  fs.writeFileSync(path.join(api.local_path, 'shared.txt'), 'local edit')
  input.repositories[1] = { ...web, base_commit_sha: 'f'.repeat(40) }
  const inspected = runtime.execute('inspect_mappings', input)
  expect(inspected.ready).toBe(false)
  expect(inspected.checks[0].errors).toContain('WORKTREE_DIRTY')
  expect(inspected.checks[1].errors).toContain('HEAD_MISMATCH')
  expect(() => runtime.execute('prepare', input)).toThrow('COLLABORATION_MAPPING_CHECK_FAILED')
  expect(fs.existsSync(path.join(root, 'private/bindings/task.json'))).toBe(false)
  expect(repositories.map(head)).toEqual(originalHeads)
  repositories.forEach((repo, i) => expect(index(repo)).toEqual(originalIndexes[i]))
  expect(fs.readFileSync(path.join(api.local_path, 'shared.txt'), 'utf8')).toBe('local edit')
}, 60_000)

test('reconnect reuses both Git indexes and only reads paths changed while disconnected', async () => {
  const originalIndexes = repositories.map(index)
  const initial = await runtime.executeAsync('prepare', input)
  runtime.execute('suspend', { task_id: 'task', binding_id: 'binding' })
  const resumed = await runtime.executeAsync('prepare', input)
  expect(resumed.scan_metrics.every((scan: any) => scan.kind === 'cached' && scan.files_read === 0)).toBe(true)
  runtime.execute('suspend', { task_id: 'task', binding_id: 'binding' })
  fs.writeFileSync(path.join(repositories[0].local_path, 'shared.txt'), 'offline human edit\n')
  fs.writeFileSync(path.join(repositories[0].local_path, 'new.txt'), 'offline addition\n')
  fs.unlinkSync(path.join(repositories[1].local_path, 'shared.txt'))
  const changed = await runtime.executeAsync('prepare', input)
  expect(changed.baseline).toEqual(initial.baseline)
  expect(changed.local_changes).toHaveLength(3)
  expect(changed.scan_metrics.every((scan: any) => scan.full_inventory === false)).toBe(true)
  expect(changed.scan_metrics.reduce((sum: number, scan: any) => sum + scan.files_read, 0)).toBe(2)
  expect(changed.manifest.repositories[0].files.find((file: any) => file.path === 'shared.txt').sha256).toBe(hash('offline human edit\n'))
  expect(changed.manifest.repositories[1].files).toEqual([])
  repositories.forEach((repo, i) => expect(index(repo)).toEqual(originalIndexes[i]))
  // Windows may report parent directory changes after the resumed cut. A lost
  // watcher barrier must also fall back to Git's delta rather than an inventory.
  for (const record of (runtime.index as any).indexes.values()) {
    fs.mkdirSync(path.join(record.root, 'empty-directory'))
    record.changedPaths.add('empty-directory'); record.changedPaths.add('.git')
    record.dirty = true; record.gap = true
  }
  const checked = await runtime.executeAsync('status', { task_id: 'task' })
  expect(checked.scan_metrics.every((scan: any) => scan.kind === 'cached' && scan.files_read === 0)).toBe(true)
  expect(checked.local_changes).toHaveLength(3)
  runtime.execute('suspend', { task_id: 'task', binding_id: 'binding' })
  git(repositories[0].local_path, 'checkout', '-b', 'another-branch')
  expect(() => runtime.execute('prepare', input)).toThrow('COLLABORATION_REPOSITORY_IDENTITY_CHANGED')
}, 120_000)

test('rejects staged changes, untracked files and overlapping repository mappings', () => {
  const api = repositories[0]
  git(api.local_path, 'config', 'status.showUntrackedFiles', 'no')
  fs.writeFileSync(path.join(api.local_path, 'new.txt'), 'untracked')
  expect(runtime.execute('inspect_mappings', input).checks[0].errors).toContain('WORKTREE_DIRTY')
  git(api.local_path, 'add', 'new.txt')
  expect(runtime.execute('inspect_mappings', input).checks[0].errors).toContain('WORKTREE_DIRTY')
  fs.rmSync(path.join(api.local_path, 'new.txt')); git(api.local_path, 'reset', '--', 'new.txt')
  const duplicate = { ...api, task_repository_id: 'other', rel_path: 'other' }
  expect(runtime.execute('inspect_mappings', { ...input, repositories: [api, duplicate] }).checks[1].errors).toContain('COLLABORATION_REPOSITORY_OVERLAP')
}, 60_000)

test('reserves mapped directories per task and releases them without cleaning user changes', async () => {
  await runtime.executeAsync('prepare', input)
  const another = { ...input, task_id: 'another', binding_id: 'another-binding' }
  expect(() => runtime.execute('prepare', another)).toThrow('COLLABORATION_DIRECTORY_IN_USE')
  fs.writeFileSync(path.join(repositories[0].local_path, 'shared.txt'), 'keep local edit')
  expect(runtime.execute('release', { task_id: 'task', binding_id: 'binding' }).managed_roots).toEqual([])
  expect(() => runtime.execute('prepare', another)).toThrow('COLLABORATION_MAPPING_CHECK_FAILED')
  expect(fs.readFileSync(path.join(repositories[0].local_path, 'shared.txt'), 'utf8')).toBe('keep local edit')
  fs.writeFileSync(path.join(repositories[0].local_path, 'shared.txt'), 'api:base\n')
  // A new desktop process has no previous binding ID in renderer memory.
  expect(runtime.execute('prepare', { ...input, binding_id: 're-enabled' }).directory_mode).toBe('MAPPED')
  runtime.execute('release', { task_id: 'task', binding_id: 're-enabled' })
  expect(runtime.execute('prepare', another).directory_mode).toBe('MAPPED')
}, 120_000)

test('uses the mapped directories for dual delivery and selected recovery without changing HEAD, branch or user index', async () => {
  const originalHeads = repositories.map(head), originalIndexes = repositories.map(index)
  const prepared = await runtime.executeAsync('prepare', input)
  expect(prepared.directory_mode).toBe('MAPPED')
  expect(prepared.repositories.map((repo: any) => repo.local_worktree_path)).toEqual(repositories.map(repo => repo.local_path))
  repositories.forEach(repo => expect(git(repo.local_path, 'worktree', 'list', '--porcelain').match(/^worktree /gm)?.length).toBe(1))
  const initial = { ...prepared.manifest, source: 'INITIAL', snapshot_id: 'base' }
  await runtime.executeAsync('reconcile', { task_id: 'task', operation_id: 'initial', target: initial })
  const target = structuredClone(initial); target.snapshot_id = 'output'; target.workspace_revision = 2; target.source = 'AGENT_OUTPUT'
  target.session_turn_id = 'turn-1'; target.turn_index = 1
  for (const repo of target.repositories) {
    const raw = Buffer.from(repo.repo_slug + ':cloud\n')
    runtime.execute('cache_objects', { objects: [{ sha256: hash(raw), content: raw.toString('base64') }] })
    repo.files[0] = { ...repo.files[0], sha256: hash(raw), size: raw.length }
  }
  for (const repo of repositories) fs.writeFileSync(path.join(repo.local_path, 'shared.txt'), repo.repo_slug + ':human\n')
  let status = await runtime.executeAsync('reconcile', { task_id: 'task', operation_id: 'final', target })
  expect(status.conflicts).toHaveLength(2)
  expect(runtime.execute('suspend', { task_id: 'task', binding_id: 'binding' }).managed_roots).toEqual([])
  expect(() => runtime.execute('capture', { task_id: 'task' })).toThrow('binding released')
  const retained = runtime.execute('binding', { task_id: 'task' })
  expect(retained.conflicts).toEqual(status.conflicts)
  expect(retained.baseline).toEqual(initial)
  status = await runtime.executeAsync('prepare', input)
  expect(status.conflicts).toHaveLength(2)
  const first = status.conflicts.find((row: any) => row.task_repository_id === 'api')
  status = runtime.execute('restore', { task_id: 'task', operation_id: 'restore-api', conflict_set_id: status.conflict_set_id, selected: [first] })
  expect(status.conflicts).toHaveLength(1)
  expect(fs.readFileSync(path.join(repositories[0].local_path, 'shared.txt'), 'utf8')).toBe('api:cloud\n')
  expect(fs.readFileSync(path.join(repositories[1].local_path, 'shared.txt'), 'utf8')).toBe('web:human\n')
  const backups = runtime.execute('backups', { task_id: 'task' }).backups
  expect(backups).toHaveLength(1)
  expect(fs.readFileSync(backups[0].backup_path, 'utf8')).toBe('api:human\n')
  expect(backups[0].backup_path).toContain('.git')
  expect(backups[0].context).toMatchObject({ task_id: 'task', snapshot_id: 'output', workspace_revision: 2, session_turn_id: 'turn-1', turn_index: 1, kind: 'restore', repo_slug: 'api', branch_name: 'main' })
  expect(Number.isFinite(Date.parse(backups[0].created_at))).toBe(true)
  expect(repositories.map(head)).toEqual(originalHeads)
  repositories.forEach((repo, i) => expect(index(repo)).toEqual(originalIndexes[i]))
  const resumed = await runtime.executeAsync('prepare', input)
  expect(resumed.conflicts).toHaveLength(1) // Dirty files are allowed after this binding's initial gate.
  fs.writeFileSync(path.join(repositories[0].local_path, 'independent.txt'), 'independent')
  const next = await runtime.executeAsync('status', { task_id: 'task' })
  expect(next.local_changes.some((row: any) => row.path === 'independent.txt')).toBe(true)
  runtime.execute('restore', { task_id: 'task', operation_id: 'restore-web', conflict_set_id: next.conflict_set_id, selected: next.conflicts })
  const second = structuredClone(target); second.snapshot_id = 'output-2'; second.workspace_revision = 3; second.session_turn_id = 'turn-2'; second.turn_index = 2
  const raw = Buffer.from('api:second round\n')
  runtime.execute('cache_objects', { objects: [{ sha256: hash(raw), content: raw.toString('base64') }] })
  second.repositories[0].files[0] = { ...second.repositories[0].files[0], sha256: hash(raw), size: raw.length }
  await runtime.executeAsync('reconcile', { task_id: 'task', operation_id: 'receive-second', target: second })
  runtime.close()
  runtime = new CollaborationRuntime(path.join(root, 'private'), () => [path.join(root, 'user-repositories')])
  const history = runtime.execute('backups', { task_id: 'task' }).backups
  expect(history).toHaveLength(3)
  expect(history.find((row: any) => row.operation_id === 'restore-api')).toEqual(backups[0])
  expect(history.find((row: any) => row.operation_id === 'restore-web').context).toMatchObject({ snapshot_id: 'output', turn_index: 1, repo_slug: 'web' })
  expect(history.find((row: any) => row.operation_id === 'receive-second').context).toMatchObject({ snapshot_id: 'output-2', turn_index: 2, kind: 'receive' })
  // Older receipts cannot inherit the new round from the current binding.
  const receiptPath = path.join(root, 'private', 'operations', 'restore-api', hash('api:shared.txt') + '.json')
  const legacy = JSON.parse(fs.readFileSync(receiptPath, 'utf8')); delete legacy.context; delete legacy.created_at
  fs.writeFileSync(receiptPath, JSON.stringify(legacy))
  expect(runtime.execute('backups', { task_id: 'task' }).backups.find((row: any) => row.operation_id === 'restore-api').context).toBeUndefined()
}, 120_000)
