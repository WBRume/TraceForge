import { ref } from 'vue'

import type {
  TerminalCommandTone,
  TerminalLocalEcho,
  TerminalLocalEchoKind,
} from '@/utils/chat-terminal/timeline-types'

const SUPPORTED_COMMANDS = [
  'help',
  'start',
  'send',
  'init',
  'interrupt',
  'complete',
  'status',
  'clear',
  'clear-all',
] as const

type SupportedCommand = (typeof SUPPORTED_COMMANDS)[number]

const RUNNING_ALLOWED_COMMANDS = new Set<SupportedCommand>([
  'help',
  'status',
  'interrupt',
  'clear',
])

interface ClearHistoryResult {
  deleted_chat_messages: number
  deleted_execution_logs: number
  deleted_total: number
}

export interface ChatTerminalBridge {
  currentTask: { id?: string; name?: string; status?: string } | null
  messages: any[]
  terminalLogs: any[]
  highlightedTerminalLogId?: string
  statusCards: any[]
  activeHitlCards: any[]
  resultsSummary: { history?: any[] }
  loadingMore: boolean
  hasMore: boolean
  engineRunning: boolean
  isTaskPreStart: boolean
  isTerminalStatus: boolean
  canManageTaskStatus: boolean
  loadOlderMessages: () => Promise<void>
  submitHitl: (cardId: string, response: string) => void
  formatTime: (value: string) => string
  formatToolInput: (value: unknown) => string
  startTask: () => Promise<boolean>
  sendChatContent: (content: string) => Promise<boolean>
  initializeTaskWithReason: (reason?: string) => Promise<boolean>
  interruptCurrentRun: () => Promise<boolean>
  interruptTaskNow: () => Promise<boolean>
  completeTaskNow: () => Promise<boolean>
  clearTaskHistory: () => Promise<ClearHistoryResult | null>
  setTerminalContainer: (container: HTMLElement | null) => void
  t: (key: string, values?: Record<string, unknown>) => string
}

interface ParsedCommand {
  command: SupportedCommand | 'unknown'
  raw: string
}

const isSupportedCommand = (name: string): name is SupportedCommand => {
  return (SUPPORTED_COMMANDS as readonly string[]).includes(name)
}

const parseCommand = (rawInput: string): ParsedCommand => {
  const normalized = rawInput.trim()
  if (!normalized.startsWith('/')) {
    return { command: 'send', raw: normalized }
  }
  const commandName = normalized.slice(1).split(/\s+/, 1)[0].toLowerCase()
  if (!isSupportedCommand(commandName)) {
    return { command: 'unknown', raw: normalized }
  }
  return {
    command: commandName,
    raw: normalized,
  }
}

const extractCommandPayload = (rawInput: string, command: SupportedCommand): string => {
  const slash = `/${command}`
  if (!rawInput.toLowerCase().startsWith(slash)) return ''
  return rawInput.slice(slash.length).trim()
}

