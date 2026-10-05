import { afterEach, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { captureGitSnapshot, restoreGitSnapshot, collectGitSnapshots } from '../git-snapshots'
import { snapshot } from '../snapshots'
import { git, type Receipt } from '../filesystem'

const roots: string[] = []
afterEach(() => { for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true }) })
function setup() {
  const store = fs.mkdtempSync(path.join(os.tmpdir(), 'tf-git-snapshot-')); roots.push(store)
  const task = path.join(store, 'task'); fs.mkdirSync(task)
  const receipt: Receipt = { task_id: 'test', task_root: task, repositories_input: [], repositories: [] }
  return { store, task, receipt, checkpoint: path.join(store, 'turn-a'), backup: path.join(store, 'turn-a/current-worktree') }
}

test('non-Git workspace preserves initial files and empty directories, deletes newly created files', () => {
  const { store, task, receipt, checkpoint, backup } = setup()
  fs.writeFileSync(path.join(task, 'initial.txt'), 'first round\r\n')
  fs.mkdirSync(path.join(task, 'empty'))
  const first = captureGitSnapshot(receipt, checkpoint, store)
  const warm = captureGitSnapshot(receipt, path.join(store, 'turn-b'), store)
  expect(warm.partitions[0].tree).toBe(first.partitions[0].tree)
  fs.writeFileSync(path.join(task, 'initial.txt'), 'later')
  fs.writeFileSync(path.join(task, 'new.txt'), 'not git added')
  restoreGitSnapshot(receipt, checkpoint, backup, store)
  expect(fs.readFileSync(path.join(task, 'initial.txt'), 'utf8')).toBe('first round\r\n')
  expect(fs.existsSync(path.join(task, 'new.txt'))).toBe(false)
  expect(fs.statSync(path.join(task, 'empty')).isDirectory()).toBe(true)
  expect(fs.existsSync(path.join(task, '.git'))).toBe(false)
}, 60_000)

test('empty boundary removes a later git init and compensation restores its identity', () => {
  const { store, task, receipt, checkpoint, backup } = setup()
  captureGitSnapshot(receipt, checkpoint, store)
  git(task, 'init'); git(task, 'config', 'user.name', 'Test'); git(task, 'config', 'user.email', 'test@example.test')
  fs.writeFileSync(path.join(task, 'new'), 'new'); git(task, 'add', '.'); git(task, 'commit', '-m', 'created')
  const head = git(task, 'rev-parse', 'HEAD')
  restoreGitSnapshot(receipt, checkpoint, backup, store)
  expect(fs.readdirSync(task)).toEqual([])
  restoreGitSnapshot(receipt, backup, path.join(checkpoint, 'recovery'), store)
  expect(git(task, 'rev-parse', 'HEAD')).toBe(head)
  expect(fs.readFileSync(path.join(task, 'new'), 'utf8')).toBe('new')
}, 60_000)

test('unborn Git, ignored large files, and corrupt indexes are handled explicitly', () => {
  const { store, task, receipt, checkpoint, backup } = setup()
  git(task, 'init')
  fs.writeFileSync(path.join(task, '.gitignore'), '.env\n')
  fs.writeFileSync(path.join(task, '.env'), Buffer.alloc(3 * 1024 * 1024, 42))
  const first = captureGitSnapshot(receipt, checkpoint, store)
  fs.unlinkSync(path.join(task, '.env'))
  restoreGitSnapshot(receipt, checkpoint, backup, store)
  expect(fs.statSync(path.join(task, '.env')).size).toBe(3 * 1024 * 1024)
  fs.writeFileSync(path.join(first.partitions[0].git_dir, 'index'), 'corrupt')
  expect(() => captureGitSnapshot(receipt, path.join(store, 'turn-b'), store)).toThrow()
  expect(fs.existsSync(path.join(store, 'turn-b/worktree.json'))).toBe(false)
}, 60_000)

test('seeded packs survive source object deletion without altering its index', () => {
  const { store, task, receipt, checkpoint } = setup()
  git(task, 'init'); git(task, 'config', 'user.name', 'Test'); git(task, 'config', 'user.email', 'test@example.test')
  fs.writeFileSync(path.join(task, 'a'), 'source bytes')
  git(task, 'add', '.'); git(task, 'commit', '-m', 'seed'); git(task, 'gc')
  const index = fs.readFileSync(path.join(task, '.git/index'))
  const saved = captureGitSnapshot(receipt, checkpoint, store), part = saved.partitions[0]
  expect(fs.readFileSync(path.join(task, '.git/index'))).toEqual(index)
  fs.rmSync(path.join(task, '.git/objects'), { recursive: true })
  fs.mkdirSync(path.join(task, '.git/objects'))
  expect(git(task, '--git-dir=' + part.git_dir, 'show', part.tree + ':a')).toBe('source bytes')
  git(task, '--git-dir=' + part.git_dir, 'fsck', '--full', '--no-dangling', part.tree)
}, 60_000)

