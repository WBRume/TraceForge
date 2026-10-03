import api from '@/utils/api'
import type { WebhookRequest } from '@/types/taskAwareness'
import { useAuthStore } from '@/stores/auth'

let draining: Promise<void> | undefined
let requested = false
/** Only native clients claim local deliveries. No browser fetch or focus gate. */
export function flushDesktopWebhooks(): Promise<void> {
  if (!window.sddDesktop?.webhooks) return Promise.resolve()
  if (draining) { requested = true; return draining }
  const native = window.sddDesktop.webhooks
  const auth = useAuthStore()
  const userId = auth.user?.id
  const server = String(api.defaults?.baseURL || '')
  const isCurrent = () => auth.user?.id === userId && String(api.defaults?.baseURL || '') === server
  if (!userId) return Promise.resolve()
  draining = (async () => {
    try {
      while (isCurrent()) {
        const { data } = await api.post('/task-awareness/desktop-deliveries/claim', undefined, { timeout: 3000 })
        if (!isCurrent()) break
        const items = data.items as (WebhookRequest & { id: string; lease_token: string })[]
        if (!items.length) break
        // Ten leased items fit within 30 seconds: four groups × (3s POST + 3s ACK).
        for (let offset = 0; offset < items.length && isCurrent(); offset += 3) {
          const results = await Promise.allSettled(items.slice(offset, offset + 3).map(async item => {
            if (!isCurrent()) return
            let result: { ok: boolean; error?: string } = { ok: false, error: 'NetworkError' }
            try { result = await native.send(item) } catch { /* Report only a non-secret category. */ }
            if (!isCurrent()) return
            await api.post('/task-awareness/desktop-deliveries/ack', { id: item.id, lease_token: item.lease_token, ...result }, { timeout: 3000 })
          }))
          if (results.some(result => result.status === 'rejected')) return
        }
      }
    } catch { /* Unacknowledged leases are recovered after reconnect. */ }
    finally {
      const again = requested || !isCurrent()
      requested = false; draining = undefined
      if (again) void flushDesktopWebhooks()
    }
  })()
  return draining
}
