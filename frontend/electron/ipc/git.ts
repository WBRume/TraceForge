import { dialog, ipcMain } from 'electron'
import { execFile } from 'node:child_process'
import { mkdir } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { remoteUrlsMatch } from '../../src/composables/local-agent/localAgentUtils'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)
const GIT_TIMEOUT_MS = 120_000
const GIT_MAX_BUFFER = 20 * 1024 * 1024
const ALLOWED_GIT_COMMANDS = new Set([
  'remote',
  'worktree',
  'rev-parse',
  'config',
  'status',
  'fetch',
  'checkout',
  'pull',
  'apply',
  'diff',
])

export type GitCommandResult = {
  ok: boolean
  stdout: string
  stderr: string
  exitCode?: number
}

type GitStatusEntry = {
  code: string
  path: string
}

const toErrorMessage = (error: unknown): string => {
  if (error instanceof Error && error.message) return error.message
  return String(error || 'Git command failed')
}

const toExecError = (error: unknown): { stdout: string; stderr: string; exitCode?: number; message: string } => {
  const record = error as {
    stdout?: unknown
    stderr?: unknown
    code?: unknown
    message?: unknown
  }
  return {
    stdout: String(record?.stdout ?? ''),
    stderr: String(record?.stderr ?? ''),
    exitCode: typeof record?.code === 'number' ? record.code : undefined,
    message: String(record?.message || toErrorMessage(error)),
  }
}

const assertRepoPath = (repoPath: unknown): string => {
  const normalized = String(repoPath || '').trim()
  if (!normalized) {
    throw new Error('Repository path is required')
  }
  return normalized
}

const assertSafeBranchName = (branch: unknown): string => {
  const normalized = String(branch || '').trim()
  if (!normalized) {
    throw new Error('Branch name is required')
  }
  if (normalized.startsWith('-') || normalized.includes('\0')) {
    throw new Error('Invalid branch name')
  }
  return normalized
}

export const runGit = async (
  repoPath: string,
  args: string[],
  options?: { allowFailure?: boolean; timeoutMs?: number },
): Promise<GitCommandResult> => {
  const cwd = assertRepoPath(repoPath)
  const command = args[0]
  if (!command || !ALLOWED_GIT_COMMANDS.has(command)) {
    throw new Error('Git command is not allowed')
  }
  if (args.includes('push') || args.includes('commit')) {
    throw new Error('Git push/commit is not allowed from SDD Native')
  }

  try {
    const result = await execFileAsync('git', args, {
      cwd,
      windowsHide: true,
      timeout: options?.timeoutMs ?? GIT_TIMEOUT_MS,
      maxBuffer: GIT_MAX_BUFFER,
      env: {
        ...process.env,
        GIT_TERMINAL_PROMPT: '0',
      },
    })
    return {
      ok: true,
      stdout: String(result.stdout || ''),
      stderr: String(result.stderr || ''),
    }
  } catch (error: unknown) {
    const execError = toExecError(error)
    if (options?.allowFailure) {
      return {
        ok: false,
        stdout: execError.stdout,
        stderr: execError.stderr || execError.message,
        exitCode: execError.exitCode,
      }
    }
    throw new Error(execError.stderr || execError.message)
  }
}

const parseStatus = (raw: string): GitStatusEntry[] =>
  raw
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean)
    .map((line) => ({
      code: line.slice(0, 2),
      path: line.slice(3).trim(),
    }))

export const listUnmergedFiles = async (repoPath: string): Promise<string[]> => {
  const result = await runGit(repoPath, ['diff', '--name-only', '--diff-filter=U'], {
    allowFailure: true,
  })
  return result.stdout.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
}

const getFetchRemotes = async (repoPath: string) => {
  const names = (await runGit(repoPath, ['remote'])).stdout.trim().split(/\r?\n/).filter(Boolean)
  const result: { name: string; fetchUrl: string }[] = []
  for (const name of names) {
    for (const fetchUrl of (await runGit(repoPath, ['remote', 'get-url', '--all', name])).stdout.trim().split(/\r?\n/).filter(Boolean)) result.push({ name, fetchUrl })
  }
  return result
}

