export type SpeechSession = {
  provider?: string
  transport?: 'websocket'
  token: string
  expires_at: number
  websocket_url: string
  model: string
}

/** Preview and finish return complete text, never provider-specific deltas. */
export interface SpeechStream {
  start(session: SpeechSession, sampleRate: number): Promise<void>
  sendPcm(pcm: Uint8Array): void
  beginCapture(): void
  keepAlive(): void
  finish(): Promise<string>
  cancel(): void
}
