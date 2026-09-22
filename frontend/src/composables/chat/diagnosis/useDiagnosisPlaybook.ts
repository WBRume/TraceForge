import { computed, readonly, shallowRef, watch } from 'vue'
import api from '@/utils/api'
import type { PlaybookRun } from '@/types/diagnosisPlaybook'

export function useDiagnosisPlaybook(options: { workspaceId: () => string; taskId: () => string; enabled: () => boolean; eligible?: () => boolean }) {
  const run = shallowRef<PlaybookRun | null>(null)
  const error = shallowRef('')
  const busy = shallowRef(false)
  const elapsed = shallowRef(0)
  const tail = shallowRef('')
  const agentText = shallowRef('')
  const agentCalls = new Map<string, string>()
  let discoveredRun = false
  const enabled = () => options.enabled() || discoveredRun
  let generation = 0
  let controller: AbortController | null = null
  let recovery: Promise<void> | null = null
  let pendingCommand: { digest: string; key: string } | null = null
  const base = () => `/workspaces/${options.workspaceId()}/tasks/${options.taskId()}/playbook-runs`
  const accept = (next: PlaybookRun, captured: number) => {
    if (captured !== generation || next.task_id !== options.taskId()) return
    if (run.value?.id === next.id && next.state_version < run.value.state_version) return
    run.value = next
  }
  const reload = async () => {
    if (!enabled() || !options.taskId()) return
    if (recovery) return recovery
    const captured = generation
    const url = base()
    const current = run.value
    controller = new AbortController()
    const signal = controller.signal
    recovery = (async () => {
      try {
        if (current) {
          const { data } = await api.get(`${url}/${current.id}/events`, { params: { after_seq: current.event_seq }, signal })
          accept(data.snapshot, captured)
        } else {
          const { data } = await api.get(url, { signal })
          if (data.items?.[0]) accept(data.items[0], captured)
        }
      } catch (e: any) {
        if (captured === generation && !signal.aborted) error.value = e.response?.data?.detail?.code || e.message
      } finally {
        if (captured === generation) recovery = null
      }
    })()
    return recovery
  }
  watch(() => [options.workspaceId(), options.taskId(), options.enabled()], (_value, _old, cleanup) => {
    generation++
    controller?.abort()
    recovery = null
    run.value = null
    tail.value = ''
    agentText.value = ''
    agentCalls.clear()
    elapsed.value = 0
    error.value = ''
    busy.value = false
    pendingCommand = null
    discoveredRun = false
    void reload()
    cleanup(() => { controller?.abort(); generation++ })
  }, { immediate: true })
  const onEvent = (type: string, payload: any) => {
    if (payload.task_id !== options.taskId()) return
    // Another collaborator may attach a run after this task snapshot loaded.
    // Its committed creation event is enough to enable one snapshot fetch.
    if (!enabled() && options.eligible?.() && type === 'playbook.created') discoveredRun = true
    if (!enabled()) return
    if (type === 'playbook.resync') { void reload(); return }
    if (type === 'playbook.guide_updated') return
    if (run.value && (payload.run_id !== run.value.id || payload.run_epoch < run.value.run_epoch)) return
    if (type === 'playbook.agent_event' && ['text', 'result'].includes(payload.provider_type)) {
      const content = payload.payload?.text || payload.payload?.result || ''
      if (typeof content !== 'string' || !content || !run.value) return
      const callId = payload.call_id || payload.scope_id || 'main'
      const previous = agentCalls.get(callId) || ''
      agentCalls.set(callId, (payload.provider_type === 'result' ? content : previous + content).slice(-40000))
      agentText.value = [...agentCalls.values()].join('\n\n').slice(-40000)
      return
    }
    if (type === 'runner.heartbeat') { elapsed.value = payload.elapsed_seconds; return }
    if (type === 'runner.tail') { tail.value = (tail.value + payload.content).slice(-40000); return }
    if (!Number.isInteger(payload.event_seq)) return
    if (payload.event_seq <= (run.value?.event_seq ?? 0)) return
    if (payload.payload?.snapshot && payload.event_seq === (run.value?.event_seq ?? 0) + 1) accept(payload.payload.snapshot, generation)
    else void reload()
  }
  const command = async (action: string, extra: Record<string, unknown> = {}) => {
    if (!run.value || busy.value) return
    const captured = generation
    const request = { action, expected_state_version: run.value.state_version, ...extra }
    const signature = JSON.stringify(request)
    if (pendingCommand?.digest !== signature) pendingCommand = { digest: signature, key: crypto.randomUUID() }
    busy.value = true
    error.value = ''
    try {
      const { data } = await api.post(`${base()}/${run.value.id}/commands`, { ...request, idempotency_key: pendingCommand.key })
      accept(data, captured)
      if (captured === generation) pendingCommand = null
    } catch (e: any) {
      if (captured !== generation) return
      error.value = e.response?.data?.detail?.code || e.message
      if (e.response?.status === 409) { pendingCommand = null; await reload() }
    } finally {
      if (captured === generation) busy.value = false
    }
  }
  return { run: readonly(run), error: readonly(error), busy: readonly(busy), elapsed: readonly(elapsed), tail: readonly(tail),
    canContinue: computed(() => ['READY', 'NEEDS_INPUT', 'ENVIRONMENT_BLOCKED'].includes(run.value?.state ?? '')),
    agentText: readonly(agentText), command, reload, onEvent }
}
