type SpeechBuildOptions = { mode: 'off' | 'api' | 'offline'; enabled: boolean; bundled: boolean; assetsDirectory: string }
export function speechBuildOptions(env?: Record<string, string | undefined>): SpeechBuildOptions
export function validateSpeechAssets(options: SpeechBuildOptions, platform?: string, arch?: string): void
