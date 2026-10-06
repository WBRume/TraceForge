import { execFile, type ChildProcess } from 'node:child_process'
import { mkdtemp, rm, stat, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import type { SpeechStatus } from '../../src/types/offlineSpeech'

export const MAX_WAV_BYTES = 44 + 16000 * 2 * 60

export function validateWav(base64: unknown): Buffer {
  if (typeof base64 !== 'string' || base64.length > Math.ceil(MAX_WAV_BYTES / 3) * 4
    || base64.length % 4 !== 0 || /[^A-Za-z0-9+/=]/.test(base64) || /=/.test(base64.slice(0, -2))) {
    throw new Error('Invalid audio payload')
  }
  const wav = Buffer.from(base64, 'base64')
  if (wav.length < 44 + 3200 || wav.length > MAX_WAV_BYTES || wav.length % 2 !== 0
    || wav.toString('ascii', 0, 4) !== 'RIFF' || wav.readUInt32LE(4) !== wav.length - 8
    || wav.toString('ascii', 8, 16) !== 'WAVEfmt ' || wav.readUInt32LE(16) !== 16
    || wav.readUInt16LE(20) !== 1 || wav.readUInt16LE(22) !== 1
    || wav.readUInt32LE(24) !== 16000 || wav.readUInt32LE(28) !== 32000
    || wav.readUInt16LE(32) !== 2 || wav.readUInt16LE(34) !== 16
    || wav.toString('ascii', 36, 40) !== 'data' || wav.readUInt32LE(40) !== wav.length - 44) {
    throw new Error('Expected 0.1–60 seconds of mono 16 kHz PCM16 WAV audio')
  }
  return wav
}

export function parseTranscript(output: string): string {
  for (const line of output.split(/\r?\n/)) {
    if (!line.trim().startsWith('{')) continue
    try {
      const result = JSON.parse(line)
      if (typeof result.text === 'string') return result.text.replace(/<\|[^|]*\|>/g, '').trim()
    } catch { /* Sherpa also emits diagnostic lines. */ }
  }
  throw new Error('Speech engine returned no transcript')
}

type Options = { available: boolean; temp: string; bundledAssets: string; platform?: string }
type Job = { id: string; canceled: boolean; child?: ChildProcess; done: Promise<void> }

/** Optional standalone Sherpa CLI keeps native dependencies out of both JS runtimes. */
export class OfflineSpeechService {
  private job?: Job
  private readonly options: Options

  constructor(options: Options) { this.options = options }

  private assets() {
    const root = resolve(this.options.bundledAssets)
    return {
      root,
      executable: join(root, 'bin', (this.options.platform || process.platform) === 'win32' ? 'sherpa-onnx-offline.exe' : 'sherpa-onnx-offline'),
      model: join(root, 'model.int8.onnx'),
      tokens: join(root, 'tokens.txt'),
    }
  }

  async status(): Promise<SpeechStatus> {
    const assets = this.assets()
    const required = [assets.executable, assets.model, assets.tokens]
    if ((this.options.platform || process.platform) === 'win32') required.push(join(assets.root, 'bin', 'onnxruntime.dll'))
    const present = this.options.available && (await Promise.all(
      required.map(path => stat(path).then(s => s.isFile() && s.size > 0).catch(() => false)),
    )).every(Boolean)
    return {
      available: this.options.available, ready: Boolean(present),
      reason: !this.options.available ? 'unavailable' : !present ? 'missing_assets' : 'ready',
    }
  }

  cancel(id?: string) {
    if (!this.job || (id && id !== this.job.id)) return
    this.job.canceled = true
    this.job.child?.kill()
  }

  async shutdown() {
    const job = this.job
    this.cancel()
    await job?.done // Keep the host alive until the child exits and its recording is removed.
  }

  async transcribe(payload: { id: string; wavBase64: string }): Promise<{ text: string }> {
    if (!this.options.available) throw new Error('Offline speech is not included in this build')
    if (!payload || typeof payload.id !== 'string' || !/^[a-zA-Z0-9-]{1,80}$/.test(payload.id)) throw new Error('Invalid speech request')
    if (this.job) throw new Error('Speech engine is busy')
    let finish!: () => void
    const job: Job = { id: payload.id, canceled: false, done: new Promise(resolve => { finish = resolve }) }
    this.job = job // Reserve before any await; cancellation can arrive during setup.
    let directory: string | undefined
    try {
      if (!(await this.status()).ready) throw new Error('Offline speech is disabled or its assets are missing')
      const wav = validateWav(payload.wavBase64)
      const assets = this.assets()
      directory = await mkdtemp(join(this.options.temp, 'traceforge-speech-'))
      const input = join(directory, 'input.wav')
      await writeFile(input, wav, { mode: 0o600 })
      if (job.canceled) throw new Error('Speech recognition canceled')
      const output = await new Promise<string>((resolve, reject) => {
        job.child = execFile(assets.executable, [
          `--tokens=${assets.tokens}`, `--sense-voice-model=${assets.model}`,
          '--sense-voice-language=auto', '--sense-voice-use-itn=1',
          '--num-threads=2', '--provider=cpu', '--debug=0', input,
        ], { cwd: assets.root, windowsHide: true, timeout: 120000, maxBuffer: 1024 * 1024, encoding: 'utf8' }, (error, stdout, stderr) => {
          if (error) reject(new Error(error.killed ? 'Speech recognition timed out or was canceled' : 'Speech engine failed; check the local runtime and model files'))
          else resolve(`${stdout}\n${stderr}`)
        })
      })
      if (job.canceled) throw new Error('Speech recognition canceled')
      return { text: parseTranscript(output) }
    } finally {
      if (directory) await rm(directory, { recursive: true, force: true }).catch(() => {})
      if (this.job === job) this.job = undefined
      finish()
    }
  }
}
