import * as fs from 'node:fs'
import * as path from 'node:path'
import { randomUUID } from 'node:crypto'
import { fail, git, gitRaw, readJson, resolved } from './filesystem'
import { durableJson, identifier } from './collaboration-store'

interface Initialization {
  task_id: string; task_repository_id: string; target: string; branch: string;
  base_commit_sha: string; repo_root: string; common_git_dir: string;
  marker: string; phase: string;
}

/** Resume only our own unfinished checkout; never reset or force-overwrite existing files. */
export function prepareTaskWorktree(input: {
  state: string; task_id: string; task_repository_id: string; target: string; branch: string;
  base_commit_sha: string; repo_root: string; common_git_dir: string;
  afterWorktree?: () => void;
}) {
  const { task_id, task_repository_id, target, branch, base_commit_sha, repo_root, common_git_dir } = input
  const file = path.join(input.state, 'initializations', identifier(task_id), identifier(task_repository_id) + '.json')
  const identity = { task_id, task_repository_id, target, branch, base_commit_sha, repo_root, common_git_dir }
  const ref = 'refs/heads/' + branch
  const head = () => gitRaw(repo_root, ['rev-parse', '--verify', ref], {}, false).toString().trim()
  let record: Initialization
  if (fs.existsSync(file)) {
    record = readJson(file)
    if (Object.entries(identity).some(([key, value]) => record[key as keyof Initialization] !== value)) fail('COLLABORATION_INITIALIZATION_IDENTITY_CHANGED')
  } else {
    if (head() || fs.existsSync(target)) fail('COLLABORATION_WORKTREE_OWNERSHIP_CONFLICT')
    record = { ...identity, marker: 'TraceForge initialization ' + randomUUID(), phase: 'PLANNED' }
    durableJson(file, record)
  }
  const save = (phase: string) => { record.phase = phase; durableJson(file, record) }
  if (!head()) {
    // Expected zero makes branch creation exclusive even if another Git process races us.
    git(repo_root, 'update-ref', '--create-reflog', '-m', record.marker, ref, base_commit_sha, '0'.repeat(base_commit_sha.length))
  }
  if (head() !== base_commit_sha || git(repo_root, 'reflog', 'show', '-1', '--format=%gs', ref) !== record.marker) fail('COLLABORATION_WORKTREE_OWNERSHIP_CONFLICT')
  if (record.phase === 'PLANNED') save('BRANCH_CREATED')
  const existing = fs.existsSync(target)
  if (existing && fs.lstatSync(target).isSymbolicLink()) fail('COLLABORATION_WORKTREE_OWNERSHIP_CONFLICT')
  if (!existing || !fs.readdirSync(target).length) {
    fs.mkdirSync(path.dirname(target), { recursive: true })
    git(repo_root, '-c', 'core.longpaths=true', 'worktree', 'add', '--no-checkout', target, branch)
  }
  if (git(target, 'branch', '--show-current') !== branch || git(target, 'rev-parse', 'HEAD') !== base_commit_sha
    || resolved(path.resolve(target, git(target, 'rev-parse', '--git-common-dir'))) !== common_git_dir) fail('COLLABORATION_WORKTREE_OWNERSHIP_CONFLICT')
  if (record.phase === 'BRANCH_CREATED') save('WORKTREE_CREATED')
  input.afterWorktree?.()
  const populatedIndex = gitRaw(target, ['ls-files', '-z']).length > 0
  if (populatedIndex) {
    try { git(target, '-c', 'core.longpaths=true', 'diff-index', '--cached', '--quiet', 'HEAD', '--') }
    catch { fail('COLLABORATION_INITIALIZATION_HAS_LOCAL_EDITS') }
  } else git(target, '-c', 'core.longpaths=true', 'read-tree', 'HEAD')
  save('POPULATING')
  // Without --force checkout-index leaves every existing file untouched, including edits after a crash.
  gitRaw(target, ['-c', 'core.longpaths=true', 'checkout-index', '--all'], {}, false)
  if (git(target, '-c', 'core.longpaths=true', 'status', '--porcelain')) fail('COLLABORATION_INITIALIZATION_INCOMPLETE_OR_LOCAL_EDITS')
  save('READY')
}
