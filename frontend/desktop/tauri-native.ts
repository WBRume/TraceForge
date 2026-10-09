import { homedir, tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { startServer } from './local-resource/server'
import type { Config } from './local-resource/runtime'

type Handler = (event: { sender: typeof sender }, payload: any) => unknown
export const handlers = new Map<string, Handler>()
const pendingNative = new Map<string, { resolve: (value: any) => void; reject: (error: Error) => void }>()
let nativeSequence = 0

export function send(message: unknown) {
  process.stdout.write(`${JSON.stringify(message)}\n`)
}

export function receiveNative(message: { id: string; result?: unknown; error?: string }) {
  const pending = pendingNative.get(message.id)
  pendingNative.delete(message.id)
  if (message.error) pending?.reject(new Error(message.error))
  else pending?.resolve(message.result)
}

function nativeRequest(method: string, payload: unknown = {}) {
  return new Promise<any>((resolve, reject) => {
    const id = `native-${++nativeSequence}`
    pendingNative.set(id, { resolve, reject })
    send({ kind: 'native', id, method, payload })
  })
}

export const sender = { send: (channel: string, payload: unknown) => send({ kind: 'event', channel, payload }) }
export const ipcMain = { handle: (channel: string, handler: Handler) => { handlers.set(channel, handler) } }
export const setNativeAttention = (_sender: unknown, payload: { flash: boolean; hitlCount: number }) => nativeRequest('attention', payload)
export const app = {
  getPath(name: string) {
    if (name === 'userData') return process.argv[2]!
    if (name === 'temp') return tmpdir()
    if (name === 'downloads') return process.argv[3] || join(homedir(), 'Downloads')
    throw new Error(`Unsupported application path: ${name}`)
  },
  getAppPath: () => dirname(process.execPath),
}
export const speechResourcesPath = () => process.argv[4] || dirname(process.execPath)
export const BrowserWindow = {
  fromWebContents: () => null,
  getAllWindows: () => [{ webContents: sender, isDestroyed: () => false }],
}
export const shell = {
  openExternal: (url: string) => nativeRequest('open-external', { url }),
  openPath: async (path: string) => { await nativeRequest('open-path', { path }); return '' },
}
export const dialog = {
  showOpenDialog: (options: unknown) => nativeRequest('select-directory', options),
  showSaveDialog: (...args: unknown[]) => nativeRequest('save-file', args.at(-1)),
}
export function startLocalResourceService(config: Config) {
  return startServer(config, { workerUrl: new URL('./worker.js', import.meta.url).href })
}

export function shutdownNative() {
  for (const pending of pendingNative.values()) pending.reject(new Error('Desktop service closed'))
  pendingNative.clear()
}
