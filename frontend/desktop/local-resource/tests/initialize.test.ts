import { afterEach, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { initialize } from '../initialize'
import { git, type Receipt } from '../filesystem'

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) {
    if (!root.startsWith(path.join(tmpdir(), 'tf-initialize-'))) throw new Error('Invalid test path')
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('dual worktrees discard a resolved merge, ignored output and root output incrementally', () => {
  const root = fs.mkdtempSync(path.join(tmpdir(), 'tf-initialize-'))
  roots.push(root)
  const task = path.join(root, 'task'); fs.mkdirSync(task)
  const repositories = ['a', 'b'].map(name => {
    const upstream = path.join(root, name), local = path.join(task, name)
    fs.mkdirSync(upstream)
    git(upstream, 'init', '-b', 'main')
    git(upstream, 'config', 'user.name', 'Test'); git(upstream, 'config', 'user.email', 'test@example.com')
    fs.writeFileSync(path.join(upstream, 'stable.txt'), 'unchanged\n')
    fs.writeFileSync(path.join(upstream, 'edit.txt'), 'base\n')
    fs.writeFileSync(path.join(upstream, '.gitignore'), 'dist/\n')
    git(upstream, 'add', '.'); git(upstream, 'commit', '-m', 'base')
    git(root, 'clone', upstream, local)
    git(local, 'config', 'user.name', 'Test'); git(local, 'config', 'user.email', 'test@example.com')
    fs.writeFileSync(path.join(local, 'edit.txt'), 'agent\n')
    fs.writeFileSync(path.join(local, 'generated.txt'), 'output\n')
    git(local, 'add', '.'); git(local, 'commit', '-m', 'agent')
    fs.writeFileSync(path.join(upstream, 'edit.txt'), 'remote\n')
    git(upstream, 'add', '.'); git(upstream, 'commit', '-m', 'remote')
    git(local, 'fetch', 'origin')
    expect(() => git(local, 'merge', 'origin/main')).toThrow()
    fs.writeFileSync(path.join(local, 'edit.txt'), 'resolved conflict\n')
    git(local, 'add', '.'); git(local, 'commit', '-m', 'resolved')
    fs.mkdirSync(path.join(local, 'dist')); fs.writeFileSync(path.join(local, 'dist/output'), 'build')
    return { repository_id: name, rel_path: name, branch_name: 'main', configured_git_url: upstream }
  })
  const receipt = { task_root: task, repositories } as Receipt
  const before = repositories.map(repo => fs.statSync(path.join(task, repo.rel_path, 'stable.txt')).mtimeMs)
  fs.writeFileSync(path.join(task, 'RESULT.md'), 'generated')
  fs.mkdirSync(path.join(task, '.sdd/spec'), { recursive: true })
  fs.writeFileSync(path.join(task, '.sdd/spec/input'), 'uploaded input')
  for (const [index, repo] of repositories.entries()) {
    const repository = { ...repo, branch: repo.branch_name }
    const fetched = initialize(receipt, { action: 'fetch', repository })
    const result = initialize(receipt, { action: 'reset', repository: { ...repository, target: fetched.target } })
    expect(result.completed).toBe(true)
    const local = path.join(task, repo.rel_path)
    expect(git(local, 'rev-parse', 'HEAD')).toBe(git(repo.configured_git_url, 'rev-parse', 'HEAD'))
    expect(fs.statSync(path.join(local, 'stable.txt')).mtimeMs).toBe(before[index]!)
    expect(fs.readFileSync(path.join(local, 'edit.txt'), 'utf8').trim()).toBe('remote')
    expect(fs.existsSync(path.join(local, 'generated.txt'))).toBe(false)
    expect(fs.existsSync(path.join(local, 'dist'))).toBe(false)
    // Replaying a step after a lost acknowledgement is safe.
    expect(initialize(receipt, { action: 'reset', repository: { ...repository, target: fetched.target } }).completed).toBe(true)
  }
  initialize(receipt, { action: 'clean', protected: ['.sdd/spec'] })
  expect(fs.existsSync(path.join(task, 'RESULT.md'))).toBe(false)
  expect(fs.readFileSync(path.join(task, '.sdd/spec/input'), 'utf8')).toBe('uploaded input')
}, 60_000)
