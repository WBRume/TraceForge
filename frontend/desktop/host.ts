import { createInterface } from 'node:readline'
import { registerDesktopCommands } from './register'
import { handlers, receiveNative, sender, send, shutdownNative } from './tauri-native'
import { shutdownCommands } from '../electron/ipc/process'
import { shutdownLocalServices } from '../electron/ipc/localResources'
import { shutdownSpeech } from '../electron/ipc/speech'

// stdout is a protocol stream; diagnostic logging belongs on stderr.
console.log = console.error
console.info = console.error
registerDesktopCommands()
let shuttingDown = false
const shutdown = async () => {
  if (shuttingDown) return
  shuttingDown = true
  shutdownCommands()
  await Promise.allSettled([shutdownLocalServices(), shutdownSpeech()])
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
      const handler = handlers.get(request.channel)
      if (!handler) throw new Error('Unknown desktop command')
      if (request.channel === 'sdd:download:save' && Array.isArray(request.payload?.data)) {
        request.payload.data = new Uint8Array(request.payload.data)
      }
      const result = await handler({ sender }, request.payload)
      send({ kind: 'result', id, result: result ?? null })
    } catch (error) {
      send({ kind: 'result', id, error: error instanceof Error ? error.message : String(error) })
    }
  })()
})
input.once('close', shutdown)
process.once('SIGTERM', shutdown)
