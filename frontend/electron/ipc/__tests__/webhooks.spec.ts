import { afterEach, describe, expect, it, vi } from 'vitest'
import { createServer } from 'node:http'
import { transferableAbortController } from 'node:util'
vi.mock('../../../desktop/native', () => ({ ipcMain: { handle: vi.fn() } }))
import { sendNativeWebhook } from '../webhooks'
afterEach(() => vi.unstubAllGlobals())
describe('native webhook transport', () => {
  it('posts JSON to a real local listener and propagates the idempotency header', async () => {
    // jsdom's AbortSignal is incompatible with Node's native fetch transport.
    vi.stubGlobal('AbortSignal', transferableAbortController().signal.constructor)
    let received: any
    const server = createServer((request, response) => {
      let content = ''; request.on('data', part => { content += part }); request.on('end', () => {
        received = { body: JSON.parse(content), id: request.headers['x-traceforge-event-id'] }
        response.writeHead(204); response.end()
      })
    })
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
    try {
      const address = server.address() as { port: number }
      expect(await sendNativeWebhook({ url: `http://127.0.0.1:${address.port}/pet`, body: { event_type: 'AI_RUN_FINISHED' }, event_id: 'event-1' })).toEqual({ ok: true })
      expect(received).toEqual({ body: { event_type: 'AI_RUN_FINISHED' }, id: 'event-1' })
    } finally { await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()) }) }
  })
  it('uses HTTP status without a service specific response protocol and returns safe failures', async () => {
    const request = { url: 'https://hooks.example/secret', body: {}, event_id: 'e1' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"code":42,"detail":"custom response"}', { status: 200 })))
    expect(await sendNativeWebhook(request)).toEqual({ ok: true })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('secret', { status: 503 })))
    expect(await sendNativeWebhook(request)).toEqual({ ok: false, error: 'HttpError' })
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(Object.assign(new Error('secret'), { name: 'TimeoutError' })))
    expect(await sendNativeWebhook(request)).toEqual({ ok: false, error: 'TimeoutError' })
    expect(await sendNativeWebhook({ ...request, url: 'file:///secret' })).toEqual({ ok: false, error: 'NetworkError' })
  })
})
