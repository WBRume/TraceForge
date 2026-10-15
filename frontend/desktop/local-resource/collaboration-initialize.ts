import * as fs from 'node:fs'
import { fail, git, hash } from './filesystem'
import { identifier, type SyncBinding } from './collaboration-store'

/** Forward-only journal; no displaced-file backup, worktree recreation or clone. */
export function initializeMapped(binding: SyncBinding, payload: any, save: () => void) {
  identifier(payload.operation_id); identifier(payload.binding_id)
  const signature = hash(JSON.stringify([payload.task_id, payload.session_generation, payload.session_revision, payload.repositories]))
  const previous = binding.initialization
  if (previous && previous.operation_id === payload.operation_id) {
    if (previous.signature !== signature || previous.binding_id !== payload.binding_id) fail('COLLABORATION_INITIALIZATION_CHANGED')
    if (previous.receipt) return previous.receipt
  } else {
    if (previous && !previous.receipt) fail('COLLABORATION_INITIALIZATION_PENDING')
    if (binding.directory_mode !== 'MAPPED' || binding.binding_id !== payload.previous_binding_id
      || payload.session_generation <= binding.metadata.session_generation) fail('COLLABORATION_INITIALIZATION_CHANGED')
    const ids = binding.repositories.map(repo => repo.task_repository_id).sort()
    if (!Array.isArray(payload.repositories) || JSON.stringify(ids) !== JSON.stringify(payload.repositories.map((repo: any) => repo.task_repository_id).sort())) fail('COLLABORATION_REPOSITORY_SET_MISMATCH')
    for (const target of payload.repositories) {
      const repo = binding.repositories.find(repo => repo.task_repository_id === target.task_repository_id)!
      if (!/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(target.target) || target.url !== repo.repo_url) fail('COLLABORATION_INITIALIZATION_CHANGED')
    }
    binding.initialization = { operation_id: payload.operation_id, binding_id: payload.binding_id, signature, completed: [] }
    save()
  }
  const journal = binding.initialization!
  // Verify every original Git directory before touching any file, including on recovery.
  for (const repo of binding.repositories) {
    if (fs.realpathSync(git(repo.local_worktree_path, 'rev-parse', '--absolute-git-dir')) !== repo.git_dir
      || fs.realpathSync(git(repo.local_worktree_path, 'rev-parse', '--path-format=absolute', '--git-common-dir')) !== repo.common_git_dir) fail('COLLABORATION_REPOSITORY_IDENTITY_CHANGED')
    const target = payload.repositories.find((item: any) => item.task_repository_id === repo.task_repository_id)
    try { git(repo.local_worktree_path, 'cat-file', '-e', target.target + '^{commit}') }
    catch { git(repo.local_worktree_path, 'fetch', '--no-tags', '--', repo.configured_git_url || repo.repo_url, target.target) }
    if (git(repo.local_worktree_path, 'ls-tree', '-r', target.target).split('\n').some(line => line.startsWith('160000 '))) fail('COLLABORATION_LINK_OR_SUBMODULE_UNSUPPORTED')
  }
  for (const repo of binding.repositories) {
    const target = payload.repositories.find((item: any) => item.task_repository_id === repo.task_repository_id)
    if (!journal.completed.includes(repo.task_repository_id)
      || git(repo.local_worktree_path, 'rev-parse', 'HEAD') !== target.target
      || git(repo.local_worktree_path, 'status', '--porcelain', '--ignored')) {
      git(repo.local_worktree_path, 'reset', '--hard', target.target)
      git(repo.local_worktree_path, 'clean', '-ffdx')
      if (git(repo.local_worktree_path, 'status', '--porcelain', '--ignored')) fail('COLLABORATION_INITIALIZATION_NOT_CLEAN')
      if (!journal.completed.includes(repo.task_repository_id)) journal.completed.push(repo.task_repository_id)
      save()
    }
    if (git(repo.local_worktree_path, 'rev-parse', 'HEAD') !== target.target
      || git(repo.local_worktree_path, 'status', '--porcelain', '--ignored')) fail('COLLABORATION_INITIALIZATION_NOT_CLEAN')
    repo.base_commit_sha = target.target
    repo.task_branch = git(repo.local_worktree_path, 'rev-parse', '--abbrev-ref', 'HEAD')
  }
  binding.binding_id = payload.binding_id
  binding.metadata = { ...binding.metadata, snapshot_id: '', session_generation: payload.session_generation,
    session_revision: payload.session_revision, source: 'INITIAL' }
  binding.baseline = binding.target = null
  binding.conflicts = []; binding.conflict_set_id = null; binding.applied = {}; binding.errors = []
  binding.released = binding.suspended = false
  save()
  return null // Caller builds the clean baseline using the existing private Git index.
}
