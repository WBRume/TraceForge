import * as fs from 'node:fs'
import * as path from 'node:path'
import { createHash, randomUUID } from 'node:crypto'
import { spawnSync } from 'node:child_process'

export const hash = (data: string | Uint8Array) => createHash('sha256').update(data).digest('hex')
export const fail = (message: string): never => { throw new Error(message) }
export function resolved(file: string): string {
  const absolute = path.resolve(file)
  if (fs.existsSync(absolute)) return fs.realpathSync(absolute)
  // Reject dangling links instead of interpreting them as missing regular files.
  try { if (fs.lstatSync(absolute).isSymbolicLink()) fail('DANGLING_LINK') } catch (error: any) { if (error.code !== 'ENOENT') throw error }
  const parent = path.dirname(absolute)
  return parent === absolute ? absolute : path.join(resolved(parent), path.basename(absolute))
}
export function inside(file: string, roots: string[]): string {
  const target = resolved(file)
  if (!roots.some(root => { const rel = path.relative(resolved(root), target); return rel === '' || (!rel.startsWith('..' + path.sep) && rel !== '..' && !path.isAbsolute(rel)) })) {
    fail(`PATH_OUTSIDE_RESOURCE_ROOT: 路径 "${target}" 不在同机资源服务的授权目录 (allowed_roots) 中。当前授权目录: [${roots.join(', ')}]`)
  }
  return target
}
export function child(root: string, relative: string): string {
  if (typeof relative !== 'string' || !relative || relative.includes('\0') || relative.includes(':') || path.isAbsolute(relative) || relative.replaceAll('\\', '/').split('/').some(part => !part || part === '..' || part === '.')) fail('INVALID_RELATIVE_PATH')
  return inside(path.join(root, relative), [root])
}
export function atomic(file: string, data: string | Uint8Array) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  const temporary = path.join(path.dirname(file), '.tf-write-' + randomUUID())
  try { fs.writeFileSync(temporary, data, { flag: 'wx', mode: 0o600 }); fs.renameSync(temporary, file) }
  finally { fs.rmSync(temporary, { force: true }) }
}
export const readJson = <T = any>(file: string): T => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''))
export const writeJson = (file: string, data: unknown) => atomic(file, JSON.stringify(data))
export function gitRaw(cwd: string, args: string[], env: NodeJS.ProcessEnv = {}, check = true): Buffer {
  const result = spawnSync('git', args, { cwd, env: { ...process.env, GIT_TERMINAL_PROMPT: '0', ...env }, timeout: 180_000, windowsHide: true, maxBuffer: 128 * 1024 * 1024 })
  if (result.error) throw result.error
  if (check && result.status !== 0) fail(result.stderr.toString().trim() || 'GIT_OPERATION_FAILED')
  return result.stdout
}
export const git = (cwd: string, ...args: string[]) => gitRaw(cwd, args).toString('utf8').trim()
export function decodeFile(entry: { content: string; sha256: string }) {
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(entry.content)) fail('INVALID_BASE64')
  const data = Buffer.from(entry.content, 'base64')
  if (hash(data) !== entry.sha256) fail('FILE_HASH_MISMATCH')
  return data
}
export function writeFiles(root: string, entries: { path: string; content: string; sha256: string }[]) {
  const files = entries.map(entry => {
    if (entry.path.replaceAll('\\', '/').split('/').some(part => part.toLowerCase() === '.git')) fail('GIT_CONTROL_PATH_FORBIDDEN')
    return { target: child(root, entry.path), data: decodeFile(entry) }
  })
  for (const file of files) atomic(file.target, file.data)
}
export function walk(root: string, prefix = ''): string[] {
  if (!fs.existsSync(root)) return []
  const result: string[] = []
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) continue
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name
    if (entry.isDirectory()) result.push(...walk(path.join(root, entry.name), relative))
    else if (entry.isFile()) result.push(relative)
  }
  return result.sort()
}
export function copyTree(source: string, target: string) {
  for (const relative of walk(source)) atomic(child(target, relative), fs.readFileSync(child(source, relative)))
}

