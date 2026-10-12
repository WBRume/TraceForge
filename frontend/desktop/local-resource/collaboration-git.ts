import * as fs from 'node:fs'
import * as path from 'node:path'
import { hash, fail, gitRaw, readJson, writeJson } from './filesystem'
import { capturePart, capturePartPaths, shadowGit, withSnapshotLock, type Part } from './git-snapshots'
import { treeEntries } from './git-content'
import { pathsInRepository, validateRepositoryIdentity, type LocalRepository, type SyncFile, type SyncObjects, type SyncRepository } from './collaboration-store'

export interface GitScanMetrics {
  kind: 'git' | 'git-delta' | 'git-forced' | 'cached'; files_read: number; bytes_read: number; files_reused: number;
  paths_checked?: number; full_inventory?: boolean;
  cas_bytes_read: number; new_blobs: number; new_blob_bytes: number; elapsed_ms: number; forced_content_checks: number;
}

/** A disconnected interval is checked by Git against the retained private index. */
export function disconnectedChanges(repo: LocalRepository, snapshot: SyncRepository, part: Part) {
  const worktree = '--work-tree=' + repo.local_worktree_path
  let changed = shadowGit(part.git_dir, [worktree, 'diff-files', '--name-only', '-z']).toString().split('\0').filter(Boolean)
  if (changed.length) {
    // Imported blobs have no stat cache yet. Porcelain diff filters these false
    // positives without writing either index; check links before it reads.
    allowlist(repo, changed, snapshot.files)
    changed = shadowGit(part.git_dir, ['--no-optional-locks', worktree, '-c', 'diff.autoRefreshIndex=true', 'diff', '--name-only', '-z',
      '--no-renames', '--no-ext-diff', '--no-textconv']).toString().split('\0').filter(Boolean)
  }
  const known = new Set(snapshot.files.map(file => file.path))
  const added = gitRaw(repo.local_worktree_path, ['ls-files', '--others', '--exclude-standard', '-z']).toString().split('\0').filter(name => name && !known.has(name)
    && !name.split('/').some(part => /^\.traceforge-sync/.test(part) || /^\.env(?:\.|$)/.test(part)))
  return new Set([...changed, ...added])
}

/** Reuse an existing task snapshot owner, including its lock, before creating one for SERVER tasks. */
function snapshotOwner(state: string, task: string, root: string) {
  const record = path.join(state, 'git-tasks', task + '.json')
  if (fs.existsSync(record)) {
    const saved = readJson(record)
    if (saved.task_root !== root) fail('SNAPSHOT_IDENTITY_CHANGED')
    return saved.object_store as string
  }
  let owner: string | undefined
  const snapshots = path.join(path.dirname(state), 'snapshots')
  if (fs.existsSync(snapshots)) for (const resource of fs.readdirSync(snapshots, { withFileTypes: true })) {
    if (!resource.isDirectory() || resource.isSymbolicLink()) continue
    const candidate = path.join(snapshots, resource.name, task + '_task'), shadows = path.join(candidate, 'shadow')
    if (!fs.existsSync(shadows)) continue
    if (fs.readdirSync(shadows).some(name => {
      const identity = path.join(shadows, name, 'owner.json')
      return fs.existsSync(identity) && readJson(identity).root === root
    })) { owner = candidate; break }
  }
  owner ??= path.join(state, 'snapshots', task + '_task')
  writeJson(record, { version: 1, task_root: root, object_store: owner })
  return owner
}

/** A Git-provided allowlist is checked for links, never used to maintain a custom stat cache. */
function allowlist(repo: LocalRepository, paths?: string[], known?: SyncFile[]) {
  if (known) validateRepositoryIdentity(repo)
  const listed = known ? { names: paths!, modes: new Map(known.map(file => [file.path, file.mode])) } : pathsInRepository(repo, paths)
  const existing: string[] = [], checked = new Set<string>()
  for (const name of listed.names) {
    let directory = path.dirname(path.join(repo.local_worktree_path, name))
    while (directory !== repo.local_worktree_path && !checked.has(directory)) {
      try { if (fs.lstatSync(directory).isSymbolicLink()) fail('COLLABORATION_SYMLINK_UNSUPPORTED') }
      catch (error: any) { if (!['ENOENT', 'ENOTDIR'].includes(error.code)) throw error }
      checked.add(directory); directory = path.dirname(directory)
    }
    try {
      const stat = fs.lstatSync(path.join(repo.local_worktree_path, name))
      if (stat.isSymbolicLink()) fail('COLLABORATION_SYMLINK_UNSUPPORTED')
      if (stat.isFile()) existing.push(name)
      else if (!stat.isDirectory()) fail('COLLABORATION_UNSUPPORTED_FILE')
    } catch (error: any) { if (!['ENOENT', 'ENOTDIR'].includes(error.code)) throw error }
  }
  return { names: existing, modes: listed.modes }
}

