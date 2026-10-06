export type SpeechMode = 'off' | 'api' | 'offline'

export function speechMode(): SpeechMode {
  const mode = import.meta.env.VITE_SPEECH_MODE
  if (mode === 'api') return 'api'
  if (mode === 'offline' && window.sddDesktop?.speech) return 'offline'
  return 'off'
}
