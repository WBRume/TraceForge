import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { randomUUID } from 'node:crypto'
import { gitRaw } from './filesystem'
import { validateRepositoryIdentity, type LocalRepository, type SyncRepository, type SyncObjects } from './collaboration-store'
import { captureAllowlist, captureCollaborationGit, disconnectedChanges, type GitScanMetrics } from './collaboration-git'
import { prefetchCapture, reserveCaptureBudget, type CaptureBudget, type PreparedCapture } from './collaboration-prefetch'
import type { Part } from './git-snapshots'

interface RepositoryIndex { taskId: string; root: string; watcher?: fs.FSWatcher; prepared?: PreparedCapture; revision: number; dirty: boolean; gap: boolean; changedPaths: Set<string>; verifiedAt: number; snapshot?: SyncRepository; part?: Part; indexPath: string; indexStamp: string; controlStamp?: string; suspended?: boolean; barrier?: { name: string; done: () => void } }
function stamp(file: string) { try { const s = fs.statSync(file); return `${s.ino}:${s.size}:${s.mtimeMs}:${s.ctimeMs}` } catch { return '' } }
const controls = (repo: LocalRepository, index: RepositoryIndex) => [path.join(repo.common_git_dir, 'config'), path.join(repo.common_git_dir, 'info/exclude'), ...(index.part ? [path.join(index.part.git_dir, 'index')] : [])].map(stamp).join('|')

