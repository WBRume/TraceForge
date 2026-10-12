import { afterEach, beforeEach, expect, spyOn, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { captureCollaborationGit } from '../collaboration-git'
import { CollaborationIndex } from '../collaboration-index'
import { captureGitSnapshot, collectGitSnapshots, shadowGit } from '../git-snapshots'
import { SyncObjects, type LocalRepository } from '../collaboration-store'
import { git, gitRaw, hash, resolved, type Receipt } from '../filesystem'

let root: string, directory: string, repo: LocalRepository, objects: SyncObjects, task: { task_id: string; task_root: string }
beforeEach(() => {
  root = fs.mkdtempSync(path.join(tmpdir(), 'tf-collaboration-git-'))
  task = { task_id: 'task', task_root: path.join(root, 'task') }
  directory = path.join(task.task_root, 'repo'); fs.mkdirSync(directory, { recursive: true })
  git(directory, 'init', '-b', 'main'); git(directory, 'config', 'user.name', 'Test'); git(directory, 'config', 'user.email', 'test@example.com')
  git(directory, 'config', 'core.autocrlf', 'false')
  fs.writeFileSync(path.join(directory, 'source.txt'), 'before')
  fs.mkdirSync(path.join(directory, 'nested')); fs.writeFileSync(path.join(directory, 'nested/other.txt'), 'unchanged')
  git(directory, 'add', '.'); git(directory, 'commit', '-m', 'fixture')
  repo = { task_repository_id: 'repo', repository_id: 'repo', repo_url: 'https://example.com/repo.git', repo_slug: 'repo', rel_path: 'repo',
    branch_name: 'main', base_commit_sha: git(directory, 'rev-parse', 'HEAD'), local_path: directory, configured_git_url: 'https://example.com/repo.git',
    local_worktree_path: resolved(directory), mapped_repo_root: resolved(directory), common_git_dir: resolved(path.join(directory, '.git')), task_branch: 'main', files: [] }
  objects = new SyncObjects(path.join(root, 'state', 'collaboration'))
}, 60_000)
afterEach(() => { fs.rmSync(root, { recursive: true, force: true }) })
const capture = (changedPaths?: ReadonlySet<string>) => captureCollaborationGit(repo, objects, task, false, changedPaths)

test('warm native journal updates only named Git paths and survives idle time, deletion and directory rename', async () => {
  const index = new CollaborationIndex()
  const watch = fs.watch
  let notify: fs.WatchListener<string> | undefined
  const watcher = spyOn(fs, 'watch').mockImplementation(((file: fs.PathLike, options: fs.WatchOptionsWithStringEncoding, listener: fs.WatchListener<string>) => {
    notify = listener
    return watch(file, options, listener)
  }) as typeof fs.watch)
  try {
    index.scan(repo, objects, true, false, task)
    fs.writeFileSync(path.join(directory, 'source.txt'), 'edited')
    fs.utimesSync(path.join(directory, 'source.txt'), 1700000000, 1700000000)
    await index.flush(); index.beginOperation()
    const next = index.scan(repo, objects, true, false, task)
    expect(next.files.find(file => file.path === 'source.txt')?.sha256).toBe(hash('edited'))
    expect(index.measurements()[0]).toMatchObject({ kind: 'git-delta', full_inventory: false, paths_checked: 1 })
    await index.flush(); index.beginOperation()
    index.scan(repo, objects, true, false, task)
    expect(['cached', 'git-delta']).toContain(index.measurements()[0].kind)
    expect(index.measurements()[0].new_blobs).toBe(0)
    fs.unlinkSync(path.join(directory, 'source.txt'))
    fs.renameSync(path.join(directory, 'nested'), path.join(directory, 'renamed'))
    await index.flush(); index.beginOperation()
    const renamed = index.scan(repo, objects, true, false, task)
    expect(renamed.files.map(file => file.path)).toEqual(['renamed/other.txt'])
    expect(index.measurements()[0].kind).toBe('git-delta')
    fs.writeFileSync(path.join(directory, '.gitignore'), 'renamed/\n')
    await index.flush(); index.beginOperation()
    const excluded = index.scan(repo, objects, true, false, task)
    expect(index.measurements()[0].full_inventory).toBe(true)
    expect(excluded.files.map(file => file.path)).toEqual(['.gitignore'])
    // Bun stores fs.watch's callback outside EventEmitter listeners; invoke the
    // actual registered callback to emulate a native event with no path.
    notify!('rename', null)
    await index.flush(); index.beginOperation()
    index.scan(repo, objects, true, false, task)
    expect(index.measurements()[0].full_inventory).toBe(true)
  } finally { index.close(); watcher.mockRestore() }
}, 60_000)

test('Git snapshots reuse immutable OIDs, import only changed blobs, and preserve business Git state', () => {
  const index = fs.readFileSync(path.join(directory, '.git/index')), head = git(directory, 'rev-parse', 'HEAD'), refs = git(directory, 'show-ref')
  const initial = capture(), warm = capture()
  expect(initial.metrics.new_blobs).toBe(2)
  expect(warm.metrics.new_blobs).toBe(0); expect(warm.metrics.new_blob_bytes).toBe(0)
  fs.writeFileSync(path.join(directory, 'source.txt'), 'edited')
  const edited = capture()
  expect(edited.metrics.new_blobs).toBe(1); expect(edited.metrics.new_blob_bytes).toBe(6)
  expect(edited.snapshot.files.find(file => file.path === 'source.txt')?.sha256).toBe(hash('edited'))
  expect(fs.readFileSync(path.join(directory, '.git/index'))).toEqual(index)
  expect(git(directory, 'rev-parse', 'HEAD')).toBe(head); expect(git(directory, 'show-ref')).toBe(refs)
  expect(fs.existsSync(path.join(objects.state, 'objects'))).toBe(false)
  objects = new SyncObjects(objects.state)
  expect(capture().metrics.new_blobs).toBe(0)
  expect(objects.get(hash('edited')).toString()).toBe('edited')
}, 60_000)

test('watcher hints refresh only affected paths despite exactly restored mtime', () => {
  const file = path.join(directory, 'source.txt')
  fs.utimesSync(file, 1_700_000_000, 1_700_000_000); capture()
  const before = fs.statSync(file, { bigint: true })
  fs.writeFileSync(file, 'edited'); fs.utimesSync(file, 1_700_000_000, 1_700_000_000)
  expect(fs.statSync(file, { bigint: true }).mtimeNs).toBe(before.mtimeNs)
  const result = capture(new Set(['source.txt']))
  expect(result.snapshot.files.find(entry => entry.path === 'source.txt')?.sha256).toBe(hash('edited'))
  expect(result.metrics.forced_content_checks).toBe(0)
}, 60_000)

test('reuses the initial rollback shadow while export excludes ignored, env and private files; GC retains collaboration trees', () => {
  fs.writeFileSync(path.join(directory, '.gitignore'), 'ignored.txt\n')
  fs.writeFileSync(path.join(directory, 'ignored.txt'), 'ignored')
  fs.writeFileSync(path.join(directory, '.env'), 'private')
  fs.mkdirSync(path.join(directory, '.sdd')); fs.writeFileSync(path.join(directory, '.sdd/private'), 'private control')
  const owner = path.join(root, 'state/snapshots/resource_resource/task_task'), checkpoint = path.join(owner, 'turn-initial')
  const receipt: Receipt = { task_id: task.task_id, task_root: task.task_root, repositories: [], repositories_input: [] }
  const initial = captureGitSnapshot(receipt, checkpoint, owner)
  const exported = capture()
  expect(exported.part.git_dir).toBe(initial.partitions.find(part => part.relative === 'repo')!.git_dir)
  expect(exported.snapshot.files.map(file => file.path).sort()).toEqual(['.gitignore', 'nested/other.txt', 'source.txt'])
  expect(objects.git.check([{ sha256: hash('private') }, { sha256: hash('ignored') }])).toEqual([hash('private'), hash('ignored')])
  collectGitSnapshots(owner)
  expect(shadowGit(exported.part.git_dir, ['cat-file', '-t', exported.part.tree]).toString().trim()).toBe('tree')
  expect(objects.get(hash('before')).toString()).toBe('before')
}, 60_000)

test('captures raw binary and CRLF bytes with attributes disabled, deletions and untracked additions', () => {
  fs.writeFileSync(path.join(directory, '.gitattributes'), '* text eol=lf filter=invalid\n')
  git(directory, 'config', 'filter.invalid.clean', 'command-that-must-never-run')
  const bytes = Buffer.from([0, 255, 13, 10, 128])
  fs.writeFileSync(path.join(directory, 'binary.dat'), bytes)
  fs.writeFileSync(path.join(directory, 'line.txt'), 'line\r\n')
  fs.unlinkSync(path.join(directory, 'source.txt'))
  const result = capture()
  expect(result.snapshot.files.some(file => file.path === 'source.txt')).toBe(false)
  expect(objects.get(hash(bytes))).toEqual(bytes)
  expect(objects.get(hash('line\r\n')).toString()).toBe('line\r\n')
}, 60_000)

test('refuses parent junctions before capturing bytes outside the repository', () => {
  const saved = path.join(root, 'parked')
  fs.renameSync(path.join(directory, 'nested'), saved)
  fs.symlinkSync(saved, path.join(directory, 'nested'), process.platform === 'win32' ? 'junction' : 'dir')
  expect(() => capture()).toThrow('SYMLINK_UNSUPPORTED')
  expect(fs.readFileSync(path.join(saved, 'other.txt'), 'utf8')).toBe('unchanged')
}, 60_000)

test('lazily migrates legacy raw objects without removing frozen captures or backup bytes', () => {
  const digest = hash('legacy'), legacy = path.join(objects.state, 'objects', digest.slice(0, 2), digest)
  fs.mkdirSync(path.dirname(legacy), { recursive: true }); fs.writeFileSync(legacy, 'legacy')
  expect(objects.get(digest).toString()).toBe('legacy')
  expect(fs.readFileSync(legacy, 'utf8')).toBe('legacy')
  objects = new SyncObjects(objects.state)
  expect(objects.get(digest).toString()).toBe('legacy')
  expect(objects.git.check([{ sha256: digest, size: 6 }])).toEqual([])
}, 60_000)

test('ambient Git overrides cannot redirect private capture into the business index or object store', () => {
  const original = fs.readFileSync(path.join(directory, '.git/index')), head = git(directory, 'rev-parse', 'HEAD'), refs = git(directory, 'show-ref')
  const ambient: Record<string, string> = { GIT_DIR: path.join(directory, '.git'), GIT_WORK_TREE: directory,
    GIT_INDEX_FILE: path.join(directory, '.git/index'), GIT_COMMON_DIR: path.join(directory, '.git'),
    GIT_OBJECT_DIRECTORY: path.join(directory, '.git/objects'), GIT_ALTERNATE_OBJECT_DIRECTORIES: path.join(root, 'missing'),
    GIT_NAMESPACE: 'unexpected', GIT_PREFIX: 'wrong/' }
  const prior = Object.fromEntries(Object.keys(ambient).map(key => [key, process.env[key]]))
  try {
    Object.assign(process.env, ambient)
    fs.writeFileSync(path.join(directory, 'source.txt'), 'edited')
    expect(capture().snapshot.files.find(file => file.path === 'source.txt')?.sha256).toBe(hash('edited'))
    expect(fs.readFileSync(path.join(directory, '.git/index'))).toEqual(original)
    expect(git(directory, 'rev-parse', 'HEAD')).toBe(head); expect(git(directory, 'show-ref')).toBe(refs)
    const temporaryIndex = path.join(root, 'explicit-index')
    gitRaw(directory, ['read-tree', 'HEAD'], { GIT_INDEX_FILE: temporaryIndex })
    expect(fs.existsSync(temporaryIndex)).toBe(true)
    expect(fs.readFileSync(path.join(directory, '.git/index'))).toEqual(original)
  } finally {
    for (const [key, value] of Object.entries(prior)) if (value === undefined) delete process.env[key]; else process.env[key] = value
  }
}, 60_000)
