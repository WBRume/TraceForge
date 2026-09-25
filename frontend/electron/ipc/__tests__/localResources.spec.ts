import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: any[]) => any>(),
  fork: vi.fn(), spawn: vi.fn(), fetch: vi.fn(),
}))
vi.mock('electron', () => ({
  app: { getPath: () => '/state', getAppPath: () => '/app' },
  ipcMain: { handle: (name: string, handler: (...args: any[]) => any) => mocks.handlers.set(name, handler) },
  utilityProcess: { fork: mocks.fork },
}))
vi.mock('cross-spawn', () => ({ default: mocks.spawn }))
vi.mock('node:fs', () => {
  const stub = { existsSync: () => true, closeSync: vi.fn(), openSync: vi.fn(), createWriteStream: vi.fn() }
  return { ...stub, default: stub }
})
vi.mock('node:fs/promises', () => { const stub = {
  mkdir: vi.fn(), writeFile: vi.fn(), rename: vi.fn(), realpath: vi.fn(),
  readFile: vi.fn(async () => JSON.stringify({
    port: 4098, agent_port: 4096, token: 'host-test', agent_token: 'agent-test', advertised_host: '10.0.0.2',
  })),
}; return { ...stub, default: stub } })
vi.mock('node:net', () => { const stub = {
  createServer: () => {
    let failure: (error: Error) => void
    return { listening: false, once: (_name: string, callback: typeof failure) => { failure = callback },
      listen: () => { failure(new Error('EADDRINUSE')) } }
  },
}; return { ...stub, default: stub } })

import { registerLocalResourcesIpc } from '../localResources'

describe('Electron service startup', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('fetch', mocks.fetch)
    mocks.fetch.mockImplementation(async (url: string) => ({
      ok: true, json: async () => url.endsWith('/api/info')
        ? { version: '2.0.16', pid: 123, urls: ['http://10.0.0.2:4096'] }
        : { host_id: 'host', protocol_version: 1 },
    }))
    registerLocalResourcesIpc()
  })

  it('reuses the running v2 service without launching another process or requiring roots', async () => {
    const result = await mocks.handlers.get('sdd:resources:start')!(null, { backend: 'opencode' })
    expect(result.service_url).toBe('http://10.0.0.2:4096')
    expect(mocks.fetch.mock.calls.some(([url]) => url.endsWith('/api/info'))).toBe(true)
    expect(mocks.fetch.mock.calls.some(([url]) => url.includes('/global/health'))).toBe(false)
    expect(mocks.spawn).not.toHaveBeenCalled()
    expect(mocks.fork).not.toHaveBeenCalled()
  })

  it('shares concurrent startup requests for the same engine', async () => {
    const start = mocks.handlers.get('sdd:resources:start')!
    const first = start(null, { backend: 'opencode' })
    expect(start(null, { backend: 'opencode' })).toBe(first)
    await first
  })

  it('reports an occupied incompatible port without launching a duplicate process', async () => {
    mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ healthy: true, version: '1.18.0' }) })
    await expect(mocks.handlers.get('sdd:resources:start')!(null, { backend: 'opencode' })).rejects.toThrow('端口 4096 已被占用')
    expect(mocks.spawn).not.toHaveBeenCalled()
    expect(mocks.fork).not.toHaveBeenCalled()
  })
})