/** Git owns the index; watcher paths supplement its stat check for restored mtimes. */
export class CollaborationIndex {
  onChanged?: (taskId: string) => void
  private readonly notifications = new Map<string, ReturnType<typeof setTimeout>>()
  private readonly indexes = new Map<string, RepositoryIndex>()
  private scans: (GitScanMetrics & { task_repository_id: string })[] = []
  private flushed = new Set<string>()
  hasChanges(taskId: string) {
    for (const index of this.indexes.values()) if (index.taskId === taskId && (index.dirty || index.gap)) return true
    return false
  }
  beginOperation() { this.scans = [] }
  measurements() { return this.scans }
  private notify(taskId: string) {
    if (!this.onChanged || this.notifications.has(taskId)) return
    // Coalesce native file bursts without delaying a continuously editing user.
    this.notifications.set(taskId, setTimeout(() => {
      this.notifications.delete(taskId)
      this.onChanged?.(taskId)
    }, 150))
  }
  private cancelNotification(taskId: string) {
    clearTimeout(this.notifications.get(taskId)); this.notifications.delete(taskId)
  }
  /** A witnessed marker drains queued native events before the immutable cut. */
  async flush(taskId?: string) {
    this.flushed.clear()
    await Promise.all([...this.indexes].map(async ([key, index]) => {
      if (!index.watcher || (taskId && index.taskId !== taskId)) return
      const name = '.traceforge-sync-barrier-' + randomUUID(), file = path.join(index.root, name)
      await new Promise<void>(resolve => {
        const finish = (ok: boolean) => { clearTimeout(timer); index.barrier = undefined; if (ok) this.flushed.add(key); else index.gap = true; resolve() }
        const timer = setTimeout(() => finish(false), 500)
        index.barrier = { name, done: () => finish(true) }
        try { fs.writeFileSync(file, '') } catch { finish(false) }
      })
      fs.rmSync(file, { force: true })
    }))
  }
  private observe(repo: LocalRepository, taskId: string) {
    const key = JSON.stringify([taskId, repo.task_repository_id, repo.local_worktree_path])
    let index = this.indexes.get(key)
    if (!index) {
      const indexPath = gitRaw(repo.local_worktree_path, ['rev-parse', '--path-format=absolute', '--git-path', 'index']).toString().trim()
      index = { taskId, root: repo.local_worktree_path, revision: 0, dirty: true, gap: true, changedPaths: new Set(), verifiedAt: 0, indexPath, indexStamp: stamp(indexPath) }
      this.indexes.set(key, index)
    }
    const resuming = index.suspended
    if (!index.watcher && (!index.snapshot || resuming)) {
      const watched = index
      try {
        index.watcher = fs.watch(repo.local_worktree_path, { recursive: true, persistent: false }, (_kind, name) => {
          if (watched.barrier && name?.toString() === watched.barrier.name) { watched.barrier.done(); return }
          if (name?.toString().split(/[\\/]/).some(part => part.startsWith('.traceforge-sync'))) return
          const relative = name?.toString().replaceAll('\\', '/')
          if (relative?.startsWith('.git/') && !/^\.git\/(?:HEAD|index|config|packed-refs|refs\/.*|info\/exclude)$/.test(relative)) return
          watched.revision++; watched.prepared?.dispose(); watched.prepared = undefined
          watched.dirty = true
          if (!name || name.toString().split(/[\\/]/).some(part => ['.git', '.gitignore'].includes(part))) watched.gap = true
          if (name) watched.changedPaths.add(name.toString().replaceAll('\\', '/'))
          this.notify(watched.taskId)
        })
        index.watcher.on('error', () => { watched.dirty = true; watched.gap = true; watched.prepared?.dispose(); watched.prepared = undefined; watched.watcher?.close(); watched.watcher = undefined; this.notify(watched.taskId) })
      } catch { /* Unsupported watchers always fall back to stable scans. */ }
    }
    return { key, index }
  }
  async prefetch(repo: LocalRepository, taskId: string, objects?: SyncObjects, maxBytes: CaptureBudget = 512 * 1024 * 1024) {
    const { index } = this.observe(repo, taskId), watcher = index.watcher, revision = index.revision
    if (!watcher || index.snapshot) return 0
    if (index.prepared && !index.changedPaths.size && stamp(index.indexPath) === index.indexStamp) { reserveCaptureBudget(maxBytes, index.prepared.bytes); return index.prepared.bytes }
    const started = performance.now(), inventory = captureAllowlist(repo, undefined, undefined, false)
    const prepared = await prefetchCapture(repo.local_worktree_path, inventory, objects?.state ?? tmpdir(), repo.base_commit_sha.length === 64 ? 'sha256' : 'sha1', maxBytes)
    prepared.elapsed_ms = performance.now() - started
    if (index.watcher === watcher && index.revision === revision) index.prepared = prepared
    else prepared.dispose()
    return prepared.bytes
  }
  clearPrefetch(taskId: string) {
    for (const index of this.indexes.values()) if (index.taskId === taskId) { index.prepared?.dispose(); index.prepared = undefined }
  }
  scan(repo: LocalRepository, objects: SyncObjects, verify: boolean, verifyRaw: boolean, task: { task_id: string; task_root: string }): SyncRepository {
    const { key, index } = this.observe(repo, task.task_id), resuming = index.suspended
    const currentStamp = stamp(index.indexPath)
    if (currentStamp !== index.indexStamp) index.gap = true
    const flushed = this.flushed.delete(key)
    // A marker observed after all reads fences path additions, replacements and
    // restored-mtime edits. Any hint or watcher gap uses the ordinary raw cut.
    const prepared = flushed && index.watcher && !index.changedPaths.size && currentStamp === index.indexStamp ? index.prepared : undefined
    if (!prepared) { index.prepared?.dispose(); index.prepared = undefined }
    if (prepared) validateRepositoryIdentity(repo)
    const directoryHints = [...index.changedPaths].filter(name => {
      try { return fs.lstatSync(path.join(index.root, name)).isDirectory() } catch { return false }
    })
    let gitChecked = false
    // Missed watcher barriers and directory notifications need a Git check, not a
    // second inventory. Keep exact file hints so restored mtimes remain detectable.
    if ((resuming || index.gap || verify && !flushed || directoryHints.length) && !verifyRaw
      && index.snapshot && index.part && currentStamp === index.indexStamp && controls(repo, index) === index.controlStamp) {
      const changed = disconnectedChanges(repo, index.snapshot, index.part)
      for (const name of index.changedPaths) if (name !== '.git' && !name.startsWith('.git/') && !directoryHints.includes(name)) changed.add(name)
      if (changed.size < 500 && ![...changed].some(name => name.split('/').includes('.gitignore'))) {
        index.changedPaths = changed; index.gap = false; index.dirty = changed.size > 0; gitChecked = true
      }
    }
    index.suspended = false
    const trusted = flushed || gitChecked
    if ((!verify || trusted) && !verifyRaw && index.watcher && !index.gap && !index.dirty && index.snapshot) {
      validateRepositoryIdentity(repo)
      index.controlStamp = controls(repo, index)
      this.scans.push({ task_repository_id: repo.task_repository_id, kind: 'cached', files_read: 0, bytes_read: 0, files_reused: index.snapshot.files.length, cas_bytes_read: 0, new_blobs: 0, new_blob_bytes: 0, forced_content_checks: 0, elapsed_ms: 0 })
      return index.snapshot
    }
    const incremental = !verifyRaw && !index.gap && index.watcher && index.snapshot && index.part
      && (!verify || trusted) && index.changedPaths.size && index.changedPaths.size < 500
    let capture
    try { capture = captureCollaborationGit(repo, objects, task, verifyRaw, index.changedPaths,
      incremental ? { snapshot: index.snapshot!, part: index.part! } : undefined, prepared) }
    finally { prepared?.dispose(); if (index.prepared === prepared) index.prepared = undefined }
    const { snapshot, metrics, part } = capture
    this.scans.push({ task_repository_id: repo.task_repository_id, ...metrics })
    index.snapshot = snapshot; index.part = part; index.dirty = false; index.gap = false; index.indexStamp = currentStamp; index.changedPaths.clear(); index.verifiedAt = Date.now()
    index.controlStamp = controls(repo, index)
    return snapshot
  }
  suspend(taskId: string) {
    this.cancelNotification(taskId)
    for (const index of this.indexes.values()) if (index.taskId === taskId) {
      index.watcher?.close(); index.watcher = undefined; index.barrier?.done(); index.suspended = true; index.gap = true
    }
    // Retain at most eight detached tasks; live tasks always keep their watchers.
    const detached = [...new Set([...this.indexes.values()].filter(index => index.suspended).map(index => index.taskId))]
    for (const task of detached.slice(0, -8)) this.close(task)
  }
  invalidate(changes?: Record<string, unknown>) {
    for (const index of this.indexes.values()) {
      if (!changes) { index.dirty = true; index.gap = true; continue }
      const prefix = index.snapshot?.task_repository_id + ':'
      for (const key of Object.keys(changes)) if (key.startsWith(prefix)) { index.changedPaths.add(key.slice(prefix.length)); index.dirty = true }
    }
  }
  close(taskId?: string) {
    for (const task of this.notifications.keys()) if (!taskId || taskId === task) this.cancelNotification(task)
    for (const [key, index] of this.indexes) if (!taskId || index.taskId === taskId) {
      index.prepared?.dispose(); index.prepared = undefined
      index.watcher?.close(); index.watcher = undefined; index.barrier?.done(); this.indexes.delete(key)
    }
  }
}
