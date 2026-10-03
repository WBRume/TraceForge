import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import api from '@/utils/api'
import { flushDesktopWebhooks } from '../desktopWebhooks'
const mocks = vi.hoisted(() => ({ user: { id: 'u1' } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: mocks.user }) }))
vi.mock('@/utils/api', () => ({ default: { post: vi.fn(), defaults: { baseURL: 'https://server/api' } } }))
const delivery = (id: number) => ({ id: `d${id}`, lease_token: `t${id}`, event_id: `e${id}`, url: 'http://127.0.0.1:9000/pet', body: {} })
beforeEach(() => { vi.mocked(api.post).mockResolvedValue({ data: { items: [] } }) })
afterEach(() => { delete window.sddDesktop })
describe('desktop webhook draining', () => {
  it('drains more than 100 queued deliveries with bounded native concurrency', async () => {
    const queue = Array.from({ length: 101 }, (_, id) => delivery(id))
    let active = 0, peak = 0
    const send = vi.fn(async () => { active++; peak = Math.max(active, peak); await Promise.resolve(); active--; return { ok: true } })
    window.sddDesktop = { webhooks: { send } } as any
    vi.mocked(api.post).mockImplementation(async url => ({ data: { items: String(url).endsWith('/claim') ? queue.splice(0, 10) : [] } }))
    await flushDesktopWebhooks()
    expect(send).toHaveBeenCalledTimes(101); expect(queue).toHaveLength(0); expect(peak).toBe(3)
  })
  it('merges nudges received during an in-flight drain and reports a native failure without throwing', async () => {
    let release!: () => void
    const send = vi.fn(() => new Promise<{ ok: boolean; error: string }>(resolve => { release = () => resolve({ ok: false, error: 'NetworkError' }) }))
    window.sddDesktop = { webhooks: { send } } as any
    vi.mocked(api.post).mockResolvedValueOnce({ data: { items: [delivery(1)] } }).mockResolvedValue({ data: { items: [] } })
    const first = flushDesktopWebhooks(); await Promise.resolve(); const second = flushDesktopWebhooks()
    expect(second).toBe(first); release(); await first; await flushDesktopWebhooks()
    expect(api.post).toHaveBeenCalledWith('/task-awareness/desktop-deliveries/ack', expect.objectContaining({ ok: false, error: 'NetworkError' }), { timeout: 3000 })
  })
})