export const registerGitIpc = () => {
  ipcMain.handle('sdd:git:select-directory', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory'],
      title: 'Select local repository',
    })
    return {
      canceled: result.canceled,
      path: result.filePaths[0] || null,
    }
  })

  ipcMain.handle('sdd:git:validate-repo', async (_event, payload: { repoPath?: string }) => {
    const repoPath = assertRepoPath(payload?.repoPath)
    const result = await runGit(repoPath, ['rev-parse', '--is-inside-work-tree'], {
      allowFailure: true,
    })
    return {
      ok: result.ok && result.stdout.trim() === 'true',
      stdout: result.stdout,
      stderr: result.stderr,
    }
  })

  ipcMain.handle('sdd:git:get-remote-url', async (_event, payload: { repoPath?: string }) => {
    const repoPath = assertRepoPath(payload?.repoPath)
    const result = await runGit(repoPath, ['config', '--get', 'remote.origin.url'])
    return { remoteUrl: result.stdout.trim() }
  })

  ipcMain.handle('sdd:git:get-remotes', async (_event, payload: { repoPath: string }) => {
    return getFetchRemotes(assertRepoPath(payload.repoPath))
  })
  ipcMain.handle('sdd:git:prepare-patch-worktree', async (_event, payload: { repoPath: string; remoteUrl: string; baseSha: string; baseBranch: string; branch: string }) => {
    const repoPath = assertRepoPath(payload.repoPath)
    if (!/^[0-9a-f]{40,64}$/i.test(payload.baseSha) || !/^sdd\/[a-zA-Z0-9_-]+\/v[0-9]+(?:-[a-zA-Z0-9_.-]+)?$/.test(payload.branch)) throw new Error('Invalid patch identity')
    if (!payload.baseBranch || payload.baseBranch.startsWith('-')) throw new Error('Invalid base branch')
    const hasBase = async () => (await runGit(repoPath, ['rev-parse', '--verify', `${payload.baseSha}^{commit}`], { allowFailure: true })).ok
    if (!await hasBase()) {
      // Forks need not expose the server's URL or branch name. Fetch only remotes
      // already configured by the user, without modifying the current branch/index.
      const remotes = await getFetchRemotes(repoPath)
      const preferred = remotes.filter(item => remoteUrlsMatch(item.fetchUrl, payload.remoteUrl))
      const names = [...new Set([...preferred, ...remotes].map(item => item.name))]
      for (const name of names) {
        await runGit(repoPath, ['fetch', '--no-tags', '--', name], { allowFailure: true, timeoutMs: 300_000 })
        if (await hasBase()) break
      }
      if (!await hasBase()) throw new Error(`本地仓库缺少补丁基准 commit ${payload.baseSha}，请同步包含该提交的主仓或 fork 后重试；尚未创建 worktree`)
    }
    const parent = resolve(dirname(repoPath), '.traceforge-patch-worktrees')
    const target = join(parent, payload.branch.replaceAll('/', '-'))
    await mkdir(parent, { recursive: true })
    await runGit(repoPath, ['worktree', 'add', '-b', payload.branch, target, payload.baseSha])
    return { path: target }
  })

  ipcMain.handle('sdd:git:get-status', async (_event, payload: { repoPath?: string }) => {
    const repoPath = assertRepoPath(payload?.repoPath)
    const result = await runGit(repoPath, ['status', '--porcelain=v1', '-uall'])
    const entries = parseStatus(result.stdout)
    return {
      isClean: entries.length === 0,
      raw: result.stdout,
      entries,
      unmergedFiles: entries
        .filter((entry) => entry.code.includes('U') || entry.code === 'AA' || entry.code === 'DD')
        .map((entry) => entry.path),
    }
  })

  ipcMain.handle('sdd:git:fetch-origin', async (_event, payload: { repoPath?: string }) => {
    const repoPath = assertRepoPath(payload?.repoPath)
    return runGit(repoPath, ['fetch', 'origin', '--prune'], { timeoutMs: 300_000 })
  })

  ipcMain.handle('sdd:git:checkout-branch', async (_event, payload: { repoPath?: string; branch?: string }) => {
    const repoPath = assertRepoPath(payload?.repoPath)
    const branch = assertSafeBranchName(payload?.branch)
    return runGit(repoPath, ['checkout', branch])
  })

  ipcMain.handle('sdd:git:pull-ff-only', async (_event, payload: { repoPath?: string; branch?: string }) => {
    const repoPath = assertRepoPath(payload?.repoPath)
    const branch = String(payload?.branch || '').trim()
    const args = branch ? ['pull', '--ff-only', 'origin', assertSafeBranchName(branch)] : ['pull', '--ff-only']
    return runGit(repoPath, args, { timeoutMs: 300_000 })
  })

  ipcMain.handle('sdd:git:create-local-branch', async (_event, payload: { repoPath?: string; branch?: string }) => {
    const repoPath = assertRepoPath(payload?.repoPath)
    const branch = assertSafeBranchName(payload?.branch)
    return runGit(repoPath, ['checkout', '-b', branch])
  })

  ipcMain.handle('sdd:git:get-head-sha', async (_event, payload: { repoPath?: string }) => {
    const repoPath = assertRepoPath(payload?.repoPath)
    const result = await runGit(repoPath, ['rev-parse', 'HEAD'])
    return { headSha: result.stdout.trim() }
  })
}
