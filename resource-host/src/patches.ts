import * as fs from 'node:fs'
import * as path from 'node:path'
import { randomUUID } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { child, decodeFile, fail, git, gitRaw, hash, inside, inspectRepo, type Receipt } from './filesystem'

export function generatePatches(receipt: Receipt, state: string) {
  const repositories = []
  for (const repo of receipt.repositories) {
    const cwd = child(receipt.task_root, repo.rel_path)
    const index = path.join(state, 'patch-index-' + randomUUID())
    const env = { GIT_INDEX_FILE: index }
    const diff = ['diff', '--cached', '--find-renames']
    const paths = ['--', '.', ':(exclude).sdd/**']
    try {
      gitRaw(cwd, ['read-tree', repo.base_commit_sha], env)
      gitRaw(cwd, ['add', '-A', ...paths], env)
      const status = gitRaw(cwd, [...diff, '--name-status', '-z', ...paths], env).toString().split('\0').filter(Boolean)
      if (!status.length) continue
      const files = []
      for (let i = 0; i < status.length;) {
        const kind = status[i++][0], first = status[i++], renamed = kind === 'R' || kind === 'C'
        const file = renamed ? status[i++] : first
        const filePaths = renamed ? [first, file] : [file]
        const stats = gitRaw(cwd, [...diff, '--numstat', '-z', '--', ...filePaths], env).toString().split('\t')
        const binary = stats[0] === '-' || stats[1] === '-'
        files.push({ file_path: file, change_type: ({ A: 'added', D: 'deleted', R: 'renamed' } as Record<string, string>)[kind] || 'modified',
          old_path: renamed ? first : null, new_path: renamed ? file : null, insertions: binary ? 0 : Number(stats[0] || 0), deletions: binary ? 0 : Number(stats[1] || 0), is_binary: binary,
          diff_excerpt: gitRaw(cwd, [...diff, '--', ...filePaths], env).toString().slice(0, 12000) })
      }
      const patch = gitRaw(cwd, [...diff, '--binary', ...paths], env).toString()
      repositories.push({ repository_id: repo.repository_id, repo_url: repo.repo_url, repo_name: repo.repo_name || repo.rel_path,
        repo_slug: repo.rel_path, base_branch: repo.branch_name, base_commit_sha: repo.base_commit_sha,
        cloud_task_branch: git(cwd, 'branch', '--show-current'), cloud_head_sha: git(cwd, 'rev-parse', 'HEAD'),
        patch_text: patch, sha256: hash(patch), changed_files_count: files.length,
        insertions: files.reduce((n, file) => n + file.insertions, 0), deletions: files.reduce((n, file) => n + file.deletions, 0), files })
    } finally { fs.rmSync(index, { force: true }) }
  }
  if (!repositories.length) fail('No changes in task worktree')
  return { repositories }
}

export function applyPatches(taskId: string, operationId: string, payload: any, roots: string[], state: string) {
  const root = child(inside(payload.workspace_root, roots), 'patches/' + taskId)
  if (fs.existsSync(root)) fail('PATCH_WORKTREE_EXISTS: inspect existing worktree before another application')
  const inputs = payload.repositories.map((repo: any) => ({ repo, data: decodeFile({ content: repo.patch, sha256: repo.sha256 }), target: child(root, repo.repo_slug) }))
  fs.mkdirSync(root, { recursive: true })
  const repositories = []
  for (const { repo, data, target } of inputs) {
    const info = inspectRepo(repo.local_path, repo.configured_git_url, roots)
    if (!repo.base_branch || repo.base_branch.startsWith('-') || !/^[0-9a-fA-F]{40,64}$/.test(repo.base_commit_sha)) fail('INVALID_PATCH_BASE')
    git(info.repo_root, 'check-ref-format', '--branch', repo.base_branch)
    git(info.repo_root, 'fetch', '--no-tags', info.matched_remote, repo.base_branch)
    git(info.repo_root, 'rev-parse', '--verify', repo.base_commit_sha + '^{commit}')
    const branch = `traceforge/patch/${taskId}/${repo.repo_slug}`
    git(info.repo_root, 'worktree', 'add', '-b', branch, target, repo.base_commit_sha)
    const patch = path.join(state, 'patch-' + operationId + '.diff')
    fs.writeFileSync(patch, data, { flag: 'wx' })
    try {
      const result = spawnSync('git', ['apply', '--3way', '--whitespace=nowarn', patch], { cwd: target, timeout: 180_000, windowsHide: true, encoding: 'utf8' })
      if (result.error) throw result.error
      repositories.push({ repository_id: repo.repository_id, path: target, branch, status: result.status === 0 ? 'applied' : 'conflict', message: result.stderr.slice(-2000) })
    } finally { fs.rmSync(patch, { force: true }) }
  }
  return { repositories, status: repositories.every(r => r.status === 'applied') ? 'applied' : 'conflict' }
}
