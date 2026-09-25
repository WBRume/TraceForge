import * as fs from 'node:fs'
import * as path from 'node:path'
import { randomUUID } from 'node:crypto'
import { atomic, child, fail, git, gitRaw, hash, inside, readJson, writeJson, type Receipt } from './filesystem'
import { captureProvider, cleanupSession, forkSession, restoreProvider } from './provider'

const excludedDirs = new Set(['node_modules', 'dist', 'build', 'coverage', '.next', '.nuxt', '.output', '.vite', '.cache', '.turbo', '.parcel-cache', '.svelte-kit', 'target', '.gradle', '.venv', 'venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox', '.nox', 'htmlcov'])
type Entry = { hash?: string; link?: string; mode: number }
type GitState = { relative: string; head: string; branch: string; index: string | null; common: string }
interface Snapshot { version: number; manifest: Record<string, Entry>; repositories: GitState[] }

// Leaf symlinks are captured as links; parent links are never traversed.
function safe(root: string, relative: string) {
  if (!relative || relative.includes(':') || relative.includes('\\') || relative.split('/').some(p => !p || ['.', '..', '.git'].includes(p.toLowerCase()))) fail('INVALID_SNAPSHOT_PATH')
  const target = path.join(root, relative)
  inside(path.dirname(target), [root])
  let parent = path.dirname(target)
  while (parent !== root) {
    if (fs.existsSync(parent) && fs.lstatSync(parent).isSymbolicLink()) fail('SNAPSHOT_LINK_PARENT')
    parent = path.dirname(parent)
  }
  return target
}
function objectFile(objects: string, digest: string) { if (!/^[a-f0-9]{64}$/.test(digest)) fail('INVALID_OBJECT_HASH'); return child(objects, digest) }
function put(objects: string, data: Buffer) {
  const digest = hash(data), file = objectFile(objects, digest)
  if (!fs.existsSync(file)) atomic(file, data)
  return digest
}
function get(objects: string, digest: string) {
  const data = fs.readFileSync(objectFile(objects, digest))
  if (hash(data) !== digest) fail('SNAPSHOT_OBJECT_CORRUPT')
  return data
}
function capture(receipt: Receipt, destination: string, objects: string): Snapshot {
  const tracked = new Set<string>(), repositories: GitState[] = []
  for (const repo of receipt.repositories) {
    const cwd = child(receipt.task_root, repo.rel_path)
    for (const file of gitRaw(cwd, ['ls-files', '-z']).toString().split('\0').filter(Boolean)) tracked.add(repo.rel_path + '/' + file)
    const index = path.resolve(cwd, git(cwd, 'rev-parse', '--git-path', 'index'))
    repositories.push({ relative: repo.rel_path, head: git(cwd, 'rev-parse', 'HEAD'), branch: gitRaw(cwd, ['symbolic-ref', '-q', '--short', 'HEAD'], {}, false).toString().trim(), index: fs.existsSync(index) ? put(objects, fs.readFileSync(index)) : null, common: path.resolve(cwd, git(cwd, 'rev-parse', '--git-common-dir')) })
  }
  const manifest: Record<string, Entry> = {}
  function scan(directory: string, prefix = '') {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.name.toLowerCase() === '.git') continue
      const relative = prefix ? prefix + '/' + entry.name : entry.name
      const include = tracked.has(relative) || [...tracked].some(file => file.startsWith(relative + '/'))
      if (!include && (relative.split('/').some(part => excludedDirs.has(part)) || /\.(pyc|pyo|class)$/.test(entry.name))) continue
      const file = safe(receipt.task_root, relative), stat = fs.lstatSync(file)
      if (entry.isSymbolicLink()) manifest[relative] = { link: fs.readlinkSync(file), mode: stat.mode }
      else if (entry.isDirectory()) scan(file, relative)
      else if (entry.isFile()) manifest[relative] = { hash: put(objects, fs.readFileSync(file)), mode: stat.mode }
    }
  }
  scan(receipt.task_root)
  const metadata = { version: 3, manifest, repositories }
  writeJson(path.join(destination, 'worktree.json'), metadata)
  return metadata
}
function restore(receipt: Receipt, checkpoint: string, backup: string, objects: string) {
  const saved = readJson<Snapshot>(path.join(checkpoint, 'worktree.json'))
  if (saved.version !== 3) fail('SNAPSHOT_VERSION_UNSUPPORTED')
  for (const [relative, entry] of Object.entries(saved.manifest)) { safe(receipt.task_root, relative); if (entry.hash) get(objects, entry.hash) }
  for (const repo of saved.repositories) {
    const cwd = child(receipt.task_root, repo.relative)
    if (path.resolve(cwd, git(cwd, 'rev-parse', '--git-common-dir')) !== repo.common) fail('SNAPSHOT_REPOSITORY_CHANGED')
    if (repo.index) get(objects, repo.index)
  }
  const current = capture(receipt, backup, objects)
  for (const relative of Object.keys(current.manifest).sort((a, b) => b.length - a.length)) {
    if (!(relative in saved.manifest)) fs.unlinkSync(safe(receipt.task_root, relative))
  }
  for (const [relative, entry] of Object.entries(saved.manifest)) {
    const file = safe(receipt.task_root, relative)
    // File/directory transitions remove only empty directories; excluded data is retained.
    function removeEmpty(directory: string) {
      for (const name of fs.readdirSync(directory)) {
        const nested = path.join(directory, name)
        if (!fs.lstatSync(nested).isDirectory() || fs.lstatSync(nested).isSymbolicLink()) fail('RESTORE_DIRECTORY_NOT_EMPTY')
        removeEmpty(nested)
      }
      fs.rmdirSync(directory)
    }
    if (fs.existsSync(file) && fs.lstatSync(file).isDirectory() && !fs.lstatSync(file).isSymbolicLink()) removeEmpty(file)
    try { if (fs.lstatSync(file).isSymbolicLink()) fs.unlinkSync(file) } catch (error: any) { if (error.code !== 'ENOENT') throw error }
    if (entry.link !== undefined) { fs.rmSync(file, { force: true }); fs.mkdirSync(path.dirname(file), { recursive: true }); fs.symlinkSync(entry.link, file) }
    else { atomic(file, get(objects, entry.hash!)); fs.chmodSync(file, entry.mode & 0o777) }
  }
  for (const repo of saved.repositories) {
    const cwd = child(receipt.task_root, repo.relative)
    if (repo.branch) { git(cwd, 'symbolic-ref', 'HEAD', 'refs/heads/' + repo.branch); git(cwd, 'update-ref', 'refs/heads/' + repo.branch, repo.head) }
    else git(cwd, 'update-ref', '--no-deref', 'HEAD', repo.head)
    const index = path.resolve(cwd, git(cwd, 'rev-parse', '--git-path', 'index'))
    if (repo.index) atomic(index, get(objects, repo.index)); else fs.rmSync(index, { force: true })
  }
}
export function snapshot(state: string, resourceId: string, receipt: Receipt, payload: any, dshRoot: string): any {
  const owner = path.join(state, 'snapshots', resourceId + '_resource', receipt.task_id + '_task')
  const objects = path.join(owner, 'objects')
  if (!['opencode', 'dsh'].includes(payload.provider || 'opencode')) fail('UNSUPPORTED_LOCAL_PROVIDER')
  if (payload.action === 'create') {
    const root = path.join(owner, 'turn-' + randomUUID())
    const worktree = capture(receipt, root, objects)
    const provider = captureProvider(dshRoot, root, payload.provider || 'opencode', payload.session_id || null)
    return { root, worktree, provider }
  }
  const checkpoint = inside(payload.checkpoint_root, [owner])
  if (checkpoint === path.resolve(owner) || checkpoint === objects || checkpoint.startsWith(objects + path.sep)) fail('INVALID_CHECKPOINT_PATH')
  switch (payload.action) {
    case 'exists': return { exists: fs.existsSync(path.join(checkpoint, 'worktree.json')) }
    case 'restore_worktree': {
      const backup = inside(payload.backup_path, [owner])
      if (backup === checkpoint || backup === path.resolve(owner) || backup.startsWith(objects)) fail('INVALID_BACKUP_PATH')
      restore(receipt, checkpoint, backup, objects); break
    }
    case 'backup_provider': return captureProvider(dshRoot, checkpoint, payload.provider, payload.session_id, true)
    case 'restore_provider': restoreProvider(dshRoot, checkpoint); break
    case 'restore_provider_backup': restoreProvider(dshRoot, checkpoint, true); break
    case 'fork_dsh': return { session_id: forkSession(dshRoot, payload.session_id, receipt.task_root) }
    case 'cleanup_dsh': cleanupSession(dshRoot, payload.session_id); break
    case 'cleanup': fs.rmSync(checkpoint, { recursive: true, force: true }); break
    default: fail('Unsupported snapshot action')
  }
  return { ok: true }
}
