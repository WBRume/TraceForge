import { createDesktopApi } from '../../desktop/api'
import type { DesktopSaveRequest } from '../types/sddDesktop'

export async function initializeDesktopRuntime(): Promise<void> {
  if (window.sddDesktop || !('__TAURI_INTERNALS__' in window)) return
  const [{ invoke }, { listen }] = await Promise.all([
    import('@tauri-apps/api/core'),
    import('@tauri-apps/api/event'),
  ])
  const listeners = new Map<string, Set<(payload: any) => void>>()
  const unlisten = await listen<{ channel: string; payload: unknown }>('desktop-event', event => {
    for (const listener of listeners.get(event.payload.channel) ?? []) listener(event.payload.payload)
  })
  window.addEventListener('beforeunload', unlisten, { once: true })
  const platform = await invoke<string>('desktop_platform')
  window.sddDesktop = createDesktopApi({
    runtime: 'tauri',
    platform,
    invoke: (channel, payload) => {
      // Tauri JSON IPC cannot carry ArrayBuffer/Uint8Array directly.
      if (channel === 'sdd:download:save') {
        const request = payload as DesktopSaveRequest
        const bytes = request.data instanceof Uint8Array ? request.data : new Uint8Array(request.data)
        payload = { ...request, data: Array.from(bytes) }
      }
      return invoke('desktop_invoke', { channel, payload: payload ?? null })
    },
    subscribe: (channel, listener) => {
      let channelListeners = listeners.get(channel)
      if (!channelListeners) listeners.set(channel, channelListeners = new Set())
      channelListeners.add(listener)
      return () => { channelListeners.delete(listener) }
    },
  })
}
