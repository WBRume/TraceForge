export type SpeechStatus = {
  available: boolean
  ready: boolean
  reason: 'unavailable' | 'missing_assets' | 'ready'
}

export type OfflineSpeechApi = {
  status: () => Promise<SpeechStatus>
  transcribe: (payload: { id: string; wavBase64: string }) => Promise<{ text: string }>
  cancel: (id: string) => Promise<void>
}
