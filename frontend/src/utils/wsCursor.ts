export interface WsCursor {
  epoch: string
  lastAppliedSequence: number
  recentEventIds: string[]
}

export type WsFrameResult =
  | { kind: 'control'; frame: any }
  | { kind: 'event'; event: any; commit: () => void }
  | { kind: 'ignore' }
  | { kind: 'resync'; reason: string; frame: any }

const CLIENT_ID_KEY = 'traceforge.ws.client_id'
const CURSORS_KEY = 'traceforge.ws.cursors'
const RECENT_EVENT_LIMIT = 128

const readJson = <T>(key: string, fallback: T): T => {
  try {
    const raw = window.sessionStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

const writeJson = (key: string, value: unknown) => {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value))
  } catch {
    // sessionStorage is an optional persistence layer. In-memory state remains
    // authoritative for the lifetime of this tab when it is unavailable.
  }
}

const cloneCursor = (cursor: WsCursor): WsCursor => ({
  epoch: cursor.epoch,
  lastAppliedSequence: cursor.lastAppliedSequence,
  recentEventIds: [...cursor.recentEventIds],
})

const cursorMemory = new Map<string, WsCursor>()
const pendingResync = new Map<string, WsCursor>()
let hydrated = false

const hydrateCursorMemory = () => {
  if (hydrated) return
  hydrated = true
  const stored = readJson<Record<string, WsCursor>>(CURSORS_KEY, {})
  for (const [room, value] of Object.entries(stored || {})) {
    if (!value?.epoch || !Number.isFinite(Number(value.lastAppliedSequence))) continue
    cursorMemory.set(room, {
      epoch: String(value.epoch),
      lastAppliedSequence: Math.max(0, Number(value.lastAppliedSequence)),
      recentEventIds: Array.isArray(value.recentEventIds)
        ? value.recentEventIds.map(String).slice(-RECENT_EVENT_LIMIT)
        : [],
    })
  }
}

const persistCursorMemory = () => {
  const cursors: Record<string, WsCursor> = {}
  for (const [room, cursor] of cursorMemory.entries()) cursors[room] = cloneCursor(cursor)
  writeJson(CURSORS_KEY, cursors)
}

