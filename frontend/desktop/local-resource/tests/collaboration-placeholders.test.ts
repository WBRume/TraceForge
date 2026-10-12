import { afterEach, beforeEach, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { CollaborationRuntime } from '../collaboration'
import { applyFile } from '../collaboration-write'
import { type SyncManifest } from '../collaboration-store'
import { git, hash } from '../filesystem'

let root: string, source: string, tree: string, runtime: CollaborationRuntime, prepared: any
const windowsTest = process.platform === 'win32' ? test : test.skip
beforeEach(() => {
  root = fs.mkdtempSync(path.join(tmpdir(), 'tf-collaboration-placeholder-'))
  source = path.join(root, 'source'); fs.mkdirSync(source)
  git(source, 'init', '-b', 'main'); git(source, 'config', 'user.name', 'Test'); git(source, 'config', 'user.email', 'test@example.com')
  git(source, 'config', 'core.autocrlf', 'false'); git(source, 'config', 'core.symlinks', 'false')
  fs.writeFileSync(path.join(source, 'regular.txt'), 'regular')
  fs.mkdirSync(path.join(source, 'links')); fs.writeFileSync(path.join(source, 'links/reference'), '../regular.txt')
  git(source, 'add', '.')
  const blob = git(source, 'hash-object', '-w', 'links/reference')
  git(source, 'update-index', '--add', '--cacheinfo', '120000,' + blob + ',links/reference')
  git(source, 'commit', '-m', 'tracked Windows link placeholder')
  git(source, 'remote', 'add', 'origin', 'https://example.com/repo.git')
  runtime = new CollaborationRuntime(path.join(root, 'state'), () => [root])
  if (process.platform !== 'win32') return
  prepared = runtime.execute('prepare', { task_id: 'task', binding_id: 'binding', workspace_root: path.join(root, 'tasks'),
    repositories: [{ task_repository_id: 'repo', repository_id: 'repo', repo_url: 'https://example.com/repo.git', repo_slug: 'repo',
      rel_path: 'repo', branch_name: 'main', base_commit_sha: git(source, 'rev-parse', 'HEAD'), local_path: source }],
    session_generation: 1, session_revision: 1, repository_set_digest: 'set', workspace_revision: 1 })
  tree = prepared.repositories[0].local_worktree_path
}, 60_000)
afterEach(() => { runtime?.close(); if (root) fs.rmSync(root, { recursive: true, force: true }) })
function target(): SyncManifest {
  return { ...structuredClone(prepared.baseline), snapshot_id: 'cloud', workspace_revision: 2, source: 'AGENT_OUTPUT' }
}

windowsTest('round trips tracked Windows Git link text, restores conflicts and never materializes a real link', () => {
  const placeholder = prepared.baseline.repositories[0].files.find((file: any) => file.path === 'links/reference')
  expect(placeholder.mode).toBe('120000')
  expect(runtime.objects.get(placeholder.sha256).toString()).toBe('../regular.txt')
  expect(fs.lstatSync(path.join(tree, placeholder.path)).isSymbolicLink()).toBe(false)
  const cloud = target(), entry = cloud.repositories[0].files.find(file => file.path === placeholder.path)!
  entry.sha256 = runtime.objects.put(Buffer.from('../../cloud-destination')); entry.size = 23
  fs.writeFileSync(path.join(tree, placeholder.path), '../../human-destination')
  const pending = runtime.execute('reconcile', { task_id: 'task', operation_id: 'deliver', target: cloud })
  expect(pending.state).toBe('CONFLICT_PENDING')
  expect(pending.conflicts[0].local.mode).toBe('120000')
  const restored = runtime.execute('restore', { task_id: 'task', operation_id: 'restore', conflict_set_id: pending.conflict_set_id,
    selected: [{ task_repository_id: 'repo', path: placeholder.path, expected_sha256: hash('../../human-destination') }] })
  expect(restored.state).toBe('READY')
  expect(fs.lstatSync(path.join(tree, placeholder.path)).isFile()).toBe(true)
  expect(fs.readFileSync(path.join(tree, placeholder.path), 'utf8')).toBe('../../cloud-destination')
  expect(runtime.execute('capture', { task_id: 'task', include_objects: false }).manifest.repositories[0].files.find((file: any) => file.path === placeholder.path).mode).toBe('120000')
  expect(git(tree, 'ls-files', '--stage', 'links/reference').startsWith('120000 ')).toBe(true)
}, 60_000)

windowsTest('rejects injected placeholder paths, Git type conversion and manifest type conversion before writes', () => {
  for (const name of ['regular.txt', 'new-link']) {
    const cloud = target()
    cloud.repositories[0].files = cloud.repositories[0].files.filter(file => file.path !== name)
    cloud.repositories[0].files.push({ path: name, sha256: runtime.objects.put(Buffer.from('../outside')), size: 10, mode: '120000' })
    expect(() => runtime.execute('reconcile', { task_id: 'task', operation_id: 'injected', target: cloud })).toThrow('PLACEHOLDER_TYPE_CHANGED')
  }
  const cloud = target(), placeholder = cloud.repositories[0].files.find(file => file.path === 'links/reference')!
  placeholder.mode = '100644'
  expect(() => runtime.execute('reconcile', { task_id: 'task', operation_id: 'converted', target: cloud })).toThrow('PLACEHOLDER_TYPE_CHANGED')
  const expected = prepared.baseline.repositories[0].files.find((file: any) => file.path === 'links/reference')
  expect(() => applyFile({ state: path.join(root, 'state'), operation_id: 'direct', task_repository_id: 'repo', root: tree,
    relative: expected.path, expected, target: placeholder, objects: runtime.objects })).toThrow('PLACEHOLDER_TYPE_CHANGED')
  const blob = git(tree, 'hash-object', '-w', 'links/reference')
  git(tree, 'update-index', '--cacheinfo', '100644,' + blob + ',links/reference')
  expect(() => runtime.execute('capture', { task_id: 'task', include_objects: false })).toThrow('PLACEHOLDER_TYPE_CHANGED')
  expect(fs.readFileSync(path.join(tree, 'links/reference'), 'utf8')).toBe('../regular.txt')
  expect(fs.readFileSync(path.join(tree, 'regular.txt'), 'utf8')).toBe('regular')
  expect(fs.existsSync(path.join(tree, 'new-link'))).toBe(false)
}, 60_000)

windowsTest('requires explicit Git placeholder mode and rejects a real filesystem junction ancestor', () => {
  git(tree, 'config', 'core.symlinks', 'true')
  expect(() => runtime.execute('capture', { task_id: 'task', include_objects: false })).toThrow('LINK_OR_SUBMODULE_UNSUPPORTED')
  git(tree, 'config', 'core.symlinks', 'false')
  const saved = path.join(root, 'saved-links')
  fs.renameSync(path.join(tree, 'links'), saved)
  fs.symlinkSync(saved, path.join(tree, 'links'), 'junction')
  expect(() => runtime.execute('capture', { task_id: 'task', include_objects: false })).toThrow('SYMLINK_UNSUPPORTED')
  expect(fs.readFileSync(path.join(saved, 'reference'), 'utf8')).toBe('../regular.txt')
}, 60_000)