test('checkpoint cleanup cannot delete the persistent shadow store', () => {
  const { store, receipt } = setup()
  const shadow = path.join(store, 'snapshots/resource_resource/test_task/shadow')
  fs.mkdirSync(shadow, { recursive: true })
  expect(() => snapshot(store, 'resource', receipt, { action: 'cleanup', checkpoint_root: shadow }, '')).toThrow('INVALID_CHECKPOINT_PATH')
  expect(fs.existsSync(shadow)).toBe(true)
})

test('provisioned baseline seeds chat snapshots and missing indexes fail without rebuilding', () => {
  const { store, task, receipt } = setup()
  const initial = snapshot(store, 'resource', receipt, { action: 'create' }, '')
  fs.writeFileSync(path.join(task, 'manual'), 'before first message')
  const turn = snapshot(store, 'resource', receipt, { action: 'create', initial_checkpoint: initial.root }, '')
  expect(turn.worktree.partitions[0].git_dir).toBe(initial.worktree.partitions[0].git_dir)
  expect(turn.worktree.modes.manual).toBeDefined()
  const index = path.join(initial.worktree.partitions[0].git_dir, 'index')
  fs.unlinkSync(index)
  expect(() => snapshot(store, 'resource', receipt, { action: 'create', initial_checkpoint: initial.root }, '')).toThrow('SNAPSHOT_INDEX_MISSING')
  expect(fs.existsSync(index)).toBe(false)
}, 60_000)

test('snapshot collection preserves retained trees and the current index', () => {
  const { store, task, receipt, checkpoint } = setup()
  fs.writeFileSync(path.join(task, 'a'), 'first')
  const first = captureGitSnapshot(receipt, checkpoint, store)
  fs.writeFileSync(path.join(task, 'a'), 'current')
  const removed = path.join(store, 'turn-removed')
  captureGitSnapshot(receipt, removed, store)
  fs.rmSync(removed, { recursive: true })
  collectGitSnapshots(store)
  const part = first.partitions[0]
  expect(git(task, '--git-dir=' + part.git_dir, 'show', part.tree + ':a')).toBe('first')
  const warm = captureGitSnapshot(receipt, path.join(store, 'turn-next'), store)
  expect(git(task, '--git-dir=' + part.git_dir, 'show', warm.partitions[0].tree + ':a')).toBe('current')
}, 60_000)

test.each([false, true])('long Unicode snapshot paths support capture, reuse, restore, and collection (seeded: %s)', (seeded) => {
  const { store: base, task, receipt } = setup()
  const store = path.join(base, '86c8697d-ccea-4a6e-b494-5bbec15f1726_test', '0040c159-98fa-4437-b428-b7c70a0eaab8_系统层：用户权限、Claude Runtime 节点管理、MCP 服务网关与操作')
  const checkpoint = path.join(store, 'turn-a')
  const original = Buffer.from([65, 13, 10, 0, 255])
  if (seeded) { git(task, 'init'); git(task, 'config', 'user.name', 'Test'); git(task, 'config', 'user.email', 'test@example.test') }
  fs.writeFileSync(path.join(task, 'a'), original)
  if (seeded) { git(task, 'add', '.'); git(task, 'commit', '-m', 'seed') }
  const sourceIndex = seeded ? fs.readFileSync(path.join(task, '.git/index')) : null
  const first = captureGitSnapshot(receipt, checkpoint, store)
  expect(Buffer.byteLength(first.partitions[0].git_dir, 'utf8')).toBeGreaterThan(220)
  fs.writeFileSync(path.join(task, 'a'), 'second turn')
  const removed = path.join(store, 'turn-removed')
  const second = captureGitSnapshot(receipt, removed, store)
  expect(second.partitions[0].git_dir).toBe(first.partitions[0].git_dir)
  fs.writeFileSync(path.join(task, 'new'), 'created later')
  restoreGitSnapshot(receipt, checkpoint, path.join(checkpoint, 'current-worktree'), store)
  expect(fs.readFileSync(path.join(task, 'a'))).toEqual(original)
  expect(fs.existsSync(path.join(task, 'new'))).toBe(false)
  if (sourceIndex) expect(fs.readFileSync(path.join(task, '.git/index'))).toEqual(sourceIndex)
  fs.rmSync(removed, { recursive: true })
  collectGitSnapshots(store)
  const warm = captureGitSnapshot(receipt, path.join(store, 'turn-next'), store)
  expect(warm.partitions[0].tree).toBe(first.partitions[0].tree)
}, 60_000)
