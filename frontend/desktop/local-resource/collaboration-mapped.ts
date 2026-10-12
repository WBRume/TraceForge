import * as fs from 'node:fs'
import * as path from 'node:path'
import { fail, git, gitRaw, inspectRepo, resolved } from './filesystem'
import { identifier, syncPath, type LocalRepository } from './collaboration-store'

export interface MappingCheck {
  task_repository_id: string; local_path: string; expected_head: string;
  local_head?: string; local_branch?: string; clean?: boolean; changes: string[]; errors: string[];
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
      const info = inspectRepo(repo.local_path, repo.configured_git_url || repo.repo_url, roots)
      check.local_path = info.repo_root; check.local_head = info.head_sha
      check.local_branch = git(info.repo_root, 'rev-parse', '--abbrev-ref', 'HEAD')
      check.clean = !info.dirty
      if (info.dirty) check.changes = gitRaw(info.repo_root, ['status', '--porcelain', '--untracked-files=normal'], { GIT_OPTIONAL_LOCKS: '0' }).toString().trimEnd().split('\n').slice(0, 30)
      if (info.head_sha !== repo.base_commit_sha) check.errors.push('HEAD_MISMATCH')
      if (info.dirty) check.errors.push('WORKTREE_DIRTY')
      const overlaps = (left: string, right: string) => { const relative = path.relative(left, right); return !relative || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative)) }
      if (paths.some(other => overlaps(other, info.repo_root) || overlaps(info.repo_root, other))) check.errors.push('COLLABORATION_REPOSITORY_OVERLAP')
      paths.push(info.repo_root)
      const gitDir = resolved(git(info.repo_root, 'rev-parse', '--absolute-git-dir'))
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
