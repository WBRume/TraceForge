import { join } from 'node:path'
import { app, ipcMain, speechResourcesPath } from '../../desktop/native'
import { OfflineSpeechService } from '../../desktop/speech/service'

declare const __OFFLINE_SPEECH__: boolean
let service: OfflineSpeechService | undefined

export async function shutdownSpeech() { await service?.shutdown() }

export function registerSpeechIpc() {
  service = new OfflineSpeechService({
    available: typeof __OFFLINE_SPEECH__ !== 'undefined' && __OFFLINE_SPEECH__,
    temp: app.getPath('temp'),
    bundledAssets: process.env.TRACEFORGE_SPEECH_ASSETS || join(speechResourcesPath(), 'offline-speech'),
  })
  const speech = service
  ipcMain.handle('sdd:speech:status', () => speech.status())
  ipcMain.handle('sdd:speech:transcribe', (_event, payload) => speech.transcribe(payload))
  ipcMain.handle('sdd:speech:cancel', (_event, payload) => {
    if (typeof payload?.id !== 'string') throw new Error('Speech request id is required')
    speech.cancel(payload.id)
  })
}
