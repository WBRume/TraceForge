import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/utils/api'
import { useAuthStore } from './auth'
import { usePinnedFloatsStore } from './pinnedFloats'
import type { TaskRuntimeEvent } from '@/types/taskAwareness'

export const LONG_RUN_MS = 10_000
export const FINISHED_DWELL_MS = 8_000
type Intent = { taskId: string; requestId?: string; jobId?: string; at: number; terminalInView?: boolean }
type Run = { event: TaskRuntimeEvent; dismissed: boolean; consumed: number; nativeVersion: number; expiresAt?: number; wasAway: boolean }

/** Qualification is seeded exclusively by a successful user submission path. */
export const useTaskAwarenessStore = defineStore('taskAwareness', () => {
  const auth = useAuthStore()
  const floats = usePinnedFloatsStore()
  const runs = ref<Record<string, Run>>({})
  const outputs = ref<Record<string, { text: string; revision: number }>>({})
  let intents: Intent[] = []
  let ownerId = ''
  let taskId = ''
  let focused = true
  let timer: ReturnType<typeof setTimeout> | undefined
  let generation = 0
  const nativeUnread = new Set<string>()
  const restoring = new Set<string>()
  let attentionActive = false
  const serverScope = () => String(api.defaults?.baseURL || window.location.origin)
  const storageKey = () => `traceforge.awareness:${encodeURIComponent(serverScope())}:${ownerId}`
  const save = () => {
    try { sessionStorage.setItem(storageKey(), JSON.stringify({ intents, runs: runs.value })) } catch { /* Optional storage. */ }
  }
  const longEnough = (event: TaskRuntimeEvent, now: number) => {
    const start = Date.parse(event.run.started_at)
    const end = event.run.finished_at ? Date.parse(event.run.finished_at) : now
    return Number.isFinite(start) && end - start >= LONG_RUN_MS
  }
  const nativeSet = (flash: boolean) => {
    if (flash) attentionActive = true
    const hitlCount = [...nativeUnread].filter(id => runs.value[id]?.event.event_type === 'AI_HITL_SUSPENDED').length
    void window.sddDesktop?.attention?.set({ flash: attentionActive && !focused, hitlCount }).catch(() => {})
  }
  const reconcile = () => {
    clearTimeout(timer)
    const now = Date.now()
    let next = Infinity
    let flash = false
    for (const [id, run] of Object.entries(runs.value)) {
      if (restoring.has(id)) continue
      const event = run.event
      const inView = focused && taskId === event.task.id
      const active = ['AI_RUNNING', 'AI_HITL_SUSPENDED'].includes(event.event_type)
      const stopped = ['AI_RUN_INTERRUPTED', 'AI_RUN_STOPPED'].includes(event.event_type)
      if (active && !inView) run.wasAway = true
      const qualified = event.event_type === 'AI_RUN_ERROR' || longEnough(event, now)
      const item = floats.items.find(item => item.kind === 'task' && item.taskId === event.task.id)
      const manual = item && item.source !== 'automatic'
      const ownProbe = item?.source === 'automatic' && item.runId === id
      if (manual) {
        item.runId = id; item.runtimeState = event.event_type; item.runtimeSummary = event.summary
      }
      if (!active) nativeUnread.delete(id)
      if (inView) {
        run.consumed = event.run.version
        if (ownProbe) floats.unpin(item.id)
      } else if (qualified && !run.dismissed && !manual && !stopped
        && (active || (run.wasAway && run.consumed < event.run.version))) {
        if (event.event_type === 'AI_RUN_FINISHED') {
          run.expiresAt ??= now + FINISHED_DWELL_MS
          if (run.expiresAt <= now) {
            run.consumed = event.run.version
            if (ownProbe) floats.unpin(item.id)
          } else {
            floats.dockRuntime(event)
            next = Math.min(next, run.expiresAt)
          }
        } else floats.dockRuntime(event)
      } else if ((!qualified || stopped) && ownProbe) {
        floats.unpin(item.id)
      }
      if (active && !qualified) next = Math.min(next, Date.parse(event.run.started_at) + LONG_RUN_MS)
      if (qualified && ['AI_HITL_SUSPENDED', 'AI_RUN_FINISHED', 'AI_RUN_ERROR'].includes(event.event_type)
        && run.nativeVersion < event.run.version) {
        run.nativeVersion = event.run.version
        if (!focused && !run.dismissed && run.consumed < event.run.version) {
          flash = true
          if (event.event_type === 'AI_HITL_SUSPENDED') nativeUnread.add(id)
        }
      }
    }
    nativeSet(flash)
    save()
    if (Number.isFinite(next)) timer = setTimeout(reconcile, Math.max(1, next - Date.now()))
  }

  const ingest = (event: TaskRuntimeEvent) => {
    if (!event?.run?.id || !event.run.started_at || event.initiator?.id !== ownerId
      || !['AI_RUNNING', 'AI_HITL_SUSPENDED', 'AI_RUN_FINISHED', 'AI_RUN_ERROR', 'AI_RUN_INTERRUPTED', 'AI_RUN_STOPPED'].includes(event.event_type)) return
    const id = event.run.id
    const previous = runs.value[id]
    if (previous && previous.event.run.version > event.run.version) return
    if (previous && previous.event.run.version === event.run.version) { if (restoring.delete(id)) reconcile(); return }
    restoring.delete(id)
    const intent = intents.find(intent => intent.jobId === id || (!intent.jobId && intent.taskId === event.task.id
      && (intent.requestId ? intent.requestId === event.run.client_message_id : Date.parse(event.run.started_at) >= intent.at - 1000)))
    if (!previous && !intent) return
    if (intent) intent.jobId = id
    if (!previous) for (const [oldId, old] of Object.entries(runs.value)) {
      if (old.event.task.id === event.task.id && Date.parse(old.event.run.started_at) <= Date.parse(event.run.started_at)) {
        old.dismissed = true; old.consumed = old.event.run.version; nativeUnread.delete(oldId)
        const probe = floats.items.find(item => item.source === 'automatic' && item.runId === oldId)
        if (probe) floats.unpin(probe.id)
      }
    }
    runs.value[id] = { event, dismissed: previous?.dismissed || intent?.terminalInView || false, consumed: intent?.terminalInView ? event.run.version : previous?.consumed ?? 0,
      nativeVersion: previous?.nativeVersion ?? 0, wasAway: previous?.wasAway ?? (!focused || taskId !== event.task.id) }
    reconcile()
    window.dispatchEvent(new CustomEvent('task-context-changed', { detail: { taskId: event.task.id } }))
  }
  const arm = (task: string, requestId?: string, jobId?: string) => {
    if (!task || !ownerId) return
    const old = intents.find(intent => intent.taskId === task && intent.requestId === requestId)
    if (old) { if (jobId) old.jobId = jobId }
    else intents.push({ taskId: task, requestId, jobId, at: Date.now() })
    intents = intents.slice(-100)
    save()
    if (jobId) void refresh()
  }
  const disarm = (task: string, requestId?: string) => {
    intents = intents.filter(intent => intent.taskId !== task || intent.requestId !== requestId)
    save()
  }
  const observeForegroundTerminal = (job: any) => {
    if (!focused || job?.task_id !== taskId || job.creator_id !== ownerId
      || !['SUCCESS', 'FAILED', 'INTERRUPTED', 'CANCELLED', 'REVERTED'].includes(job.status)) return
    const run = runs.value[job.id]
    const intent = intents.find(item => item.jobId === job.id || (!item.jobId && item.taskId === taskId
      && item.requestId && item.requestId === job.context_json?.client_message_id))
    if (!run && !intent) return
    if (intent) { intent.jobId = job.id; intent.terminalInView = true }
    if (run) { run.dismissed = true; run.consumed = run.event.run.version }
    const probe = floats.items.find(item => item.source === 'automatic' && item.runId === job.id)
    if (probe) floats.unpin(probe.id)
    nativeUnread.delete(job.id); reconcile()
  }
  const refresh = async () => {
    const version = generation
    const ids = [...new Set([...Object.keys(runs.value), ...intents.flatMap(item => item.jobId ? [item.jobId] : [])])].slice(-100)
    const requests = intents.flatMap(item => !item.jobId && item.requestId ? [item.requestId] : []).slice(-100)
    if ((!ids.length && !requests.length) || !auth.isAuthenticated) return
    try {
      const { data } = await api.get('/task-awareness/runs', { params: { job_ids: ids.join(','), client_message_ids: requests.join(',') } })
      if (version === generation) {
        const events: TaskRuntimeEvent[] = data.runs || []
        const returned = new Set(events.map(event => event.run.id))
        for (const id of ids) if (runs.value[id] && !returned.has(id)) {
          const probe = floats.items.find(item => item.source === 'automatic' && item.runId === id)
          if (probe) floats.unpin(probe.id)
          delete runs.value[id]; restoring.delete(id); nativeUnread.delete(id)
          intents = intents.filter(intent => intent.jobId !== id)
        }
        for (const event of events) ingest(event)
        reconcile()
      }
    } catch { /* Existing WS remains authoritative. Reconnect retries this snapshot. */ }
  }
  const view = (currentTaskId: string, windowFocused: boolean) => {
    taskId = currentTaskId; focused = windowFocused
    if (focused) { nativeUnread.clear(); attentionActive = false; nativeSet(false) }
    reconcile()
  }
  const dismiss = (id?: string) => {
    if (id && runs.value[id]) { runs.value[id].dismissed = true; nativeUnread.delete(id) }
    reconcile()
  }
  const consume = (id?: string) => {
    const run = id ? runs.value[id] : undefined
    if (run?.event.event_type === 'AI_RUN_FINISHED') {
      run.consumed = run.event.run.version; run.expiresAt = undefined
      reconcile()
    }
  }
  const receiveOutput = (frame: any) => {
    if (!frame?.job_id || !runs.value[frame.job_id]) return
    const old = outputs.value[frame.task_id] || { text: '', revision: 0 }
    const payload = frame.payload || {}
    if (frame.kind === 'thinking') outputs.value[frame.task_id] = {
      text: (payload.delta ? old.text + payload.delta : String(payload.content || '')).slice(-12_000), revision: old.revision + 1,
    }
    else if (frame.kind === 'tool_result') outputs.value[frame.task_id] = { text: String(payload.output || '').slice(-12_000), revision: old.revision + 1 }
    else if (frame.kind === 'chat_message') {
      outputs.value[frame.task_id] = { text: '', revision: old.revision + 1 }
      window.dispatchEvent(new CustomEvent('task-context-changed', { detail: { taskId: frame.task_id } }))
    }
  }
  const reset = (userId = '') => {
    generation++; clearTimeout(timer); nativeUnread.clear(); restoring.clear(); attentionActive = false; nativeSet(false)
    runs.value = {}; outputs.value = {}; intents = []; floats.clearAutomatic(); ownerId = userId
    floats.scope(userId, serverScope())
    if (userId) try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey()) || '{}')
      intents = Array.isArray(saved.intents) ? saved.intents.slice(-100) : []
      // Same-tab intent survives reload; new tabs never seed from server history.
      for (const [id, run] of Object.entries(saved.runs || {})) {
        const item = run as Run
        if (item.event?.initiator?.id === userId && item.event.run?.id === id) { runs.value[id] = item; restoring.add(id) }
      }
    } catch { /* No restored intent. */ }
  }
  const stop = () => { clearTimeout(timer); nativeUnread.clear(); attentionActive = false; nativeSet(false) }
  return { runs, outputs, arm, disarm, ingest, refresh, view, dismiss, consume, receiveOutput, reset, stop, observeForegroundTerminal }
})