export function captureCollaborationGit(repo: LocalRepository, objects: SyncObjects, task: { task_id: string; task_root: string }, verifyRaw = false,
  changedPaths?: ReadonlySet<string>, previous?: { snapshot: SyncRepository; part: Part }) {
  const mapped = repo.directory_mode === 'MAPPED'
  const started = performance.now(), owner = snapshotOwner(objects.state, task.task_id + (mapped ? '-mapped' : ''), task.task_root)
  const captureRoot = mapped ? repo.local_worktree_path : task.task_root
  const captureStore = mapped ? path.join(owner, 'mapped', hash(repo.task_repository_id).slice(0, 24)) : owner
  const captureRelative = mapped ? '.' : repo.rel_path
  const forced = verifyRaw && process.platform === 'win32'
  return withSnapshotLock(owner, () => {
    const scope = previous && changedPaths ? [...changedPaths] : undefined
    const known = new Set(previous?.snapshot.files.map(file => file.path))
    const first = allowlist(repo, scope, process.platform === 'win32' && scope?.every(name => known.has(name)) ? previous?.snapshot.files : undefined)
    // One immutable cut. Edits after this tree belong to the next input.
    const affected = (name: string) => scope?.some(prefix => name === prefix || name.startsWith(prefix + '/'))
    const removed = previous?.snapshot.files.filter(file => affected(file.path)).map(file => file.path) ?? []
    const existing = new Set(first.names)
    const part = previous ? capturePartPaths(captureRoot, previous.part, first.names, removed.filter(name => !existing.has(name)), { modes: first.modes, rejectLinks: true }, false)
      : capturePart(captureRoot, captureStore, captureRelative, repo.local_worktree_path,
      first.names, 'refs/traceforge/collaboration/current/' + hash(repo.task_repository_id),
      { modes: first.modes, rejectLinks: true, forceContent: forced, changedPaths })
    const entries = treeEntries(part.git_dir, part.tree, scope)
    if (entries.length > 100_000 || entries.reduce((total, entry) => total + entry.size, 0) > 512 * 1024 * 1024) fail('COLLABORATION_SNAPSHOT_LIMIT')
    shadowGit(part.git_dir, ['update-ref', '--stdin'], Buffer.from(
      `update ${part.ref} ${part.tree}\nupdate refs/traceforge/collaboration/trees/${part.tree} ${part.tree}\n`))
    objects.git.preferStore(part.git_dir)
    const registered = objects.git.registerTree(entries)
    const { task_repository_id, repository_id, repo_url, repo_slug, rel_path, branch_name, base_commit_sha } = repo
    const files = new Map(previous?.snapshot.files.map(file => [file.path, file]))
    for (const name of removed) files.delete(name)
    for (const file of registered.files as SyncFile[]) files.set(file.path, file)
    const folded = new Set<string>()
    for (const name of files.keys()) { const key = name.toLowerCase(); if (folded.has(key)) fail('COLLABORATION_CASE_COLLISION'); folded.add(key) }
    if (files.size > 100_000 || [...files.values()].reduce((sum, file) => sum + file.size, 0) > 512 * 1024 * 1024) fail('COLLABORATION_SNAPSHOT_LIMIT')
    const snapshot: SyncRepository = { task_repository_id, repository_id, repo_url, repo_slug, rel_path, branch_name, base_commit_sha, files: [...files.values()] }
    const metrics: GitScanMetrics = { kind: previous ? 'git-delta' : forced ? 'git-forced' : 'git', paths_checked: first.names.length, full_inventory: !previous, files_read: registered.new_blobs, bytes_read: registered.new_blob_bytes,
      files_reused: entries.length - registered.new_blobs, cas_bytes_read: 0, new_blobs: registered.new_blobs,
      new_blob_bytes: registered.new_blob_bytes, forced_content_checks: forced ? 1 : 0, elapsed_ms: performance.now() - started }
    writeJson(path.join(owner, 'collaboration', repo.task_repository_id + '.json'), { version: 1, task_root: task.task_root, ...part,
      ref: 'refs/traceforge/collaboration/trees/' + part.tree })
    return { snapshot, metrics, part }
  })
}
