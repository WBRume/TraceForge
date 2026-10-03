import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { transferableAbortController } from 'node:util'

describe('desktop HTTP transport', () => {
  beforeEach(() => {
    vi.resetModules()
    // Vitest supplies Node's Request but jsdom's AbortController; keep their brands consistent.
    vi.stubGlobal('AbortController', transferableAbortController().constructor)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('uses browser fetch before a native transport is configured', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('web'))
    vi.stubGlobal('fetch', fetch)
    const { backendFetch } = await import('../http')
    await backendFetch('https://server.example/api/draft', { method: 'PUT', keepalive: true })
    expect(fetch).toHaveBeenCalledWith('https://server.example/api/draft', { method: 'PUT', keepalive: true })
  })

  it('applies native HTTP to new Axios clients and preserves auth, query and JSON bodies', async () => {
    const { configureNativeHttp, backendFetch } = await import('../http')
    const { default: axios } = await import('axios')
    const fetch = vi.fn().mockImplementation(async () => new Response('{"ok":true}', {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }))
    configureNativeHttp(fetch)
    const client = axios.create({ baseURL: 'https://server.example/api', timeout: 1000 })
    client.interceptors.request.use(config => {
      config.headers.Authorization = 'Bearer test-token'
      return config
    })
    const response = await client.post('/draft', { value: '中文' }, { params: { revision: 2 } })
    expect(response.data).toEqual({ ok: true })
    const request = fetch.mock.calls[0]![0] as Request
    expect(request.url).toBe('https://server.example/api/draft?revision=2')
    expect(request.headers.get('Authorization')).toBe('Bearer test-token')
    expect(request.method).toBe('POST')
    expect(await request.json()).toEqual({ value: '中文' })
    await backendFetch('https://server.example/api/draft', { method: 'PUT', keepalive: true })
    expect(fetch).toHaveBeenLastCalledWith('https://server.example/api/draft', { method: 'PUT', keepalive: true })
  })

  it('preserves HTTP errors for response interceptors instead of turning them into network errors', async () => {
    const { configureNativeHttp } = await import('../http')
    const { default: axios } = await import('axios')
    configureNativeHttp(vi.fn().mockResolvedValue(new Response('{"detail":"unauthorized"}', {
      status: 401, headers: { 'Content-Type': 'application/json' },
    })))
    const client = axios.create()
    const onError = vi.fn(error => Promise.reject(error))
    client.interceptors.response.use(undefined, onError)
    await expect(client.get('https://server.example/api/me')).rejects.toMatchObject({
      response: { status: 401, data: { detail: 'unauthorized' } },
    })
    expect(onError).toHaveBeenCalledOnce()
  })

  it('propagates timeouts to the native fetch AbortSignal', async () => {
    const { configureNativeHttp } = await import('../http')
    const { default: axios } = await import('axios')
    let signal: AbortSignal | undefined
    configureNativeHttp(vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        signal = init?.signal ?? undefined
        if (!signal) return reject(new Error('Native fetch did not receive the AbortSignal'))
        signal.addEventListener('abort', () => reject('Request cancelled'), { once: true })
      })
    }))
    await expect(axios.create({ timeout: 20 }).get('https://server.example/api/slow')).rejects.toMatchObject({
      code: 'ETIMEDOUT',
    })
    expect(signal?.aborted).toBe(true)
  })
})
