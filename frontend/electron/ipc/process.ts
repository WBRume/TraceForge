import { ipcMain } from 'electron'
import spawn from 'cross-spawn'
import { randomUUID } from 'node:crypto'

type RunCommandPayload = {
  cwd?: string
  command?: string
  args?: string[]
}

type RunningCommand = {
  child: ReturnType<typeof spawn>
  startedAt: number
}

const runningCommands = new Map<string, RunningCommand>()
const deniedExecutables = new Set(['rm', 'del', 'erase', 'rmdir', 'rd', 'remove-item'])
const deniedGitSubcommands = new Set(['push', 'commit', 'clean', 'reset'])

const redactSecrets = (value: string): string =>
  value
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [REDACTED]')
    .replace(/(access_token|refresh_token|token|password|secret|api[_-]?key)\s*[:=]\s*["']?[^"'\s]+/gi, '$1=[REDACTED]')
    .replace(/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g, '[REDACTED_JWT]')

const parseCommandLine = (input: string): string[] => {
  const tokens: string[] = []
  const pattern = /"([^"\\]*(?:\\.[^"\\]*)*)"|'([^'\\]*(?:\\.[^'\\]*)*)'|([^\s]+)/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(input)) !== null) {
    tokens.push((match[1] ?? match[2] ?? match[3] ?? '').replace(/\\"/g, '"').replace(/\\'/g, "'"))
  }
  return tokens
}

const normalizePayload = (payload: RunCommandPayload) => {
  const cwd = String(payload?.cwd || '').trim()
  if (!cwd) {
    throw new Error('Working directory is required')
  }
  const commandText = String(payload?.command || '').trim()
  const parts = payload?.args?.length
    ? [commandText, ...payload.args.map((arg) => String(arg))]
    : parseCommandLine(commandText)
  const file = parts[0]
  const args = parts.slice(1)
  if (!file) {
    throw new Error('Command is required')
  }
  const executable = file.toLowerCase()
  if (deniedExecutables.has(executable)) {
    throw new Error('This command is not allowed')
  }
  if (executable === 'git' && args[0] && deniedGitSubcommands.has(args[0].toLowerCase())) {
    throw new Error('This git command is not allowed')
  }
  return { cwd, file, args, commandText }
}

export const registerProcessIpc = () => {
  ipcMain.handle('sdd:process:run-command', async (event, payload: RunCommandPayload) => {
    const { cwd, file, args, commandText } = normalizePayload(payload)
    const runId = randomUUID()
    const startedAt = Date.now()
    const child = spawn(file, args, {
      cwd,
      shell: false,
      windowsHide: true,
      env: {
        ...process.env,
      },
    })

    runningCommands.set(runId, { child, startedAt })

    child.stdout?.on('data', (chunk: Buffer) => {
      event.sender.send('sdd:process:output', {
        runId,
        stream: 'stdout',
        text: redactSecrets(chunk.toString('utf8')),
        at: new Date().toISOString(),
      })
    })

    child.stderr?.on('data', (chunk: Buffer) => {
      event.sender.send('sdd:process:output', {
        runId,
        stream: 'stderr',
        text: redactSecrets(chunk.toString('utf8')),
        at: new Date().toISOString(),
      })
    })

    child.on('error', (error) => {
      runningCommands.delete(runId)
      event.sender.send('sdd:process:exit', {
        runId,
        command: commandText,
        code: null,
        signal: null,
        error: redactSecrets(error.message),
        durationMs: Date.now() - startedAt,
        finishedAt: new Date().toISOString(),
      })
    })

    child.on('exit', (code, signal) => {
      runningCommands.delete(runId)
      event.sender.send('sdd:process:exit', {
        runId,
        command: commandText,
        code,
        signal,
        durationMs: Date.now() - startedAt,
        finishedAt: new Date().toISOString(),
      })
    })

    return {
      runId,
      pid: child.pid ?? null,
      startedAt: new Date(startedAt).toISOString(),
    }
  })

  ipcMain.handle('sdd:process:cancel-command', async (_event, payload: { runId?: string }) => {
    const runId = String(payload?.runId || '').trim()
    const running = runningCommands.get(runId)
    if (!running) {
      return { ok: false, message: 'Command is not running' }
    }
    running.child.kill()
    runningCommands.delete(runId)
    return { ok: true }
  })
}
