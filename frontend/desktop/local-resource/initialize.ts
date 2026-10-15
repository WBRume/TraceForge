/** Forward-only reset of owned task worktrees; existing Git objects are reused. */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { child, fail, gitRaw, hash, type Receipt } from './filesystem'

export function initialize(receipt: Receipt, payload: any) {
  const taskRoot = fs.realpathSync(receipt.task_root)
  const run = (root: string, ...args: string[]) => gitRaw(root, ['-c', `core.hooksPath=${process.platform === 'win32' ? 'NUL' : '/dev/null'}`, ...args]).toString().trim()
  if (payload.action === 'clean') {
    const keep = ['.git', ...receipt.repositories.map(repo => repo.rel_path), ...payload.protected]
    if (keep.includes('.')) return { cleaned: true }
    const visit = (root: string, prefix = '') => {
      for (const name of fs.readdirSync(root)) {
        const relative = prefix + name
        if (keep.includes(relative)) continue
        const file = path.join(root, name), info = fs.lstatSync(file)
        if (keep.some((value: string) => value.startsWith(relative + '/'))) {
          if (info.isSymbolicLink()) fail('INITIALIZATION_INPUT_SYMLINK')
          if (info.isDirectory()) visit(file, relative + '/')
          continue
        }
        // Never traverse a link; every recursive target is inside this owned task.
        if (path.relative(taskRoot, fs.realpathSync(root)).split(path.sep).includes('..')) fail('INITIALIZATION_PATH_INVALID')
        fs.rmSync(file, { recursive: info.isDirectory() && !info.isSymbolicLink(), force: true })
      }
    }
    visit(taskRoot)
    return { cleaned: true }
  }
  const request = payload.repository
  const repo = receipt.repositories.find(item => item.repository_id === request?.repository_id)
  if (!repo || repo.rel_path !== request.rel_path || repo.branch_name !== request.branch) fail('INITIALIZATION_REPOSITORY_MISMATCH')
  const root = child(taskRoot, repo!.rel_path)
  if (path.resolve(run(root, 'rev-parse', '--show-toplevel')) !== root) fail('INITIALIZATION_WORKTREE_MISMATCH')
  const started = Date.now()
  if (payload.action === 'fetch') {
    const ref = 'refs/heads/' + repo!.branch_name.replace(/^refs\/heads\//, '')
    const destination = 'refs/traceforge/initialize/' + hash(root)
    run(root, 'check-ref-format', ref)
    run(root, 'fetch', '--no-tags', '--no-recurse-submodules', '--', repo!.configured_git_url, `+${ref}:${destination}`)
    const target = run(root, 'rev-parse', `${destination}^{commit}`)
    if (run(root, 'ls-tree', '-r', target).split('\n').some(line => line.startsWith('160000 '))) fail('INITIALIZATION_SUBMODULE_UNSUPPORTED')
    return { target, fetch_seconds: (Date.now() - started) / 1000 }
  }
  if (payload.action !== 'reset' || !/^[a-f0-9]{40,64}$/.test(request.target)) fail('INITIALIZATION_TARGET_INVALID')
  run(root, 'reset', '--hard', request.target)
  run(root, 'clean', '-ffdx', '--', '.')
  if (run(root, 'rev-parse', 'HEAD') !== request.target || run(root, 'status', '--porcelain', '--untracked-files=all', '--ignored')) fail('INITIALIZATION_INCOMPLETE')
  return { completed: true, reset_seconds: (Date.now() - started) / 1000 }
}
