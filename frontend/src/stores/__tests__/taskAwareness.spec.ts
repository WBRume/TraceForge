import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTaskAwarenessStore } from '../taskAwareness'
import { usePinnedFloatsStore } from '../pinnedFloats'
import { useAuthStore } from '../auth'
import type { TaskRuntimeEvent } from '@/types/taskAwareness'
import api from '@/utils/api'

vi.mock('@/router', () => ({ default: { push: vi.fn() } }))
vi.mock('@/utils/api', () => ({ default: { get: vi.fn().mockResolvedValue({ data: { runs: [] } }) } }))
const baseTime = Date.parse('2026-10-03T00:00:00Z')
const event = (state: TaskRuntimeEvent['event_type'] = 'AI_RUNNING', version = 1, changes: Partial<TaskRuntimeEvent> = {}): TaskRuntimeEvent => ({
  event_type: state, event_id: `e${version}`, workspace: { id: 'w1', name: '工作区' }, task: { id: 't1', title: 'Task A', url: 'https://tf/workspaces/w1/chat/t1' },
  initiator: { id: 'u1', name: '本人' }, summary: '', run: { id: 'j1', version, started_at: new Date(baseTime).toISOString(), client_message_id: 'c1',
    finished_at: ['AI_RUN_FINISHED', 'AI_RUN_ERROR', 'AI_RUN_INTERRUPTED'].includes(state) ? new Date(Date.now()).toISOString() : null }, ...changes,
})
let store: ReturnType<typeof useTaskAwarenessStore>
let floats: ReturnType<typeof usePinnedFloatsStore>
let native: ReturnType<typeof vi.fn>
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(baseTime); localStorage.clear(); sessionStorage.clear(); setActivePinia(createPinia())
  const auth = useAuthStore(); auth.token = 'test'; auth.user = { id: 'u1', email: 'u1@test', display_name: '本人' }
  native = vi.fn().mockResolvedValue({ ok: true }); window.sddDesktop = { attention: { set: native } } as any
  store = useTaskAwarenessStore(); floats = usePinnedFloatsStore(); store.reset('u1'); store.view('t1', true)
  vi.mocked(api.get).mockResolvedValue({ data: { runs: [] } })
})
afterEach(() => { store.stop(); vi.useRealTimers(); delete window.sddDesktop })

