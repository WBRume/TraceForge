import { afterEach, beforeEach, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { prepareTaskWorktree } from '../collaboration-prepare'
import { CollaborationRuntime } from '../collaboration'
import { git, resolved } from '../filesystem'

let root: string, repo: string, base: string
beforeEach(() => {
  root = fs.mkdtempSync(path.join(tmpdir(), 'tf-init-'))
  repo = path.join(root, 'source'); fs.mkdirSync(repo)
  git(repo, 'init', '-b', 'main'); git(repo, 'config', 'user.name', 'Test'); git(repo, 'config', 'user.email', 'test@example.com')
  git(repo, 'config', 'core.autocrlf', 'false'); git(repo, 'config', 'core.longpaths', 'false')
  fs.writeFileSync(path.join(repo, 'source.txt'), 'initial bytes')
  git(repo, 'add', '.'); git(repo, 'commit', '-m', 'base')
  git(repo, 'remote', 'add', 'origin', 'https://example.com/repo.git')
  base = git(repo, 'rev-parse', 'HEAD')
})
afterEach(() => { fs.rmSync(root, { recursive: true, force: true }) })
function options() {
  return { state: path.join(root, 'state'), task_id: 'task', task_repository_id: 'repo', target: path.join(root, 'task', 'repo'),
    branch: 'traceforge/sync/task/repo', base_commit_sha: base, repo_root: resolved(repo), common_git_dir: resolved(path.join(repo, '.git')) }
}

test('resumes its owned branch and empty worktree after interrupted initialization', () => {
  const input = options()
  expect(() => prepareTaskWorktree({ ...input, afterWorktree: () => { throw Error('interrupted') } })).toThrow('interrupted')
  expect(fs.existsSync(path.join(input.target, 'source.txt'))).toBe(false)
  prepareTaskWorktree(input)
  expect(fs.readFileSync(path.join(input.target, 'source.txt'), 'utf8')).toBe('initial bytes')
  expect(git(input.target, 'branch', '--show-current')).toBe(input.branch)
  expect(git(repo, 'branch', '--show-current')).toBe('main')
}, 60_000)

test('refuses a pre-existing user branch and preserves edits in an interrupted checkout', () => {
  const input = options()
  git(repo, 'branch', input.branch)
  expect(() => prepareTaskWorktree(input)).toThrow('OWNERSHIP_CONFLICT')
  expect(git(repo, 'rev-parse', input.branch)).toBe(base)
  const owned = { ...input, branch: 'traceforge/sync/task/owned' }
  expect(() => prepareTaskWorktree({ ...owned, afterWorktree: () => { throw Error('interrupted') } })).toThrow('interrupted')
  fs.writeFileSync(path.join(owned.target, 'source.txt'), 'human edit while preparing')
  expect(() => prepareTaskWorktree(owned)).toThrow('LOCAL_EDITS')
  expect(fs.readFileSync(path.join(owned.target, 'source.txt'), 'utf8')).toBe('human edit while preparing')
  expect(git(repo, 'rev-parse', input.branch)).toBe(base)
}, 60_000)

test('prepares and captures deeply nested Windows worktrees without changing repository longpaths configuration', () => {
  const name = 'nested/' + 'path-segment-'.repeat(4) + '/'.repeat(1) + 'file-name-'.repeat(5) + '.txt'
  fs.mkdirSync(path.dirname(path.join(repo, name)), { recursive: true }); fs.writeFileSync(path.join(repo, name), 'deep content')
  git(repo, '-c', 'core.longpaths=true', 'add', '.'); git(repo, 'commit', '-m', 'deep file')
  const runtime = new CollaborationRuntime(path.join(root, 'state'), () => [root])
  const workspace = path.join(root, 'workspace-name-'.repeat(7))
  try {
    const state = runtime.execute('prepare', { task_id: 'long-path-task', binding_id: 'binding', workspace_root: workspace,
      repositories: [{ task_repository_id: 'repo', repository_id: 'repo', repo_url: 'https://example.com/repo.git', repo_slug: 'repo',
        rel_path: 'repo', branch_name: 'main', base_commit_sha: git(repo, 'rev-parse', 'HEAD'), local_path: repo }],
      session_generation: 1, session_revision: 1, repository_set_digest: 'set', workspace_revision: 1 })
    const absolute = path.join(state.repositories[0].local_worktree_path, name)
    expect(absolute.length).toBeGreaterThan(260)
    expect(fs.readFileSync(absolute, 'utf8')).toBe('deep content')
    expect(runtime.execute('capture', { task_id: 'long-path-task', include_objects: false }).manifest.repositories[0].files.some((file: any) => file.path === name)).toBe(true)
    expect(git(repo, 'config', '--bool', 'core.longpaths')).toBe('false')
  } finally { runtime.close() }
}, 60_000)
