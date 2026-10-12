import * as fs from 'node:fs'
import * as path from 'node:path'
import { randomUUID } from 'node:crypto'
import { child, fail, git, gitRaw, hash } from './filesystem'
import { GitContent } from './git-content'

export interface SyncFile { path: string; sha256: string; size: number; mode: '100644' | '100755' | '120000' }
export interface SyncRepository {
  task_repository_id: string; repository_id: string; repo_url: string; repo_slug: string;
  rel_path: string; branch_name: string; base_commit_sha: string; files: SyncFile[];
}
export interface SyncManifest {
  protocol_version: 1; snapshot_id: string; task_id: string; workspace_revision: number;
  session_generation: number; session_revision: number; repository_set_digest: string;
  source: string; repositories: SyncRepository[];
}
export interface LocalRepository extends SyncRepository {
  local_path: string; configured_git_url: string; local_worktree_path: string;
  mapped_repo_root: string; common_git_dir: string; task_branch: string;
  directory_mode?: 'MAPPED'; git_dir?: string;
}
export interface SyncConflict {
  task_repository_id: string; path: string; expected_sha256: string | null;
  base: SyncFile | null; local: SyncFile | null; cloud: SyncFile | null; reason: string;
  related_paths?: string[];
}
export interface SyncBinding {
  task_id: string; binding_id: string; task_root: string; repositories: LocalRepository[];
  expected_repository_ids: string[];
  metadata: Omit<SyncManifest, 'repositories'>; baseline: SyncManifest | null;
  target: SyncManifest | null; conflicts: SyncConflict[]; conflict_set_id: string | null;
  applied: Record<string, SyncFile | null>; errors: string[];
  directory_mode?: 'MAPPED'; released?: boolean; suspended?: boolean;
}

