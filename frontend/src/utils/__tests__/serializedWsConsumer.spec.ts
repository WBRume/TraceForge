import { beforeEach, describe, expect, it } from 'vitest'
import { clearWsCursorMemory, getWsCursor } from '@/utils/wsCursor'
import { createSerializedWsConsumer } from '@/utils/serializedWsConsumer'

const socket = () => ({
  readyState: WebSocket.OPEN,
  send: () => undefined,
  close: () => undefined,
}) as unknown as WebSocket

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

describe('serialized WebSocket consumer', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    clearWsCursorMemory()
  })

  it('applies asynchronous events strictly in arrival order before committing', async () => {
    const order: string[] = []
    let releaseFirst!: () => void
    const firstDone = new Promise<void>((resolve) => { releaseFirst = resolve })
    const consumer = createSerializedWsConsumer({
      room: 'task:serial',
      onEvent: async (event) => {
        order.push(`start-${event.sequence}`)
        if (event.sequence === 1) await firstDone
        order.push(`end-${event.sequence}`)
      },
      onResync: async () => undefined,
      onFailure: () => undefined,
    })
    const generation = consumer.resetForConnection(socket())
    consumer.enqueue({ type: 'event', epoch: 'e1', sequence: 1, event_id: 'a', event_type: 'status', payload: {} }, generation)
    consumer.enqueue({ type: 'event', epoch: 'e1', sequence: 2, event_id: 'b', event_type: 'status', payload: {} }, generation)
    await tick()
    expect(order).toEqual(['start-1'])
    releaseFirst()
    await tick()
    await tick()
    expect(order).toEqual(['start-1', 'end-1', 'start-2', 'end-2'])
    expect(getWsCursor('task:serial')?.lastAppliedSequence).toBe(2)
  })

  it('drops a stale generation completion and bounds the queue', async () => {
    let releaseOld!: () => void
    const oldDone = new Promise<void>((resolve) => { releaseOld = resolve })
    let failures = 0
    const consumer = createSerializedWsConsumer({
      room: 'task:generation',
      maxEvents: 1,
      onEvent: async () => oldDone,
      onResync: async () => undefined,
      onFailure: () => { failures += 1 },
    })
    const firstGeneration = consumer.resetForConnection(socket())
    consumer.enqueue({ type: 'event', epoch: 'e1', sequence: 1, event_id: 'old', event_type: 'status', payload: {} }, firstGeneration)
    await tick()
    const currentGeneration = consumer.resetForConnection(socket())
    releaseOld()
    consumer.enqueue({ type: 'event', epoch: 'e1', sequence: 1, event_id: 'new', event_type: 'status', payload: {} }, currentGeneration)
    await tick()
    await tick()
    expect(failures).toBe(0)
    expect(getWsCursor('task:generation')?.lastAppliedSequence).toBe(1)
  })
})
