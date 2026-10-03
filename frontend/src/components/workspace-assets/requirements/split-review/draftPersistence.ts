import type { RequirementSplitDraft } from '@/types/workspaceAssets'

export type DraftStatus = 'idle' | 'saving' | 'saved' | 'error'
type DraftOptions = {
  snapshot: () => RequirementSplitDraft
  save: (draft: RequirementSplitDraft) => Promise<boolean>
  status: (status: DraftStatus) => void
}

/** Owns the draft lifecycle: one PUT at a time; closing drains all in-flight writes. */
export function createDraftPersistence(options: DraftOptions) {
  let phase: 'paused' | 'editing' | 'closing' | 'closed' = 'paused'
  let revision = 0
  let savedRevision = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let inFlight: Promise<boolean> | null = null

  function clearTimer() {
    if (timer) clearTimeout(timer)
    timer = undefined
  }

  async function drain(): Promise<boolean> {
    let ok = true
    while (savedRevision < revision && (phase === 'editing' || phase === 'closing')) {
      const savingRevision = revision
      const draft = options.snapshot()
      options.status('saving')
      try { ok = await options.save(draft) } catch { ok = false }
      if (!ok) { options.status('error'); return false }
      savedRevision = savingRevision
      options.status('saved')
    }
    return ok
  }

  function flush(): Promise<boolean> {
    clearTimer()
    if (phase === 'closed' || phase === 'paused') return Promise.resolve(true)
    if (!inFlight) {
      inFlight = drain().finally(() => { inFlight = null })
    }
    return inFlight
  }

  return {
    open() { if (phase !== 'closing') phase = 'editing' },
    schedule() {
      if (phase !== 'editing') return
      revision += 1
      clearTimer()
      timer = setTimeout(() => { timer = undefined; void flush() }, 800)
    },
    flush,
    async close() {
      if (phase === 'closed') return
      phase = 'closing'
      clearTimer()
      // DELETE/confirm consumes the draft; wait for writes already sent, omit unsent edits.
      if (inFlight) await inFlight
      phase = 'closed'
    },
    canSaveOnExit() { return phase === 'editing' && savedRevision < revision && !inFlight },
    dispose() { clearTimer(); phase = 'closed' },
  }
}