describe('explicit long-run awareness', () => {
  it('browsing or historical state never seeds qualification', () => {
    store.ingest(event()); store.view('', true); vi.advanceTimersByTime(60_000); store.ingest(event('AI_RUN_ERROR', 2))
    expect(floats.items).toHaveLength(0); expect(store.runs).toEqual({}); expect(native.mock.calls.some(([x]) => x.flash)).toBe(false)
  })
  it('waits for the 10-second boundary after leaving, then auto-cleans 8 seconds after finish', () => {
    store.arm('t1', 'c1'); store.ingest(event()); store.view('', true)
    vi.advanceTimersByTime(9999); expect(floats.items).toHaveLength(0)
    vi.advanceTimersByTime(1); expect(floats.items[0]).toMatchObject({ source: 'automatic', minimized: true, runtimeState: 'AI_RUNNING' })
    store.ingest(event('AI_RUN_FINISHED', 2)); expect(floats.items[0].runtimeState).toBe('AI_RUN_FINISHED')
    vi.advanceTimersByTime(7999); expect(floats.items).toHaveLength(1)
    vi.advanceTimersByTime(1); expect(floats.items).toHaveLength(0)
  })
  it('suppresses short execution in all personal UI channels', () => {
    store.arm('t1', 'c1'); store.ingest(event()); store.view('', false); vi.advanceTimersByTime(5000); store.ingest(event('AI_RUN_FINISHED', 2))
    vi.advanceTimersByTime(20_000); expect(floats.items).toHaveLength(0); expect(native.mock.calls.some(([x]) => x.flash)).toBe(false)
  })
  it('keeps the task foreground free of pills and consumes a foreground finish', () => {
    store.arm('t1', 'c1'); store.ingest(event()); vi.advanceTimersByTime(20_000); expect(floats.items).toHaveLength(0)
    store.ingest(event('AI_RUN_FINISHED', 2)); store.view('', true); expect(floats.items).toHaveLength(0)
  })
  it('returning to the full task removes a probe; running can dock on a later leave', () => {
    store.arm('t1', 'c1'); store.ingest(event()); vi.advanceTimersByTime(10_000); store.view('', true)
    expect(floats.items).toHaveLength(1); store.view('t1', true); expect(floats.items).toHaveLength(0)
    store.view('', true); expect(floats.items).toHaveLength(1)
  })
  it('manual pin promotes a probe and survives completion and time', () => {
    store.arm('t1', 'c1'); store.ingest(event()); store.view('', true); vi.advanceTimersByTime(10_000)
    floats.pinTask({ id: 't1', name: 'Task A', workspaceId: 'w1', workspaceName: '工作区' })
    store.ingest(event('AI_RUN_FINISHED', 2)); vi.advanceTimersByTime(60_000)
    expect(floats.items).toHaveLength(1); expect(floats.items[0]).toMatchObject({ source: 'manual', minimized: false })
  })
  it('human interruption removes a temporary probe and clears HITL without a new native alert', () => {
    store.arm('t1', 'c1'); store.ingest(event()); store.view('', false); vi.advanceTimersByTime(10_000)
    store.ingest(event('AI_HITL_SUSPENDED', 2))
    expect(floats.items).toHaveLength(1); expect(native).toHaveBeenLastCalledWith({ flash: true, hitlCount: 1 })
    native.mockClear()
    store.ingest(event('AI_RUN_INTERRUPTED', 3))
    expect(floats.items).toHaveLength(0); expect(native).toHaveBeenLastCalledWith({ flash: true, hitlCount: 0 })
    store.view('', true); store.view('', false)
    expect(native).toHaveBeenLastCalledWith({ flash: false, hitlCount: 0 })
    vi.advanceTimersByTime(60_000); expect(floats.items).toHaveLength(0)
  })
  it('manual reference panels remain after interruption and a later run can execute normally', () => {
    store.arm('t1', 'c1'); store.ingest(event()); store.view('', true); vi.advanceTimersByTime(10_000)
    floats.pinTask({ id: 't1', name: 'Task A', workspaceId: 'w1', workspaceName: '工作区' })
    store.ingest(event('AI_RUN_INTERRUPTED', 2)); vi.advanceTimersByTime(60_000)
    expect(floats.items).toHaveLength(1); expect(floats.items[0]).toMatchObject({ source: 'manual', runtimeState: 'AI_RUN_INTERRUPTED' })
    store.arm('t1', 'c2'); store.ingest(event('AI_RUNNING', 1, { run: { ...event().run, id: 'j2', client_message_id: 'c2' } }))
    expect(floats.items[0]).toMatchObject({ source: 'manual', runId: 'j2', runtimeState: 'AI_RUNNING' })
  })
  it('close suppresses later events for the same run and never changes its runtime', () => {
    store.arm('t1', 'c1'); store.ingest(event()); store.view('', false); vi.advanceTimersByTime(10_000)
    store.dismiss('j1'); floats.unpin('task:t1'); store.ingest(event('AI_RUN_ERROR', 2))
    expect(floats.items).toHaveLength(0); expect(store.runs.j1.event.event_type).toBe('AI_RUN_ERROR')
  })
  it('ignores another member, another device request, and stale/replayed versions', () => {
    store.arm('t1', 'c1'); store.ingest(event('AI_RUNNING', 1, { initiator: { id: 'other', name: '' } })); expect(store.runs).toEqual({})
    store.ingest(event()); store.view('', true); vi.advanceTimersByTime(10_000); store.ingest(event('AI_RUN_FINISHED', 2)); store.ingest(event())
    const until = store.runs.j1.expiresAt; store.ingest(event('AI_RUN_FINISHED', 2)); expect(store.runs.j1.expiresAt).toBe(until)
    store.ingest(event('AI_RUNNING', 1, { run: { ...event().run, id: 'j2', client_message_id: 'other-request' } }))
    expect(store.runs.j2).toBeUndefined()
  })
  it('a bound creation intent cannot attach a later uninitiated run', () => {
    store.arm('t1'); store.ingest(event()); store.ingest(event('AI_RUNNING', 1, { run: { ...event().run, id: 'j2' } }))
    expect(store.runs.j2).toBeUndefined()
  })
  it('native HITL notifications clear on focus and keep the remaining unresolved badge', () => {
    store.arm('t1', 'c1'); store.arm('t2', 'c2'); store.ingest(event()); store.view('', false); vi.advanceTimersByTime(10_000)
    store.ingest(event('AI_HITL_SUSPENDED', 2))
    store.ingest(event('AI_HITL_SUSPENDED', 1, { task: { id: 't2', title: 'Task B', url: '' }, run: { ...event().run, id: 'j2', client_message_id: 'c2' } }))
    expect(native).toHaveBeenLastCalledWith({ flash: true, hitlCount: 2 })
    store.ingest(event('AI_RUNNING', 3)); expect(native).toHaveBeenLastCalledWith({ flash: true, hitlCount: 1 })
    store.view('', true); expect(native).toHaveBeenLastCalledWith({ flash: false, hitlCount: 0 })
  })
  it('account change destroys temporary probes and execution intent', () => {
    store.arm('t1', 'c1'); store.ingest(event()); store.view('', true); vi.advanceTimersByTime(10_000); store.reset('u2')
    expect(floats.items).toHaveLength(0); expect(store.runs).toEqual({}); store.ingest(event()); expect(store.runs).toEqual({})
  })
  it('a prior run expiry cannot remove the next run on the same task', () => {
    store.arm('t1', 'c1'); store.ingest(event()); store.view('', true); vi.advanceTimersByTime(10_000)
    store.ingest(event('AI_RUN_FINISHED', 2)); store.arm('t1', 'c2')
    // The next run has already passed the boundary when its delayed event arrives.
    store.ingest(event('AI_RUNNING', 1, { run: { ...event().run, id: 'j2', client_message_id: 'c2' } }))
    vi.advanceTimersByTime(8_000)
    expect(floats.items).toHaveLength(1); expect(floats.items[0].runId).toBe('j2')
  })
  it('reconnect consumes a disappeared or revoked run without creating history probes', async () => {
    store.arm('t1', 'c1'); store.ingest(event()); store.view('', true); vi.advanceTimersByTime(10_000)
    await store.refresh()
    expect(floats.items).toHaveLength(0); expect(store.runs.j1).toBeUndefined()
    store.ingest(event()); expect(store.runs.j1).toBeUndefined()
  })
  it('manual pins restore only for their own account', () => {
    floats.pinTask({ id: 't1', name: 'Task A', workspaceId: 'w1', workspaceName: '工作区' })
    store.reset('u2'); expect(floats.items).toHaveLength(0)
    store.reset('u1'); expect(floats.items).toHaveLength(1); expect(floats.items[0].source).toBe('manual')
  })
  it('consuming a finished probe keeps its expanded panel available for reading', () => {
    store.arm('t1', 'c1'); store.ingest(event()); store.view('', true); vi.advanceTimersByTime(10_000)
    store.ingest(event('AI_RUN_FINISHED', 2)); floats.setMinimized('task:t1', false); store.consume('j1')
    vi.advanceTimersByTime(20_000); expect(floats.items).toHaveLength(1); expect(floats.items[0].minimized).toBe(false)
  })
  it('a terminal result seen in the main task socket cannot reappear after leaving', () => {
    store.arm('t1', 'c1'); store.ingest(event()); vi.advanceTimersByTime(10_000)
    store.observeForegroundTerminal({ id: 'j1', task_id: 't1', creator_id: 'u1', status: 'SUCCESS' })
    store.view('', false); store.ingest(event('AI_RUN_FINISHED', 2))
    expect(floats.items).toHaveLength(0); expect(native.mock.calls.some(([x]) => x.flash)).toBe(false)
  })
  it('recovers a queued receipt by its explicit client request when the initial running frame was missed', async () => {
    store.arm('t1', 'c1'); store.view('', true)
    vi.mocked(api.get).mockResolvedValue({ data: { runs: [event()] } })
    await store.refresh()
    expect(api.get).toHaveBeenCalledWith('/task-awareness/runs', expect.objectContaining({ params: { job_ids: '', client_message_ids: 'c1' } }))
    vi.advanceTimersByTime(10_000); expect(floats.items).toHaveLength(1)
  })
})
