import { beforeEach, describe, expect, it } from 'vitest'
import {
  buildWsCursorQuery,
  clearWsCursorMemory,
  finalizeWsResync,
  getWsCursor,
  prepareWsFrame,
  sendResyncComplete,
} from '@/utils/wsCursor'

describe('ws cursor protocol', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    clearWsCursorMemory()
  })

  it('keeps a tab-scoped client id and commits only after event application', () => {
    const query = buildWsCursorQuery('task:one')
    expect(query.client_id).toBeTruthy()
    expect(query.epoch).toBeUndefined()

    const prepared = prepareWsFrame('task:one', {
      type: 'event',
      epoch: 'epoch-1',
      sequence: 4,
      event_id: 'event-4',
      event_type: 'status',
      payload: { step: 4 },
    })
    expect(prepared.kind).toBe('event')
    expect(getWsCursor('task:one')).toBeNull()
    if (prepared.kind === 'event') prepared.commit()
    expect(getWsCursor('task:one')).toMatchObject({
      epoch: 'epoch-1',
      lastAppliedSequence: 4,
    })
  })

  it('ignores duplicate ids and detects a sequence gap', () => {
    const first = prepareWsFrame('task:one', {
      type: 'event', epoch: 'epoch-1', sequence: 1, event_id: 'event-1',
      event_type: 'status', payload: {},
    })
    if (first.kind === 'event') first.commit()

    expect(prepareWsFrame('task:one', {
      type: 'event', epoch: 'epoch-1', sequence: 1, event_id: 'event-1',
      event_type: 'status', payload: {},
    }).kind).toBe('ignore')
    expect(prepareWsFrame('task:one', {
      type: 'event', epoch: 'epoch-1', sequence: 3, event_id: 'event-3',
      event_type: 'status', payload: {},
    })).toMatchObject({ kind: 'resync', reason: 'gap' })
  })

  it('stages the barrier and persists it only after resync_ok', () => {
    const sent: string[] = []
    const socket = { send: (value: string) => sent.push(value) } as unknown as WebSocket
    sendResyncComplete(socket, {
      type: 'resync_required', epoch: 'epoch-2', barrier_sequence: 9,
    }, 'task:one')
    expect(JSON.parse(sent[0])).toEqual({
      type: 'resync_complete',
      epoch: 'epoch-2',
      barrier_sequence: 9,
    })
    expect(getWsCursor('task:one')).toBeNull()
    expect(finalizeWsResync('task:one', {
      type: 'resync_ok', epoch: 'epoch-2', to_sequence: 9,
    })).toMatchObject({ epoch: 'epoch-2', lastAppliedSequence: 9 })
    expect(getWsCursor('task:one')).toMatchObject({
      epoch: 'epoch-2', lastAppliedSequence: 9,
    })
  })

  it('uses the staged cursor before the stored cursor for the same epoch', () => {
    const stored = prepareWsFrame('task:one', {
      type: 'event', epoch: 'epoch-3', sequence: 10, event_id: 'event-10',
    })
    if (stored.kind === 'event') stored.commit()

    const sent: string[] = []
    const socket = { send: (value: string) => sent.push(value) } as unknown as WebSocket
    sendResyncComplete(socket, {
      type: 'resync_required', epoch: 'epoch-3', barrier_sequence: 100,
    }, 'task:one')

    const deferred = prepareWsFrame('task:one', {
      type: 'event', epoch: 'epoch-3', sequence: 101, event_id: 'event-101',
    })
    expect(deferred.kind).toBe('event')
    if (deferred.kind === 'event') deferred.commit()
    expect(getWsCursor('task:one')?.lastAppliedSequence).toBe(10)
    expect(finalizeWsResync('task:one', {
      type: 'resync_ok', epoch: 'epoch-3', to_sequence: 101,
    })?.lastAppliedSequence).toBe(101)
    expect(sent).toHaveLength(1)
  })

  it('ignores resync_ok from a different epoch', () => {
    sendResyncComplete({ send: () => undefined } as unknown as WebSocket, {
      type: 'resync_required', epoch: 'epoch-4', barrier_sequence: 100,
    }, 'task:one')

    expect(finalizeWsResync('task:one', {
      type: 'resync_ok', epoch: 'other-epoch', to_sequence: 200,
    })).toBeNull()
    expect(getWsCursor('task:one')).toBeNull()
  })

  it('does not let a late commit move the cursor backwards after resync', () => {
    const oldEvent = prepareWsFrame('task:one', {
      type: 'event', epoch: 'epoch-5', sequence: 11, event_id: 'event-11',
    })
    sendResyncComplete({ send: () => undefined } as unknown as WebSocket, {
      type: 'resync_required', epoch: 'epoch-5', barrier_sequence: 100,
    }, 'task:one')
    finalizeWsResync('task:one', {
      type: 'resync_ok', epoch: 'epoch-5', to_sequence: 100,
    })

    if (oldEvent.kind === 'event') oldEvent.commit()
    expect(getWsCursor('task:one')?.lastAppliedSequence).toBe(100)
  })
})
