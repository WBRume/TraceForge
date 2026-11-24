import { createInterface } from 'node:readline'
import { registerDesktopCommands } from './register'
import { app, handlers, nativeRequest, receiveNative, sender, send, shutdownNative } from './tauri-native'
import { shutdownCommands } from '../electron/ipc/process'
import { shutdownLocalServices } from '../electron/ipc/localResources'
import { shutdownSpeech } from '../electron/ipc/speech'
import { guardClosedOutputPipes } from './stdio'
import { createWorkspaceWindows } from './workspaceWindows'

// stdout is a protocol stream; diagnostic logging belongs on stderr.
console.log = console.error
console.info = console.error
guardClosedOutputPipes()
registerDesktopCommands()
const workspaceWindows = createWorkspaceWindows({
  create: (id, placement, position) => nativeRequest('workspace-window', { action: 'create', id, placement, position }),
  restoreMain: placement => nativeRequest('workspace-window', { action: 'restore', id: 'main', placement }),
  destroy: id => nativeRequest('workspace-window', { action: 'destroy', id }),
  focus: id => nativeRequest('workspace-window', { action: 'focus', id }),
  pointer: () => nativeRequest('workspace-window', { action: 'pointer' }),
  emit: (window, channel, payload) => send({ kind: 'event', window, channel, payload }),
}, app.getPath('userData'))
let shuttingDown = false
const shutdown = async () => {
  if (shuttingDown) return
  shuttingDown = true
  shutdownCommands()
  await Promise.allSettled([shutdownLocalServices(), shutdownSpeech(), workspaceWindows.flush()])
  shutdownNative()
  process.exit(0)
}
const input = createInterface({ input: process.stdin, crlfDelay: Infinity })
input.on('line', line => {
  void (async () => {
    let id: string | undefined
    try {
      const request = JSON.parse(line)
      if (request.kind === 'shutdown') { shutdown(); return }
      id = request.id
      if (request.kind === 'native-result') { receiveNative(request); return }
      if (request.kind === 'workspace-window-event') {
        if (shuttingDown) return
        if (request.event === 'closed') workspaceWindows.closed(request.window)
        if (request.event === 'geometry') workspaceWindows.geometry(request.window, request.placement)
        return
      }
      if (shuttingDown) throw new Error('Desktop service is shutting down')
      const { window, channel, payload } = request
      if (channel.startsWith('sdd:workspace-window:')) {
        let result: unknown
        switch (channel) {
          case 'sdd:workspace-window:command': result = await workspaceWindows.command(window, payload); break
          case 'sdd:workspace-window:strip': result = workspaceWindows.setStrip(window, payload); break
          case 'sdd:workspace-window:drag': result = await workspaceWindows.drag(window, payload.tabId, payload.phase); break
          default: throw new Error('Unknown workspace window command')
        }
        send({ kind: 'result', id, result: result ?? null })
        return
      }
      const handler = handlers.get(channel)
      if (!handler) throw new Error('Unknown desktop command')
      if (request.channel === 'sdd:download:save' && Array.isArray(request.payload?.data)) {
        request.payload.data = new Uint8Array(request.payload.data)
      }
      const result = await handler({ sender: window && channel !== 'sdd:collaboration:execute' ? {
        send: (channel, payload) => send({ kind: 'event', window, channel, payload }),
      } : sender }, request.payload)
      send({ kind: 'result', id, result: result ?? null })
    } catch (error) {
      send({ kind: 'result', id, error: error instanceof Error ? error.message : String(error) })
    }
  })()
})
input.once('close', shutdown)
process.once('SIGTERM', shutdown)
process.once('SIGINT', shutdown)
process.stdout.on('error', error => {
  if ((error as NodeJS.ErrnoException).code === 'EPIPE') void shutdown()
  else throw error
})