export const useChatTerminalController = (vm: ChatTerminalBridge) => {
  const inputValue = ref('')
  const localEchoes = ref<TerminalLocalEcho[]>([])
  const commandHistory = ref<string[]>([])
  const historyCursor = ref<number>(-1)
  const historyDraft = ref('')
  const clearSinceMs = ref<number | null>(null)
  const commandExecuting = ref(false)

  const appendEcho = (kind: TerminalLocalEchoKind, content: string) => {
    localEchoes.value.push({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      kind,
      content,
      createdAt: new Date().toISOString(),
    })
  }

  const appendCommandEcho = (content: string, tone: TerminalCommandTone) => {
    localEchoes.value.push({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      kind: 'command',
      content,
      createdAt: new Date().toISOString(),
      tone,
    })
  }

  const recordHistory = (raw: string) => {
    const normalized = raw.trim()
    if (!normalized) return
    commandHistory.value.push(normalized)
    historyCursor.value = -1
    historyDraft.value = ''
  }

  const resetForTaskChange = () => {
    inputValue.value = ''
    localEchoes.value = []
    commandHistory.value = []
    historyCursor.value = -1
    historyDraft.value = ''
    clearSinceMs.value = null
    commandExecuting.value = false
  }

  const completeInput = () => {
    const normalized = inputValue.value.trim()
    if (!normalized.startsWith('/')) return

    const token = normalized.slice(1)
    if (!token) {
      inputValue.value = '/help'
      return
    }

    if (!token.includes(' ')) {
      const matched = SUPPORTED_COMMANDS.filter((command) => command.startsWith(token.toLowerCase()))
      if (matched.length === 1) {
        inputValue.value = `/${matched[0]} `
        return
      }
      if (matched.length > 1) {
        appendEcho('info', matched.map((item) => `/${item}`).join('  '))
      }
      return
    }

    const [name, ...rest] = token.split(/\s+/)
    if (name !== 'clear-all') return
    const last = rest[rest.length - 1] || ''
    if ('--confirm'.startsWith(last)) {
      const next = rest.length > 1
        ? rest.slice(0, rest.length - 1).concat('--confirm').join(' ')
        : '--confirm'
      inputValue.value = `/clear-all ${next}`.trim()
    }
  }

  const browseHistoryPrev = () => {
    if (!commandHistory.value.length) return
    if (historyCursor.value === -1) {
      historyDraft.value = inputValue.value
      historyCursor.value = commandHistory.value.length - 1
      inputValue.value = commandHistory.value[historyCursor.value]
      return
    }
    if (historyCursor.value > 0) {
      historyCursor.value -= 1
      inputValue.value = commandHistory.value[historyCursor.value]
    }
  }

  const browseHistoryNext = () => {
    if (!commandHistory.value.length || historyCursor.value === -1) return
    if (historyCursor.value < commandHistory.value.length - 1) {
      historyCursor.value += 1
      inputValue.value = commandHistory.value[historyCursor.value]
      return
    }
    historyCursor.value = -1
    inputValue.value = historyDraft.value
  }

  const emitStatus = () => {
    const taskName = vm.currentTask?.name || '-'
    const taskStatus = vm.currentTask?.status || '-'
    const running = vm.engineRunning ? 'RUNNING' : 'IDLE'
    appendEcho('info', `task=${taskName} status=${taskStatus} engine=${running}`)
    appendEcho('info', `messages=${vm.messages.length} logs=${vm.terminalLogs.length}`)
  }

  const runSend = async (text: string) => {
    if (!text.trim()) {
      appendEcho('warning', vm.t('chat.cli_error_send_empty'))
      return
    }
    const sent = await vm.sendChatContent(text)
    if (!sent) {
      appendEcho('warning', vm.t('chat.cli_error_send_rejected'))
    }
  }

  const runCommand = async (parsed: ParsedCommand): Promise<void> => {
    if (parsed.command === 'unknown') {
      appendEcho('error', vm.t('chat.cli_error_unknown_command'))
      return
    }

    const isBlocked = vm.engineRunning && !RUNNING_ALLOWED_COMMANDS.has(parsed.command)
    if (isBlocked) {
      appendEcho('warning', vm.t('chat.cli_running_blocked'))
      return
    }

    switch (parsed.command) {
      case 'help': {
        appendEcho('info', vm.t('chat.cli_help_title'))
        appendEcho('info', '/help /start /send <text> /init [reason] /interrupt /complete /status /clear /clear-all --confirm')
        break
      }
      case 'status': {
        emitStatus()
        break
      }
      case 'clear': {
        clearSinceMs.value = Date.now()
        localEchoes.value = []
        break
      }
      case 'clear-all': {
        if (!vm.canManageTaskStatus) {
          appendEcho('error', vm.t('chat.errors.no_permission_manage_task_status'))
          break
        }
        const payload = extractCommandPayload(parsed.raw, 'clear-all')
        const confirmed = payload.split(/\s+/).some((token) => token === '--confirm')
        if (!confirmed) {
          appendEcho('warning', vm.t('chat.cli_clear_all_needs_confirm'))
          break
        }
        const result = await vm.clearTaskHistory()
        if (!result) {
          appendEcho('error', vm.t('chat.cli_clear_all_failed'))
          break
        }
        appendEcho('success', vm.t('chat.cli_clear_all_done', { count: result.deleted_total }))
        break
      }
      case 'start': {
        const ok = await vm.startTask()
        appendEcho(ok ? 'success' : 'warning', ok ? vm.t('chat.cli_start_done') : vm.t('chat.cli_start_failed'))
        break
      }
      case 'send': {
        const payload = parsed.raw.startsWith('/')
          ? extractCommandPayload(parsed.raw, 'send')
          : parsed.raw
        await runSend(payload)
        break
      }
      case 'init': {
        const reason = extractCommandPayload(parsed.raw, 'init')
        const ok = await vm.initializeTaskWithReason(reason || undefined)
        appendEcho(ok ? 'success' : 'warning', ok ? vm.t('chat.cli_init_done') : vm.t('chat.cli_init_failed'))
        break
      }
      case 'interrupt': {
        const ok = await vm.interruptCurrentRun()
        appendEcho(ok ? 'success' : 'warning', ok ? vm.t('chat.cli_interrupt_done') : vm.t('chat.cli_interrupt_failed'))
        break
      }
      case 'complete': {
        const ok = await vm.completeTaskNow()
        appendEcho(ok ? 'info' : 'warning', ok ? vm.t('chat.closeout.opened') : vm.t('chat.cli_complete_failed'))
        break
      }
    }
  }

  const resolveCommandTone = (parsed: ParsedCommand): TerminalCommandTone => {
    if (parsed.command === 'unknown') return 'danger'
    if (parsed.command === 'help' || parsed.command === 'status') return 'query'
    if (parsed.command === 'clear') return 'local'
    if (parsed.command === 'interrupt' || parsed.command === 'complete' || parsed.command === 'clear-all') return 'danger'
    if (parsed.command === 'start' || parsed.command === 'send' || parsed.command === 'init') return 'operate'
    return 'state'
  }

  const submitInput = async () => {
    const raw = inputValue.value.trim()
    if (!raw) return
    if (commandExecuting.value) {
      appendEcho('warning', vm.t('chat.cli_command_busy'))
      return
    }

    const parsed = parseCommand(raw)
    appendCommandEcho(raw, resolveCommandTone(parsed))
    recordHistory(raw)
    inputValue.value = ''
    commandExecuting.value = true
    try {
      await runCommand(parsed)
    } finally {
      commandExecuting.value = false
    }
  }

  return {
    browseHistoryNext,
    browseHistoryPrev,
    clearSinceMs,
    commandExecuting,
    completeInput,
    inputValue,
    localEchoes,
    resetForTaskChange,
    submitInput,
  }
}
