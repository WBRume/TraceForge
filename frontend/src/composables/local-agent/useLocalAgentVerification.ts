import { computed, onBeforeUnmount, ref } from 'vue'
import { createVerificationRun, uploadVerificationLog } from '@/services/agentApi'
import type { AgentTask, ChangeProposal, VerificationRunStatus } from '@/types/agent'
import type { DesktopCommandExitEvent, DesktopCommandOutputEvent, SddDesktopApi } from '@/types/sddDesktop'
import { excerptText, redactLog } from './localAgentUtils'

type VerificationOptions = {
  desktop: SddDesktopApi
  task: AgentTask
  proposal: ChangeProposal
  repoPath: string
  command: string
}

const logLines = ref<string[]>([])
const runningRunId = ref<string | null>(null)
const lastExit = ref<DesktopCommandExitEvent | null>(null)
let cleanupOutput: (() => void) | null = null
let cleanupExit: (() => void) | null = null
let activeOptions: VerificationOptions | null = null
let startedAt = ''

const appendLog = (line: string) => {
  logLines.value.push(redactLog(line))
}

const handleOutput = (event: DesktopCommandOutputEvent) => {
  if (event.runId !== runningRunId.value) return
  appendLog(`[${event.stream}] ${event.text}`)
}

const handleExit = async (event: DesktopCommandExitEvent) => {
  if (event.runId !== runningRunId.value || !activeOptions) return
  lastExit.value = event
  appendLog(`[exit] code=${event.code ?? 'null'} signal=${event.signal ?? 'null'}`)
  if (event.error) appendLog(`[error] ${event.error}`)

  const status: VerificationRunStatus = event.error
    ? 'failed'
    : event.signal
      ? 'cancelled'
      : event.code === 0
        ? 'success'
        : 'failed'
  const finishedAt = event.finishedAt || new Date().toISOString()
  const logText = logLines.value.join('')
  const localHead = await activeOptions.desktop.git.getHeadSha(activeOptions.repoPath).catch(() => ({ headSha: null }))
  const run = await createVerificationRun({
    taskId: activeOptions.task.id,
    proposalId: activeOptions.proposal.id,
    command: activeOptions.command,
    status,
    durationMs: event.durationMs,
    baseCommitSha: activeOptions.proposal.base_commit_sha,
    localHeadSha: localHead.headSha,
    logExcerpt: excerptText(logText, 4000),
    startedAt,
    finishedAt,
    osName: activeOptions.desktop.platform,
  })
  await uploadVerificationLog({
    taskId: activeOptions.task.id,
    runId: run.id,
    logText,
    logExcerpt: excerptText(logText, 4000),
  })
  runningRunId.value = null
  activeOptions = null
}

export const useLocalAgentVerification = () => {
  const isRunning = computed(() => Boolean(runningRunId.value))
  const logText = computed(() => logLines.value.join(''))

  const ensureListeners = (desktop: SddDesktopApi) => {
    if (!cleanupOutput) cleanupOutput = desktop.process.onCommandOutput(handleOutput)
    if (!cleanupExit) cleanupExit = desktop.process.onCommandExit((event) => {
      void handleExit(event)
    })
  }

  const startVerification = async (options: VerificationOptions) => {
    if (runningRunId.value) {
      throw new Error('已有验证命令正在运行')
    }
    ensureListeners(options.desktop)
    logLines.value = []
    lastExit.value = null
    activeOptions = options
    startedAt = new Date().toISOString()
    appendLog(`$ ${options.command}\n`)
    const run = await options.desktop.process.runCommand({
      cwd: options.repoPath,
      command: options.command,
    })
    runningRunId.value = run.runId
  }

  const cancelVerification = async (desktop: SddDesktopApi) => {
    if (!runningRunId.value) return
    await desktop.process.cancelCommand(runningRunId.value)
  }

  onBeforeUnmount(() => {
    cleanupOutput?.()
    cleanupExit?.()
    cleanupOutput = null
    cleanupExit = null
  })

  return {
    isRunning,
    lastExit,
    logText,
    logLines,
    startVerification,
    cancelVerification,
  }
}
