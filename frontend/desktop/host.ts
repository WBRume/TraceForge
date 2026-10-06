import { createInterface } from 'node:readline'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { registerDesktopCommands } from './register'
import { handlers, receiveNative, sender, send, shutdownNative } from './tauri-native'
import { shutdownCommands } from '../electron/ipc/process'
import { shutdownLocalServices } from '../electron/ipc/localResources'
import { shutdownSpeech } from '../electron/ipc/speech'

if (process.argv[2] === '--local-resource-service') {
  const configPath = resolve(process.argv[3]!)
  const { startServer } = await import('./local-resource/server')
  const host = await startServer(
    { ...JSON.parse(readFileSync(configPath, 'utf8')), roots_config_path: configPath },
    { workerUrl: new URL('./worker.js', import.meta.url).href },
  )
  const shutdown = async () => { await host.close(); process.exit(0) }
  process.once('SIGTERM', shutdown)
  process.once('SIGINT', shutdown)
} else {
  // stdout is a protocol stream; diagnostic logging belongs on stderr.
  console.log = console.error
  console.info = console.error
  registerDesktopCommands()
  let shuttingDown = false
  const shutdown = async () => {
    if (shuttingDown) return
    shuttingDown = true
    shutdownCommands()
    shutdownLocalServices()
    await shutdownSpeech()
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
}
