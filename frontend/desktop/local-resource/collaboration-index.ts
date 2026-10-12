import * as fs from 'node:fs'
import * as path from 'node:path'
import { randomUUID } from 'node:crypto'
import { gitRaw } from './filesystem'
import { validateRepositoryIdentity, type LocalRepository, type SyncRepository, type SyncObjects } from './collaboration-store'
import { captureCollaborationGit, type GitScanMetrics } from './collaboration-git'
import type { Part } from './git-snapshots'

interface RepositoryIndex { taskId: string; root: string; watcher?: fs.FSWatcher; dirty: boolean; gap: boolean; changedPaths: Set<string>; verifiedAt: number; snapshot?: SyncRepository; part?: Part; indexPath: string; indexStamp: string; barrier?: { name: string; done: () => void } }
function stamp(file: string) { try { const s = fs.statSync(file); return `${s.ino}:${s.size}:${s.mtimeMs}:${s.ctimeMs}` } catch { return '' } }

/** Git owns the index; watcher paths supplement its stat check for restored mtimes. */
export class CollaborationIndex {
  private readonly indexes = new Map<string, RepositoryIndex>()
  private scans: (GitScanMetrics & { task_repository_id: string })[] = []
  private flushed = new Set<string>()
  beginOperation() { this.scans = [] }
  measurements() { return this.scans }
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
  scan(repo: LocalRepository, objects: SyncObjects, verify: boolean, verifyRaw: boolean, task: { task_id: string; task_root: string }): SyncRepository {
    const key = JSON.stringify([task.task_id, repo.task_repository_id, repo.local_worktree_path])
    let index = this.indexes.get(key)
    if (!index) {
      const indexPath = gitRaw(repo.local_worktree_path, ['rev-parse', '--path-format=absolute', '--git-path', 'index']).toString().trim()
      index = { taskId: task.task_id, root: repo.local_worktree_path, dirty: true, gap: true, changedPaths: new Set(), verifiedAt: 0, indexPath, indexStamp: stamp(indexPath) }
      this.indexes.set(key, index)
      const watched = index
      try {
        index.watcher = fs.watch(repo.local_worktree_path, { recursive: true, persistent: false }, (_kind, name) => {
          if (watched.barrier && name?.toString() === watched.barrier.name) { watched.barrier.done(); return }
          if (name?.toString().split(/[\\/]/).some(part => part.startsWith('.traceforge-sync'))) return
          const relative = name?.toString().replaceAll('\\', '/')
          if (relative?.startsWith('.git/') && !/^\.git\/(?:HEAD|index|config|packed-refs|refs\/.*|info\/exclude)$/.test(relative)) return
          watched.dirty = true
          if (!name || name.toString().split(/[\\/]/).some(part => ['.git', '.gitignore'].includes(part))) watched.gap = true
          if (name) watched.changedPaths.add(name.toString().replaceAll('\\', '/'))
        })
        index.watcher.on('error', () => { watched.dirty = true; watched.gap = true; watched.watcher?.close(); watched.watcher = undefined })
      } catch { /* Unsupported watchers always fall back to stable scans. */ }
    }
    const currentStamp = stamp(index.indexPath)
    if (currentStamp !== index.indexStamp) index.gap = true
    const trusted = this.flushed.delete(key)
    if ((!verify || trusted) && !verifyRaw && index.watcher && !index.gap && !index.dirty && index.snapshot) {
      validateRepositoryIdentity(repo)
      this.scans.push({ task_repository_id: repo.task_repository_id, kind: 'cached', files_read: 0, bytes_read: 0, files_reused: index.snapshot.files.length, cas_bytes_read: 0, new_blobs: 0, new_blob_bytes: 0, forced_content_checks: 0, elapsed_ms: 0 })
      return index.snapshot
    }
    const incremental = !verifyRaw && !index.gap && index.watcher && index.snapshot && index.part
      && (!verify || trusted) && index.changedPaths.size && index.changedPaths.size < 500
    const { snapshot, metrics, part } = captureCollaborationGit(repo, objects, task, verifyRaw, index.changedPaths,
      incremental ? { snapshot: index.snapshot!, part: index.part! } : undefined)
    this.scans.push({ task_repository_id: repo.task_repository_id, ...metrics })
    index.snapshot = snapshot; index.part = part; index.dirty = false; index.gap = false; index.indexStamp = currentStamp; index.changedPaths.clear(); index.verifiedAt = Date.now()
    return snapshot
  }
  invalidate(changes?: Record<string, unknown>) {
    for (const index of this.indexes.values()) {
      if (!changes) { index.dirty = true; index.gap = true; continue }
      const prefix = index.snapshot?.task_repository_id + ':'
      for (const key of Object.keys(changes)) if (key.startsWith(prefix)) { index.changedPaths.add(key.slice(prefix.length)); index.dirty = true }
    }
  }
  close() { for (const index of this.indexes.values()) index.watcher?.close(); this.indexes.clear() }
}