export const getWsClientId = (): string => {
  try {
    const existing = window.sessionStorage.getItem(CLIENT_ID_KEY)
    if (existing) return existing
    const generated = typeof crypto?.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`
    window.sessionStorage.setItem(CLIENT_ID_KEY, generated)
    return generated
  } catch {
    return `ephemeral-${Date.now()}-${Math.random().toString(16).slice(2)}`
  }
}

export const getWsCursor = (room: string): WsCursor | null => {
  hydrateCursorMemory()
  const cursor = cursorMemory.get(room)
  if (!cursor || !cursor.epoch || !Number.isFinite(cursor.lastAppliedSequence)) return null
  return cloneCursor(cursor)
}

const commitCursor = (room: string, cursor: WsCursor, persist = true): WsCursor => {
  hydrateCursorMemory()
  const normalized = cloneCursor(cursor)
  const existing = cursorMemory.get(room)
  const staged = pendingResync.get(room)
  // An epoch transition is valid only while the matching resync barrier is
  // staged.  This prevents a late callback from an older connection
  // generation from replacing a cursor that has already been finalized for a
  // newer epoch.
  if (existing && existing.epoch !== normalized.epoch
    && staged?.epoch !== normalized.epoch) {
    return cloneCursor(existing)
  }
  // A late completion from an older handler must never move an applied cursor
  // backwards. Epoch changes are allowed only through an explicit resync.
  if (existing && existing.epoch === normalized.epoch
    && existing.lastAppliedSequence > normalized.lastAppliedSequence) {
    return cloneCursor(existing)
  }
  cursorMemory.set(room, normalized)
  if (persist) persistCursorMemory()
  return cloneCursor(normalized)
}

export const buildWsCursorQuery = (room: string): Record<string, string> => {
  const query: Record<string, string> = { client_id: getWsClientId() }
  const cursor = getWsCursor(room)
  if (cursor) {
    query.epoch = cursor.epoch
    query.last_sequence = String(cursor.lastAppliedSequence)
  }
  return query
}

/** Stage a resync barrier without persisting it before the server confirms. */
export const acknowledgeWsResync = (room: string, frame: any): WsCursor => {
  hydrateCursorMemory()
  const cursor: WsCursor = {
    epoch: String(frame?.epoch || ''),
    lastAppliedSequence: Math.max(0, Number(frame?.barrier_sequence ?? frame?.high_watermark ?? 0)),
    recentEventIds: [],
  }
  pendingResync.set(room, cursor)
  return cloneCursor(cursor)
}

export const finalizeWsResync = (room: string, frame: any): WsCursor | null => {
  hydrateCursorMemory()
  const staged = pendingResync.get(room)
  if (!staged) return null
  if (String(frame?.epoch || '') !== staged.epoch) return null
  const sequence = Number(frame?.high_watermark ?? frame?.to_sequence ?? staged.lastAppliedSequence)
  const finalized = {
    ...staged,
    lastAppliedSequence: Math.max(staged.lastAppliedSequence, Number.isFinite(sequence) ? sequence : 0),
  }
  const committed = commitCursor(room, finalized)
  pendingResync.delete(room)
  return committed
}

export const discardWsResync = (room: string) => {
  pendingResync.delete(room)
}

/** Test/support hook: clear module memory without changing the public protocol. */
export const clearWsCursorMemory = () => {
  cursorMemory.clear()
  pendingResync.clear()
  hydrated = false
}

export const prepareWsFrame = (room: string, frame: any): WsFrameResult => {
  if (!frame || typeof frame !== 'object') return { kind: 'ignore' }
  if (frame.type !== 'event') return { kind: 'control', frame }

  const epoch = String(frame.epoch || '')
  const sequence = Number(frame.sequence)
  const eventId = String(frame.event_id || '')
  if (!epoch || !Number.isFinite(sequence) || sequence < 1) {
    return { kind: 'resync', reason: 'gap', frame }
  }

  const stored = getWsCursor(room)
  const staged = pendingResync.get(room)
  const cursor = staged && staged.epoch === epoch
    ? cloneCursor(staged)
    : stored && stored.epoch === epoch
      ? stored
      : stored
  if (cursor && cursor.epoch !== epoch) {
    return { kind: 'resync', reason: 'epoch_changed', frame }
  }

  // Keep the legacy synthetic first-event rule for a server that predates the
  // barrier protocol. Current servers send resync_required before events.
  const previous: WsCursor = cursor || {
    epoch,
    lastAppliedSequence: sequence - 1,
    recentEventIds: [],
  }
  if (eventId && previous.recentEventIds.includes(eventId)) return { kind: 'ignore' }
  if (sequence <= previous.lastAppliedSequence) return { kind: 'ignore' }
  if (sequence !== previous.lastAppliedSequence + 1) {
    return { kind: 'resync', reason: 'gap', frame }
  }

  let committed = false
  return {
    kind: 'event',
    event: frame,
    commit: () => {
      if (committed) return
      committed = true
      const next: WsCursor = {
        epoch,
        lastAppliedSequence: sequence,
        recentEventIds: eventId
          ? [...previous.recentEventIds, eventId].slice(-RECENT_EVENT_LIMIT)
          : previous.recentEventIds,
      }
      if (pendingResync.has(room) && pendingResync.get(room)?.epoch === epoch) {
        pendingResync.set(room, cloneCursor(next))
      } else {
        commitCursor(room, next)
      }
    },
  }
}

export const sendResyncComplete = (
  socket: WebSocket,
  frame: any,
  room: string,
): void => {
  const cursor = acknowledgeWsResync(room, frame)
  socket.send(JSON.stringify({
    type: 'resync_complete',
    epoch: cursor.epoch,
    barrier_sequence: cursor.lastAppliedSequence,
  }))
}