export interface Repository {
  repository_id: string; local_path: string; configured_git_url: string; branch_name: string;
  rel_path: string; repo_url: string; repo_name: string;
}
export interface BoundRepository extends Repository { base_commit_sha: string; task_branch: string; repo_root: string }
export interface Receipt { task_id: string; task_root: string; repositories_input: Repository[]; repositories: BoundRepository[] }
export function remoteKey(value: string) {
  const scp = /^[^@/]+@([^:/]+):(.+)$/.exec(value.trim().replace(/\/$/, ''))
  if (scp) return `${scp[1].toLowerCase()}/${scp[2].replace(/\.git$/, '')}`
  const url = new URL(value)
  if (!['http:', 'https:', 'ssh:', 'git:'].includes(url.protocol)) fail('INVALID_GIT_URL')
  const port = url.port && url.port !== ({ 'ssh:': '22', 'git:': '9418' } as Record<string, string>)[url.protocol] ? ':' + url.port : ''
  return url.hostname.toLowerCase() + port + '/' + url.pathname.replace(/^\/+|\/+$/g, '').replace(/\.git$/, '')
}
export function inspectRepo(localPath: string, configuredUrl: string, roots: string[]) {
  const actual = inside(git(inside(localPath, roots), 'rev-parse', '--show-toplevel'), roots)
  const common = inside(path.resolve(actual, git(actual, 'rev-parse', '--git-common-dir')), roots)
  const remotes = git(actual, 'remote').split('\n').filter(Boolean).flatMap(name => git(actual, 'remote', 'get-url', '--all', name).split('\n').map(fetch_url => ({ name, fetch_url })))
  const key = remoteKey(configuredUrl)
  const matched = remotes.find(remote => { try { return remoteKey(remote.fetch_url) === key } catch { return false } })
  if (!matched) fail('REPOSITORY_MISMATCH: 配置地址未匹配任何 fetch remote，请检查个人 fork / upstream')
  const gitDir = git(actual, 'rev-parse', '--absolute-git-dir')
  if (['MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'index.lock'].some(marker => fs.existsSync(path.join(gitDir, marker)))) fail('REPOSITORY_BUSY')
  return { repo_root: actual, common_git_dir: common, matched_remote: matched!.name, remotes, head_sha: git(actual, 'rev-parse', '--verify', 'HEAD'), dirty: !!git(actual, 'status', '--porcelain') }
}
export function provision(root: string, taskId: string, repos: Repository[], roots: string[], manifestFile: string): Receipt {
  let receipt: Receipt
  if (fs.existsSync(manifestFile)) {
    receipt = readJson(manifestFile)
    if (receipt.task_id !== taskId || JSON.stringify(receipt.repositories_input) !== JSON.stringify(repos)) fail('TASK_BINDING_CONFLICT')
  } else {
    if (fs.existsSync(root) && fs.readdirSync(root).length) fail('TASK_DIRECTORY_ALREADY_EXISTS')
    fs.mkdirSync(root, { recursive: true })
    receipt = { task_id: taskId, task_root: root, repositories_input: repos, repositories: [] }
    writeJson(manifestFile, receipt)
  }
  for (const repo of repos) {
    if (receipt.repositories.some(r => r.repository_id === repo.repository_id)) continue
    const info = inspectRepo(repo.local_path, repo.configured_git_url, roots)
    if (!repo.branch_name || repo.branch_name.startsWith('-')) fail('INVALID_BRANCH')
    git(info.repo_root, 'check-ref-format', '--branch', repo.branch_name)
    git(info.repo_root, 'fetch', '--no-tags', info.matched_remote, repo.branch_name)
    let sha = git(info.repo_root, 'rev-parse', '--verify', 'FETCH_HEAD^{commit}')
    const target = child(root, repo.rel_path), branch = `traceforge/task/${taskId}/${repo.repository_id}`
    if (fs.existsSync(target)) {
      if (git(target, 'branch', '--show-current') !== branch || resolved(path.resolve(target, git(target, 'rev-parse', '--git-common-dir'))) !== info.common_git_dir) fail('WORKTREE_OWNERSHIP_CONFLICT')
      sha = git(target, 'rev-parse', 'HEAD')
    } else git(info.repo_root, 'worktree', 'add', '-b', branch, target, sha)
    receipt.repositories.push({ ...repo, base_commit_sha: sha, task_branch: branch, repo_root: info.repo_root })
    writeJson(manifestFile, receipt)
  }
  return receipt
}
