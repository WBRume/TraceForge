import api from '@/utils/api'
import { QwenSpeechStream } from './qwen'
import type { SpeechSession, SpeechStream } from './types'

type StreamProvider = {
  standby: boolean
  cacheCredentials: boolean
  create: (preview: (text: string) => void, failure: (error: Error) => void) => SpeechStream
}

/** Browser-side protocol plugins paired with the server credential provider. */
export const speechStreamProviders: Record<string, StreamProvider> = {
  bailian: {
    standby: true,
    cacheCredentials: true,
    create: (preview, failure) => new QwenSpeechStream(preview, failure),
  },
}

export function streamProvider(provider: string): StreamProvider {
  const plugin = speechStreamProviders[provider]
  if (!plugin) throw new Error('Unsupported speech provider')
  return plugin
}

export async function transcribeAudio(wavBase64: string, signal: AbortSignal, generation: string): Promise<string> {
  const bytes = Uint8Array.from(atob(wavBase64), char => char.charCodeAt(0))
  const { data } = await api.post<{ text: string }>('/speech/transcriptions', new Blob([bytes], { type: 'audio/wav' }), {
    signal, timeout: 70000,
    headers: { 'Content-Type': 'audio/wav', 'X-Speech-Generation': generation },
  })
  if (typeof data.text !== 'string') throw new Error('Invalid speech response')
  return data.text
}

export type { SpeechSession, SpeechStream }
