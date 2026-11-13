import * as fs from 'node:fs'
import * as path from 'node:path'
import { child, fail, git, gitRaw, inside, readJson, resolved, type Receipt } from './filesystem'

export function releaseTask(state: string, roots: string[], taskId: string, resourceId: string, taskRoot: string) {
  const root = inside(taskRoot, roots)
  if (root !== taskRoot || path.basename(root) !== taskId || path.basename(path.dirname(root)) !== 'tasks') {
    fail('TASK_BINDING_CONFLICT')
  }

  const manifest = path.join(state, 'tasks', `${taskId}.json`)
  if (fs.existsSync(manifest)) {
    const receipt = readJson<Receipt>(manifest)
    if (receipt.task_id !== taskId || receipt.task_root !== root) fail('TASK_BINDING_CONFLICT')
    const commonGitDir = (directory: string) => resolved(path.resolve(directory, git(directory, 'rev-parse', '--git-common-dir')))
    const worktrees = receipt.repositories.map(repo => {
      const base = inside(repo.repo_root, roots)
      const target = path.join(root, repo.rel_path)
      if (child(root, repo.rel_path) !== target || repo.task_branch !== `traceforge/task/${taskId}/${repo.repository_id}`) {
        fail('WORKTREE_OWNERSHIP_CONFLICT')
      }
      const exists = fs.existsSync(target)
      if (exists) {
        if (git(target, 'branch', '--show-current') !== repo.task_branch || commonGitDir(target) !== commonGitDir(base)) {
          fail('WORKTREE_OWNERSHIP_CONFLICT')
        }
        if (repo.files_ready !== false && git(target, 'status', '--porcelain')) {
          fail('WORKTREE_HAS_CHANGES: 保留未提交修改，不能删除')
        }
        if (repo.files_ready === false && git(target, 'rev-parse', 'HEAD') !== repo.base_commit_sha) {
          fail('WORKTREE_OWNERSHIP_CONFLICT')
        }
      }
      const registered = gitRaw(base, ['worktree', 'list', '--porcelain', '-z']).toString().split('\0')
        .some(line => line.startsWith('worktree ') && path.relative(line.slice(9), target) === '')
      if (exists && !registered) fail('WORKTREE_OWNERSHIP_CONFLICT')
      return { base, target, registered, repo }
    })
    for (const { base, target, registered, repo } of worktrees) {
      if (registered) git(base, 'worktree', 'remove', ...(repo.files_ready === false ? ['--force'] : []), target)
      if (git(base, 'branch', '--list', repo.task_branch)) git(base, 'branch', '-D', repo.task_branch)
    }
  } else if (fs.existsSync(root)) {
    fail('TASK_BINDING_CONFLICT')
  }

  if (fs.existsSync(root)) {
    if (fs.readdirSync(root).length) {
      const archive = path.join(path.dirname(root), '.delete')
      if (inside(archive, [path.dirname(root)]) !== archive) fail('TASK_ARCHIVE_PATH_CONFLICT')
      fs.mkdirSync(archive, { recursive: true })
      const destination = path.join(archive, taskId)
      if (fs.existsSync(destination)) fail('TASK_ARCHIVE_PATH_CONFLICT')
      fs.renameSync(root, destination)
    } else {
      fs.rmdirSync(root)
    }
  }
  const snapshots = path.join(state, 'snapshots', `${resourceId}_resource`, `${taskId}_task`)
  if (inside(snapshots, [state]) !== snapshots) fail('TASK_SNAPSHOT_PATH_CONFLICT')
  fs.rmSync(snapshots, { recursive: true, force: true })
  fs.rmSync(manifest, { force: true })
}
