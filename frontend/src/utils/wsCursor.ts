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
    // A private browsing context can reject sessionStorage. The connection
    // still works; it simply falls back to REST resync on the next reconnect.
  }
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

const allCursors = (): Record<string, WsCursor> => readJson(CURSORS_KEY, {})

export const getWsCursor = (room: string): WsCursor | null => {
  const cursor = allCursors()[room]
  if (!cursor || !cursor.epoch || !Number.isFinite(cursor.lastAppliedSequence)) return null
  return cursor
}

const saveCursor = (room: string, cursor: WsCursor) => {
  const cursors = allCursors()
  cursors[room] = cursor
  writeJson(CURSORS_KEY, cursors)
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

export const acknowledgeWsResync = (room: string, frame: any): WsCursor => {
  const cursor: WsCursor = {
    epoch: String(frame?.epoch || ''),
    lastAppliedSequence: Number(frame?.barrier_sequence || 0),
    recentEventIds: [],
  }
  saveCursor(room, cursor)
  return cursor
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

  const cursor = getWsCursor(room)
  if (cursor && cursor.epoch !== epoch) {
    return { kind: 'resync', reason: 'epoch_changed', frame }
  }

  // A first connection has already loaded REST state. Establish the cursor
  // immediately before this event so a journal high-watermark is accepted.
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
      saveCursor(room, next)
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
