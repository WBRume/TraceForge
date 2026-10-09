import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: any[]) => any>(),
  startResource: vi.fn(), closeResource: vi.fn(), isRunning: vi.fn(),
  spawn: vi.fn(), fetch: vi.fn(), createServer: vi.fn(),
}))
vi.mock('../../../desktop/native', () => ({
  app: { getPath: () => '/state' },
  ipcMain: { handle: (name: string, handler: (...args: any[]) => any) => mocks.handlers.set(name, handler) },
  startLocalResourceService: mocks.startResource,
}))
vi.mock('cross-spawn', () => ({ default: mocks.spawn }))
vi.mock('node:fs', () => {
  const stub = { existsSync: () => true, closeSync: vi.fn(), openSync: vi.fn() }
  return { ...stub, default: stub }
})
vi.mock('node:fs/promises', () => { const stub = {
  mkdir: vi.fn(), writeFile: vi.fn(), rename: vi.fn(), realpath: vi.fn(),
  readFile: vi.fn(async () => JSON.stringify({
    port: 4098, agent_port: 4096, token: 'host-test', agent_token: 'agent-test', advertised_host: '10.0.0.2',
  })),
}; return { ...stub, default: stub } })
vi.mock('node:net', () => { const stub = {
  createServer: mocks.createServer,
}; return { ...stub, default: stub } })

let shutdown: () => Promise<void>
const resource = () => ({ close: mocks.closeResource, isRunning: mocks.isRunning })
const ensure = () => mocks.handlers.get('sdd:resources:ensure')!(null, { backend: 'opencode' })
const start = () => mocks.handlers.get('sdd:resources:start')!(null, { backend: 'opencode' })

describe('Embedded local resource lifecycle', () => {
  beforeEach(async () => {
    vi.resetModules()
    vi.clearAllMocks()
    mocks.closeResource.mockResolvedValue(undefined)
    mocks.isRunning.mockReturnValue(true)
    mocks.startResource.mockResolvedValue(resource())
    mocks.createServer.mockImplementation(() => ({
      listening: true, once: vi.fn(),
      listen: (_port: number, _host: string, ready: () => void) => ready(),
      close: (closed: () => void) => closed(),
    }))
    vi.stubGlobal('fetch', mocks.fetch)
    mocks.fetch.mockImplementation(async (url: string) => ({
      ok: true, json: async () => url.endsWith('/api/info')
        ? { version: '2.0.16', pid: 123, urls: ['http://10.0.0.2:4096'] }
        : { host_id: 'host', protocol_version: 1 },
    }))
    const module = await import('../localResources')
    shutdown = module.shutdownLocalServices
    module.registerLocalResourcesIpc()
  })
  afterEach(async () => { await shutdown() })

  it('embeds the resource service and reuses a running Agent without launching a process', async () => {
    expect((await start()).service_url).toBe('http://10.0.0.2:4096')
    expect(mocks.startResource).toHaveBeenCalledOnce()
    expect(mocks.startResource).toHaveBeenCalledWith(expect.objectContaining({
      token: 'host-test', port: 4098, roots_config_path: expect.stringContaining('host.json'),
    }))
    expect(mocks.fetch.mock.calls.some(([url]) => url.endsWith('/api/info'))).toBe(true)
    expect(mocks.spawn).not.toHaveBeenCalled()
  })

  it('shares concurrent startup requests for the same engine', async () => {
    const first = start()
    expect(start()).toBe(first)
    await first
    expect(mocks.startResource).toHaveBeenCalledOnce()
  })

  it('automatically pairs in-process without probing or starting an Agent', async () => {
    expect(await ensure()).toEqual({ resource_service_url: 'http://10.0.0.2:4098', host_token: 'host-test' })
    expect(mocks.startResource).toHaveBeenCalledOnce()
    expect(mocks.spawn).not.toHaveBeenCalled()
    expect(mocks.fetch).not.toHaveBeenCalled()
  })

  it('reuses only its owned service instance', async () => {
    await ensure()
    await ensure()
    expect(mocks.startResource).toHaveBeenCalledOnce()
    expect(mocks.fetch).not.toHaveBeenCalled()
  })

  it('restarts a stopped embedded service', async () => {
    await ensure()
    mocks.isRunning.mockReturnValueOnce(false)
    await ensure()
    expect(mocks.closeResource).toHaveBeenCalledOnce()
    expect(mocks.startResource).toHaveBeenCalledTimes(2)
  })

  it('can retry a failed embedded startup', async () => {
    mocks.startResource.mockRejectedValueOnce(new Error('worker initialization failed'))
    await expect(ensure()).rejects.toThrow('worker initialization failed')
    await expect(ensure()).resolves.toHaveProperty('host_token', 'host-test')
    expect(mocks.spawn).not.toHaveBeenCalled()
  })

  it('waits for automatic pairing before fulfilling a concurrent full startup request', async () => {
    let resolveResource!: (value: ReturnType<typeof resource>) => void
    mocks.startResource.mockImplementationOnce(() => new Promise(resolve => { resolveResource = resolve }))
    const pairing = ensure()
    const started = start()
    await vi.waitFor(() => expect(resolveResource).toBeDefined())
    expect(mocks.fetch).not.toHaveBeenCalled()
    resolveResource(resource())
    await pairing
    expect((await started).service_url).toBe('http://10.0.0.2:4096')
    expect(mocks.fetch.mock.calls.some(([url]) => url.endsWith('/api/info'))).toBe(true)
    expect(mocks.startResource).toHaveBeenCalledOnce()
    expect(mocks.spawn).not.toHaveBeenCalled()
  })

  it('reports an occupied incompatible Agent port', async () => {
    mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ healthy: true, version: '1.18.0' }) })
    mocks.createServer.mockImplementation(() => {
      let failure: (error: Error) => void
      return { listening: false, once: (_name: string, callback: typeof failure) => { failure = callback },
        listen: (port: number, _host: string, ready: () => void) => port === 4096 ? failure(new Error('EADDRINUSE')) : ready() }
    })
    await expect(start()).rejects.toThrow('端口 4096 已被占用')
    expect(mocks.spawn).not.toHaveBeenCalled()
    expect(mocks.startResource).not.toHaveBeenCalled()
  })

  it('does not adopt an external resource process even when its credentials match', async () => {
    mocks.createServer.mockImplementation(() => {
      let failure: (error: Error) => void
      return { listening: false, once: (_name: string, callback: typeof failure) => { failure = callback },
        listen: () => failure(new Error('EADDRINUSE')) }
    })
    await expect(ensure()).rejects.toThrow('端口 4098 已被占用')
    expect(mocks.fetch).not.toHaveBeenCalled()
    expect(mocks.startResource).not.toHaveBeenCalled()
  })

  it('closes the embedded service once and rejects new starts during shutdown', async () => {
    await ensure()
    await Promise.all([shutdown(), shutdown()])
    expect(mocks.closeResource).toHaveBeenCalledOnce()
    await expect(ensure()).rejects.toThrow('客户端正在退出')
  })

  it('cleans up a service whose initialization finishes during shutdown', async () => {
    let resolveResource!: (value: ReturnType<typeof resource>) => void
    mocks.startResource.mockImplementationOnce(() => new Promise(resolve => { resolveResource = resolve }))
    const pairing = expect(ensure()).rejects.toThrow('客户端正在退出')
    await vi.waitFor(() => expect(resolveResource).toBeDefined())
    const stopped = shutdown()
    resolveResource(resource())
    await pairing
    await stopped
    expect(mocks.closeResource).toHaveBeenCalledOnce()
    expect(mocks.spawn).not.toHaveBeenCalled()
  })
})
