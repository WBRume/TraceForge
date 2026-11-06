import * as fs from 'node:fs'
import * as path from 'node:path'
import { fail, gitRaw, inside, remoteKey, resolved } from './filesystem'
import { identifier, syncPath, type LocalRepository } from './collaboration-store'

export interface MappingCheck {
  task_repository_id: string; local_path: string; expected_head: string;
  local_head?: string; local_branch?: string; clean?: boolean; changes: string[]; errors: string[];
}

/** Read the same identity and fetch URLs with three Git invocations per repo. */
function inspectMappedRepo(localPath: string, configuredUrl: string, roots: string[]) {
  const metadata = gitRaw(inside(localPath, roots), ['rev-parse', '--path-format=absolute', '--show-toplevel', '--git-common-dir', '--absolute-git-dir', 'HEAD', '--abbrev-ref', 'HEAD']).toString().trimEnd().split('\n')
  const repo_root = inside(metadata[0], roots), common_git_dir = inside(metadata[1], roots), git_dir = resolved(metadata[2])
  const remotes = gitRaw(repo_root, ['remote', '-v']).toString().split('\n').flatMap(line => {
    const match = /^([^\t]+)\t(.*) \(fetch\)$/.exec(line)
    return match ? [{ name: match[1], fetch_url: match[2] }] : []
  })
  const key = remoteKey(configuredUrl)
  if (!remotes.some(remote => { try { return remoteKey(remote.fetch_url) === key } catch { return false } })) fail('REPOSITORY_MISMATCH: 配置地址未匹配任何 fetch remote，请检查个人 fork / upstream')
  if (['MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'index.lock'].some(marker => fs.existsSync(path.join(git_dir, marker)))) fail('REPOSITORY_BUSY')
  const changes = gitRaw(repo_root, ['status', '--porcelain', '--untracked-files=all', '--ignore-submodules=none'], { GIT_OPTIONAL_LOCKS: '0' }).toString().trimEnd()
  return { repo_root, common_git_dir, git_dir, head_sha: metadata[3], branch: metadata[4], changes }
}

/** All repositories pass before binding or writing anything. Never fetch or checkout here. */
export function inspectMappedRepositories(repositories: LocalRepository[], roots: string[]) {
  if (!Array.isArray(repositories) || !repositories.length || repositories.length > 100) fail('COLLABORATION_REPOSITORIES_REQUIRED')
  const ids = new Set<string>(), paths: string[] = [], mounts: string[] = [], bound: LocalRepository[] = []
  const checks = repositories.map(repo => {
    const check: MappingCheck = { task_repository_id: repo.task_repository_id, local_path: repo.local_path,
      expected_head: repo.base_commit_sha, changes: [], errors: [] }
    try {
      identifier(repo.task_repository_id); syncPath(repo.rel_path)
      if (ids.has(repo.task_repository_id) || !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(repo.base_commit_sha)) fail('COLLABORATION_REPOSITORY_SET_MISMATCH')
      ids.add(repo.task_repository_id)
      const mount = repo.rel_path.toLowerCase()
      if (mounts.some(other => other === mount || other.startsWith(mount + '/') || mount.startsWith(other + '/'))) fail('COLLABORATION_REPOSITORY_OVERLAP')
      mounts.push(mount)
      const info = inspectMappedRepo(repo.local_path, repo.configured_git_url || repo.repo_url, roots)
      check.local_path = info.repo_root; check.local_head = info.head_sha
      check.local_branch = info.branch
      check.clean = !info.changes
      if (info.changes) check.changes = info.changes.split('\n').slice(0, 30)
      if (info.head_sha !== repo.base_commit_sha) check.errors.push('HEAD_MISMATCH')
      if (info.changes) check.errors.push('WORKTREE_DIRTY')
      const overlaps = (left: string, right: string) => { const relative = path.relative(left, right); return !relative || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative)) }
      if (paths.some(other => overlaps(other, info.repo_root) || overlaps(info.repo_root, other))) check.errors.push('COLLABORATION_REPOSITORY_OVERLAP')
      paths.push(info.repo_root)
      const gitDir = info.git_dir
      if (fs.statSync(gitDir).dev !== fs.statSync(info.repo_root).dev) check.errors.push('COLLABORATION_NESTED_VOLUME_UNSUPPORTED')
      bound.push({ ...repo, files: [], local_path: info.repo_root, mapped_repo_root: info.repo_root, local_worktree_path: info.repo_root,
        common_git_dir: info.common_git_dir, task_branch: check.local_branch, directory_mode: 'MAPPED', git_dir: gitDir })
    } catch (error) { check.errors.push(error instanceof Error ? error.message : String(error)) }
    return check
  })
  return { ready: checks.every(check => !check.errors.length), checks, repositories: bound }
}

export function requireCleanMappings(repositories: LocalRepository[], roots: string[]) {
  const result = inspectMappedRepositories(repositories, roots)
  if (!result.ready) fail('COLLABORATION_MAPPING_CHECK_FAILED: ' + JSON.stringify(result.checks))
  return result.repositories
}
