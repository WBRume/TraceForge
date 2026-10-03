import { ipcMain } from '../../desktop/native'
import type { WebhookRequest } from '../../src/types/taskAwareness'

export async function sendNativeWebhook(payload: WebhookRequest): Promise<{ ok: boolean; error?: string }> {
  try {
    const url = new URL(payload.url)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.hash || payload.url.length > 2048) return { ok: false, error: 'NetworkError' }
    const body = JSON.stringify(payload.body)
    if (body.length > 64_000) return { ok: false, error: 'ResponseTooLarge' }
    const response = await fetch(url, { method: 'POST', body, redirect: 'error', signal: AbortSignal.timeout(3000),
      headers: { 'Content-Type': 'application/json', 'X-TraceForge-Event-Id': payload.event_id } })
    // A standard webhook is acknowledged by HTTP status, with no vendor protocol.
    try { await response.body?.cancel() } catch { /* Only the HTTP status determines delivery. */ }
    return response.ok ? { ok: true } : { ok: false, error: 'HttpError' }
  } catch (error) {
    return { ok: false, error: error instanceof Error && ['TimeoutError', 'AbortError'].includes(error.name) ? 'TimeoutError' : 'NetworkError' }
  }
}

export function registerWebhooksIpc() {
  ipcMain.handle('sdd:webhooks:send', (_event, payload: WebhookRequest) => sendNativeWebhook(payload))
}
