import { discardWsResync, finalizeWsResync, prepareWsFrame, type WsFrameResult } from '@/utils/wsCursor'

type MaybePromise<T> = T | Promise<T>

export interface SerializedWsContext {
  generation: number
  socket: WebSocket
}

export interface SerializedWsConsumerOptions {
  room: string
  onEvent: (event: any, context: SerializedWsContext, signal: AbortSignal) => MaybePromise<void>
  onResync: (frame: any, reason: string, context: SerializedWsContext, signal: AbortSignal) => MaybePromise<void>
  onControl?: (frame: any, context: SerializedWsContext, signal: AbortSignal) => MaybePromise<void>
  onFailure: (error: unknown, context: SerializedWsContext) => void
  maxEvents?: number
  maxBytes?: number
}

type QueueItem = { frame: any; generation: number; bytes: number }

const frameBytes = (frame: any): number => {
  try {
    return new TextEncoder().encode(JSON.stringify(frame)).byteLength
  } catch {
    return 256
  }
}

/** One ordered consumer shared by every reliable WebSocket room. */
export const createSerializedWsConsumer = (options: SerializedWsConsumerOptions) => {
  const maxEvents = Math.max(1, options.maxEvents ?? 256)
  const maxBytes = Math.max(1024, options.maxBytes ?? 2 * 1024 * 1024)
  const queue: QueueItem[] = []
  let queuedBytes = 0
  let running = false
  let generation = 0
  let context: SerializedWsContext | null = null
  let abortController = new AbortController()
  let resyncFlight: Promise<void> | null = null
  let failed = false

  const isCurrent = (itemGeneration: number) => (
    !failed && context !== null && context.generation === itemGeneration && generation === itemGeneration
  )

  const fail = (error: unknown, itemGeneration: number) => {
    if (failed || !context || context.generation !== itemGeneration) return
    failed = true
    abortController.abort()
    queue.length = 0
    queuedBytes = 0
    options.onFailure(error, context)
  }

  const drain = async () => {
    if (running) return
    running = true
    try {
      while (queue.length > 0) {
        const item = queue.shift()!
        queuedBytes = Math.max(0, queuedBytes - item.bytes)
        if (!isCurrent(item.generation)) continue
        const currentContext = context!
        try {
          const prepared: WsFrameResult = prepareWsFrame(options.room, item.frame)
          if (prepared.kind === 'ignore') continue
          if (prepared.kind === 'event') {
            await options.onEvent(prepared.event, currentContext, abortController.signal)
            if (isCurrent(item.generation) && !abortController.signal.aborted) prepared.commit()
            continue
          }
          if (prepared.kind === 'resync') {
            if (!resyncFlight) {
              const flight = Promise.resolve(
                options.onResync(prepared.frame, prepared.reason, currentContext, abortController.signal),
              ).finally(() => {
                if (resyncFlight === flight) resyncFlight = null
              })
              resyncFlight = flight
            }
            await resyncFlight
            continue
          }
          if (prepared.frame?.type === 'resync_required') {
            if (!resyncFlight) {
              const flight = Promise.resolve(
                options.onResync(prepared.frame, String(prepared.frame.reason || 'server_resync'), currentContext, abortController.signal),
              ).finally(() => {
                if (resyncFlight === flight) resyncFlight = null
              })
              resyncFlight = flight
            }
            await resyncFlight
            continue
          }
          if (prepared.frame?.type === 'resync_ok') finalizeWsResync(options.room, prepared.frame)
          await options.onControl?.(prepared.frame, currentContext, abortController.signal)
        } catch (error) {
          fail(error, item.generation)
          return
        }
      }
    } finally {
      running = false
      if (queue.length > 0 && !failed) void drain()
    }
  }

  return {
    resetForConnection(socket: WebSocket): number {
      abortController.abort()
      abortController = new AbortController()
      queue.length = 0
      queuedBytes = 0
      resyncFlight = null
      failed = false
      generation += 1
      context = { generation, socket }
      discardWsResync(options.room)
      return generation
    },
    enqueue(frame: any, itemGeneration: number) {
      if (!isCurrent(itemGeneration)) return
      const bytes = frameBytes(frame)
      if (queue.length >= maxEvents || queuedBytes + bytes > maxBytes) {
        fail(new Error('WebSocket inbound queue overflow'), itemGeneration)
        return
      }
      queue.push({ frame, generation: itemGeneration, bytes })
      queuedBytes += bytes
      void drain()
    },
    close(itemGeneration?: number) {
      if (itemGeneration !== undefined && (!context || context.generation !== itemGeneration)) return
      failed = true
      abortController.abort()
      queue.length = 0
      queuedBytes = 0
      resyncFlight = null
      discardWsResync(options.room)
    },
  }
}
