import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
import { registerGitIpc } from '../../../../electron/ipc/git'

const handlers = vi.hoisted(() => new Map<string, (...args: any[]) => Promise<any>>())
vi.mock('electron', () => ({ dialog: {}, ipcMain: { handle: (name: string, handler: (...args: any[]) => Promise<any>) => handlers.set(name, handler) } }))
let root: string, repo: string, sha: string
const git = (...args: string[]) => execFileSync('git', args, { cwd: repo, encoding: 'utf8', windowsHide: true }).trim()
beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'tf-patch-map-')); repo = join(root, 'fork'); mkdirSync(repo)
  git('init', '-b', 'main'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.com'); git('config', 'core.autocrlf', 'false')
  writeFileSync(join(repo, 'code.txt'), 'base\n'); git('add', '.'); git('commit', '-m', 'base'); sha = git('rev-parse', 'HEAD')
  registerGitIpc()
})
afterEach(() => { rmSync(root, { recursive: true, force: true }); handlers.clear() })
const prepare = (baseSha = sha) => handlers.get('sdd:git:prepare-patch-worktree')!(null, {
  repoPath: repo, remoteUrl: 'https://github.com/LiZheng0613/sdd-tdd-workflow.git', baseSha, baseBranch: 'server-only-branch', branch: 'sdd/task-1/v1',
})

it('creates a worktree from an available base in a dirty fork without contacting the mismatched remote', async () => {
  // Unreachable remote proves the existing base can be used entirely offline.
  git('remote', 'add', 'origin', 'https://127.0.0.1:1/WBRume/sdd-tdd-workflow.git')
  writeFileSync(join(repo, 'code.txt'), 'personal edits\n')
  const result = await prepare()
  expect(readFileSync(join(result.path, 'code.txt'), 'utf8')).toBe('base\n')
  expect(readFileSync(join(repo, 'code.txt'), 'utf8')).toBe('personal edits\n')
  expect(git('branch', '--show-current')).toBe('main')
  expect(git('rev-parse', 'HEAD')).toBe(sha)
})

it('rejects a missing base before creating a branch or directory', async () => {
  await expect(prepare('f'.repeat(40))).rejects.toThrow('缺少补丁基准 commit')
  expect(git('branch', '--list', 'sdd/task-1/v1')).toBe('')
  expect(readdirSync(root)).toEqual(['fork'])
})

it('fetches the base from a configured fork even when the server branch does not exist there', async () => {
  const remote = join(root, 'remote.git')
  git('clone', '--bare', repo, remote)
  git('remote', 'add', 'personal', remote)
  writeFileSync(join(repo, 'code.txt'), 'remote base\n'); git('add', '.'); git('commit', '-m', 'remote base')
  const remoteSha = git('rev-parse', 'HEAD'); git('push', 'personal', 'main')
  // A second clone has only the initial commit, and fetches exclusively from personal.
  git('reset', '--hard', sha)
  const second = join(root, 'second'); git('clone', '--no-local', '--single-branch', repo, second)
  repo = second; git('config', 'core.autocrlf', 'false'); git('remote', 'set-url', 'origin', remote)
  const result = await prepare(remoteSha)
  expect(readFileSync(join(result.path, 'code.txt'), 'utf8')).toBe('remote base\n')
  expect(git('rev-parse', 'HEAD')).toBe(sha)
}, 15000)
