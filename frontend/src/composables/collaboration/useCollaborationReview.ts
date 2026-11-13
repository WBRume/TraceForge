import { computed, onScopeDispose, shallowReactive, shallowReadonly, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { collaborationApi, decodeCollaborationText } from '@/services/collaborationApi'
import type { CollaborationReviewDiff, CollaborationReviewScope, CollaborationState } from '@/types/collaboration'
import { formatApiError } from '@/utils/error'

type Scope = CollaborationReviewScope
type Result = { diff: CollaborationReviewDiff | null; error: string }
type Request = { version: string; abort: AbortController; promise: Promise<void> }
type Version = Pick<CollaborationState, 'state_version' | 'session_generation' | 'session_revision'
  | 'sync_phase' | 'snapshot_id' | 'input_snapshot_id' | 'progress_snapshot_id'>

export function useCollaborationReview(options: {
  workspaceId: () => string
  taskId: () => string
  userId: () => string
  sessionVersion: () => readonly [number | undefined, number | undefined]
  state: () => CollaborationState | null
  participating: () => boolean
  receivedOnce: () => boolean
}) {
  const { t } = useI18n()
  const scopes = ['cumulative', 'round'] as const
  const results = shallowReactive<Record<Scope, Result>>({
    cumulative: { diff: null, error: '' },
    round: { diff: null, error: '' },
  })
  const requests: Partial<Record<Scope, Request>> = {}
  const retries: Partial<Record<Scope, ReturnType<typeof setTimeout>>> = {}
  const eventVersion = shallowRef<Version | null>(null)
  let opened = false
  let roundRequested = false

  const identity = computed(() => JSON.stringify([options.workspaceId(), options.taskId(), options.userId()]))
  const version = computed(() => {
    const state = options.state()
    const latest = eventVersion.value && eventVersion.value.state_version > (state?.state_version ?? 0) ? eventVersion.value : state
    return JSON.stringify([identity.value, ...options.sessionVersion(), options.participating(), options.receivedOnce(),
      state?.binding_id, latest?.session_generation, latest?.session_revision, latest?.sync_phase,
      latest?.snapshot_id, latest?.input_snapshot_id, latest?.progress_snapshot_id])
  })
  const remote = () => collaborationApi(options.workspaceId(), options.taskId())

  function cancel(scope: Scope) {
    clearTimeout(retries[scope])
    delete retries[scope]
    requests[scope]?.abort.abort()
    delete requests[scope]
  }

  function load(scope: Scope, force = false): Promise<void> {
    const current = version.value
    const pending = requests[scope]
    if (!opened || !options.workspaceId() || !options.taskId() || !options.userId()
      || (scope === 'round' && (!roundRequested || options.receivedOnce()))) {
      cancel(scope)
      return Promise.resolve()
    }
    if (!force && pending?.version === current) return pending.promise
    cancel(scope)
    const abort = new AbortController()
    const isCurrent = () => !abort.signal.aborted && current === version.value
    const promise = (async () => {
      try {
        const diff = await remote().reviewDiff(scope, abort.signal)
        if (!isCurrent()) return
        results[scope] = { diff, error: '' }
        // The completion event may arrive before the Agent releases its writer lock.
        if (diff.running) retries[scope] = setTimeout(() => { void load(scope) }, 1000)
      } catch (reason) {
        if (isCurrent()) results[scope] = { ...results[scope], error: formatApiError(reason, t('task_deliverables.review_failed')) }
      } finally {
        if (requests[scope]?.abort === abort) delete requests[scope]
      }
    })()
    requests[scope] = { version: current, abort, promise }
    return promise
  }

  function reload(force: boolean) {
    return Promise.all(scopes.map(scope => load(scope, force)))
  }

  function close() {
    opened = false
    roundRequested = false
    scopes.forEach(cancel)
  }

  watch(identity, () => {
    eventVersion.value = null
    for (const scope of scopes) {
      cancel(scope)
      results[scope] = { diff: null, error: '' }
    }
  }, { flush: 'sync' })
  watch(version, () => { if (opened) void reload(false) })
  onScopeDispose(close)

  return {
    results: shallowReadonly(results),
    open() { opened = true; void reload(false); return close },
    loadRound() { roundRequested = true; return load('round') },
    refresh: () => reload(true),
    onEvent(payload: Record<string, unknown>) {
      const version = Number(payload.state_version || 0)
      if (payload.task_id !== options.taskId() || !Number.isSafeInteger(version)
        || version <= Math.max(eventVersion.value?.state_version ?? 0, options.state()?.state_version ?? 0)) return
      eventVersion.value = { ...payload, state_version: version } as Version
    },
    readObject: (hash: string, signal?: AbortSignal) => remote().object(hash, signal),
    async readText(hash: string) {
      const data = new Uint8Array(await remote().object(hash))
      return decodeCollaborationText(data, t('collaboration.binary'))
    },
  }
}

export type CollaborationReview = ReturnType<typeof useCollaborationReview>