export function durableJson(file: string, value: unknown) {
  durableFile(file, Buffer.from(JSON.stringify(value)))
}
export function durableFile(file: string, data: Uint8Array) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  const temporary = file + '.' + randomUUID() + '.tmp'
  const fd = fs.openSync(temporary, 'wx', 0o600)
  try { fs.writeFileSync(fd, data); fs.fsyncSync(fd) } finally { fs.closeSync(fd) }
  try { fs.renameSync(temporary, file) } finally { fs.rmSync(temporary, { force: true }) }
}
export const identifier = (value: string) => {
  if (typeof value !== 'string' || !/^[a-zA-Z0-9_-]{1,128}$/.test(value)) fail('INVALID_COLLABORATION_ID')
  return value
}
export function syncPath(relative: string) {
  if (typeof relative !== 'string' || relative.includes('\\') || relative.length > 2048
    || relative.split('/').some(part => !part || part === '.' || part === '..' || /[<>:"|?*\x00-\x1f]/.test(part)
      || /^(\.git|\.sdd|\.traceforge-collaboration|\.traceforge-sync.*)$/i.test(part) || /[. ]$/.test(part)
      || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i.test(part))) fail('INVALID_COLLABORATION_PATH')
  return relative
}
export const sameFile = (a: SyncFile | null | undefined, b: SyncFile | null | undefined) =>
  (!a && !b) || (!!a && !!b && a.sha256 === b.sha256 && a.mode === b.mode && a.size === b.size)
export const fileKey = (repo: string, file: string) => repo + ':' + file

export class SyncObjects {
  readonly state: string
  readonly git: GitContent
  constructor(state: string) { this.state = state; this.git = new GitContent(state) }
  file(digest: string) { return this.git.file(digest) }
  put(data: Uint8Array) {
    if (data.byteLength > 64 * 1024 * 1024) fail('COLLABORATION_FILE_TOO_LARGE')
    const sha256 = hash(data)
    this.git.putMany([{ sha256, data: Buffer.from(data) }])
    this.get(sha256)
    return sha256
  }
  get(digest: string) {
    return this.git.get(digest)
  }
  receive(entries: { sha256: string; content: string }[]) {
    const incoming = entries.map(entry => {
      const data = Buffer.from(entry.content, 'base64')
      if (data.toString('base64') !== entry.content || hash(data) !== entry.sha256) fail('CONTENT_OBJECT_DIGEST_MISMATCH')
      return { sha256: entry.sha256, data }
    })
    this.git.putMany(incoming)
    return { stored: entries.length }
  }
}

/** Reads raw working bytes, never Git-filtered content, and rejects links at every component. */
export function localFile(root: string, relative: string, objects: SyncObjects): SyncFile | null {
  syncPath(relative)
  let next = root
  for (const segment of relative.split('/')) {
    next = path.join(next, segment)
    try { if (fs.lstatSync(next).isSymbolicLink()) fail('COLLABORATION_SYMLINK_UNSUPPORTED') }
    catch (error: any) { if (['ENOENT', 'ENOTDIR'].includes(error.code)) return null; throw error }
  }
  // Windows' native resolver avoids repeatedly walking every ancestor in JavaScript.
  // Keep both canonical boundary validation and the explicit link checks above.
  const file = process.platform === 'win32' ? fs.realpathSync.native(next) : child(root, relative)
  if (process.platform === 'win32') {
    const boundary = path.relative(fs.realpathSync.native(root), file)
    if (boundary === '..' || boundary.startsWith('..' + path.sep) || path.isAbsolute(boundary)) fail('PATH_OUTSIDE_RESOURCE_ROOT')
  }
  let before: fs.Stats
  try { before = fs.statSync(file) } catch (error: any) { if (error.code === 'ENOENT') return null; throw error }
  if (!before.isFile()) fail('COLLABORATION_PATH_STRUCTURE_CONFLICT: ' + relative)
  if (before.size > 64 * 1024 * 1024) fail('COLLABORATION_FILE_TOO_LARGE: ' + relative)
  const data = fs.readFileSync(file), after = fs.statSync(file)
  if (before.size !== after.size || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs
    || before.ino !== after.ino || data.length !== after.size) fail('LOCAL_FILE_CHANGING: ' + relative)
  if (data.subarray(0, 80).toString().startsWith('version https://git-lfs.github.com/spec/v1\n')) fail('COLLABORATION_LFS_CONTENT_REQUIRED: ' + relative)
  return { path: relative, sha256: objects.put(data), size: data.length, mode: after.mode & 0o111 ? '100755' : '100644' }
}

/** Git link placeholders stay inert regular files and must retain their original indexed type. */
export function repositoryFileModes(root: string, paths?: string[]) {
  const scope = paths ? ['--', ...paths] : []
  const tracked = gitRaw(root, ['--literal-pathspecs', 'ls-files', '--stage', '-z', ...scope]).toString().split('\0').filter(Boolean)
  const modes = new Map<string, SyncFile['mode']>()
  for (const entry of tracked) {
    const match = /^(\d+) [a-f0-9]+ (\d)\t([\s\S]+)$/.exec(entry)
    if (!match || match[2] !== '0') throw new Error('COLLABORATION_INDEX_CONFLICT')
    if (!['100644', '100755', '120000'].includes(match[1])) fail('COLLABORATION_LINK_OR_SUBMODULE_UNSUPPORTED')
    modes.set(match[3], match[1] as SyncFile['mode'])
  }
  const placeholders = new Set<string>()
  for (const entry of gitRaw(root, ['--literal-pathspecs', 'ls-tree', '-r', '--full-tree', '-z', 'HEAD', ...scope]).toString().split('\0')) {
    const link = /^120000 blob [a-f0-9]+\t([\s\S]+)$/.exec(entry)
    if (link) placeholders.add(link[1])
  }
  if (placeholders.size || [...modes.values()].includes('120000')) {
    if (process.platform !== 'win32' || gitRaw(root, ['config', '--bool', 'core.symlinks'], {}, false).toString().trim() !== 'false') fail('COLLABORATION_LINK_OR_SUBMODULE_UNSUPPORTED')
    for (const [name, mode] of modes) if ((mode === '120000') !== placeholders.has(name)) fail('COLLABORATION_PLACEHOLDER_TYPE_CHANGED')
  }
  return { modes, placeholders }
}

export function validateFileMode(name: string, mode: SyncFile['mode'], indexed: ReturnType<typeof repositoryFileModes>) {
  if (mode === '120000' ? !indexed.placeholders.has(name) || indexed.modes.get(name) !== '120000' : indexed.placeholders.has(name)) fail('COLLABORATION_PLACEHOLDER_TYPE_CHANGED')
}

export function validateRepositoryIdentity(repo: LocalRepository) {
  const root = repo.local_worktree_path
  const [head, branch, common, gitDir] = git(root, 'rev-parse', '--path-format=absolute', 'HEAD', '--abbrev-ref', 'HEAD', '--git-common-dir', '--absolute-git-dir').split(/\r?\n/)
  if (head !== repo.base_commit_sha || branch !== repo.task_branch || !common
    || fs.realpathSync(path.resolve(root, common)) !== repo.common_git_dir
    || (repo.directory_mode === 'MAPPED' && (!gitDir || fs.realpathSync(gitDir) !== repo.git_dir))) fail('COLLABORATION_REPOSITORY_IDENTITY_CHANGED')
}

export function pathsInRepository(repo: LocalRepository, paths?: string[]) {
  validateRepositoryIdentity(repo)
  const root = repo.local_worktree_path
  const { modes, placeholders } = repositoryFileModes(root, paths)
  const untracked = gitRaw(root, ['--literal-pathspecs', 'ls-files', '--others', '--exclude-standard', '-z', ...(paths ? ['--', ...paths] : [])]).toString().split('\0').filter(Boolean)
    .filter(file => !file.split('/').some(part => /^\.traceforge-sync/.test(part) || /^\.env(?:\.|$)/.test(part)))
  const names = [...new Set([...modes.keys(), ...untracked])]
    .filter(file => !file.split('/').some(part => ['.sdd', '.traceforge-collaboration'].includes(part) || /^\.traceforge-sync/.test(part))).sort()
  const keys = new Set<string>()
  for (const name of names) {
    syncPath(name)
    if (placeholders.has(name) && modes.get(name) !== '120000') fail('COLLABORATION_PLACEHOLDER_TYPE_CHANGED')
    const key = process.platform === 'win32' ? name.toLowerCase() : name
    if (keys.has(key)) fail('COLLABORATION_CASE_COLLISION')
    keys.add(key)
  }
  return { names, modes }
}
