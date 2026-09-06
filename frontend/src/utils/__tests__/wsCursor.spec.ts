import { beforeEach, describe, expect, it } from 'vitest'
import {
  buildWsCursorQuery,
  getWsCursor,
  prepareWsFrame,
  sendResyncComplete,
} from '@/utils/wsCursor'

describe('ws cursor protocol', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
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

  it('sends resync completion after recording the server barrier', () => {
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
  })
})
