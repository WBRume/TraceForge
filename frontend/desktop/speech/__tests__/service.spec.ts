import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mkdtemp, mkdir, writeFile, readdir, readFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { execFile } from 'node:child_process'
import { OfflineSpeechService, validateWav, parseTranscript, MAX_WAV_BYTES } from '../service'
import { speechBuildOptions, validateSpeechAssets } from '../build-options.cjs'

vi.mock('node:child_process', () => { const execFile = vi.fn(); return { execFile, default: { execFile } } })
let root: string
let service: OfflineSpeechService
function wav(length = 3200) {
  const bytes = Buffer.alloc(44 + length)
  bytes.write('RIFF'); bytes.writeUInt32LE(bytes.length - 8, 4); bytes.write('WAVEfmt ', 8)
  bytes.writeUInt32LE(16, 16); bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(1, 22)
  bytes.writeUInt32LE(16000, 24); bytes.writeUInt32LE(32000, 28); bytes.writeUInt16LE(2, 32)
  bytes.writeUInt16LE(16, 34); bytes.write('data', 36); bytes.writeUInt32LE(length, 40)
  return bytes
}
beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), 'traceforge-speech-test-'))
  await mkdir(join(root, 'bin'))
  for (const path of ['bin/sherpa-onnx-offline.exe', 'bin/onnxruntime.dll', 'model.int8.onnx', 'tokens.txt']) await writeFile(join(root, path), 'fixture')
  service = new OfflineSpeechService({ available: true, temp: root, bundledAssets: root, platform: 'win32' })
})
afterEach(async () => { service.cancel(); await rm(root, { recursive: true, force: true }) })

describe('optional offline recognition', () => {
  it('keeps API/off builds independent of assets and rejects incompatible bundling', async () => {
    expect(speechBuildOptions({}).mode).toBe('api')
    validateSpeechAssets(speechBuildOptions({ TRACEFORGE_SPEECH_ASSETS: 'does-not-exist' }))
    expect(() => speechBuildOptions({ TRACEFORGE_BUNDLE_SPEECH: '1' })).toThrow('requires')
    expect(() => speechBuildOptions({ TRACEFORGE_SPEECH_MODE: 'invalid' })).toThrow('must be')
    expect(() => validateSpeechAssets(speechBuildOptions({ TRACEFORGE_SPEECH_MODE: 'offline', TRACEFORGE_BUNDLE_SPEECH: '1', TRACEFORGE_SPEECH_ASSETS: 'does-not-exist' }))).toThrow('Missing')
    const disabled = new OfflineSpeechService({ available: false, temp: root, bundledAssets: root })
    await expect(disabled.transcribe({ id: 'x', wavBase64: wav().toString('base64') })).rejects.toThrow('not included')
    expect(execFile).not.toHaveBeenCalled()
  })

  it('validates audio format and maximum duration at the desktop boundary', () => {
    expect(validateWav(wav(MAX_WAV_BYTES - 44).toString('base64')).length).toBe(MAX_WAV_BYTES)
    expect(() => validateWav(wav(MAX_WAV_BYTES).toString('base64'))).toThrow()
    const stereo = wav(); stereo.writeUInt16LE(2, 22)
    expect(() => validateWav(stereo.toString('base64'))).toThrow('mono')
    expect(() => validateWav('not audio')).toThrow()
  })

  it('runs the SenseVoice-Small model without a shell and deletes temporary audio', async () => {
    vi.mocked(execFile).mockImplementation(((_exe: string, args: string[], _options: unknown, callback: Function) => {
      void readFile(args.at(-1)!).then(bytes => {
        expect(bytes).toEqual(wav())
        callback(null, '', 'diagnostic\n{"text":"<|zh|>你好"}\n')
      })
      return { kill: vi.fn() }
    }) as any)
    await expect(service.transcribe({ id: 'one', wavBase64: wav().toString('base64') })).resolves.toEqual({ text: '你好' })
    expect(execFile).toHaveBeenCalledWith(join(root, 'bin/sherpa-onnx-offline.exe'), expect.arrayContaining([`--sense-voice-model=${join(root, 'model.int8.onnx')}`]), expect.objectContaining({ windowsHide: true, timeout: 120000 }), expect.any(Function))
    expect((await readdir(root)).some(name => name.startsWith('traceforge-speech-'))).toBe(false)
  })

  it('reserves a job before async setup and honors immediate cancellation', async () => {
    const first = service.transcribe({ id: 'one', wavBase64: wav().toString('base64') })
    await expect(service.transcribe({ id: 'two', wavBase64: wav().toString('base64') })).rejects.toThrow('busy')
    service.cancel('one')
    await expect(first).rejects.toThrow('canceled')
    expect(execFile).not.toHaveBeenCalled()
  })

  it('detects missing assets and does not invent successful text from diagnostics', async () => {
    await rm(join(root, 'model.int8.onnx'))
    expect((await service.status()).reason).toBe('missing_assets')
    expect(() => parseTranscript('engine failed')).toThrow('no transcript')
  })

  it('rejects incomplete runtime dependencies and assets for another architecture', async () => {
    const options = speechBuildOptions({ TRACEFORGE_SPEECH_MODE: 'offline', TRACEFORGE_BUNDLE_SPEECH: '1', TRACEFORGE_SPEECH_ASSETS: root })
    await writeFile(join(root, 'manifest.json'), JSON.stringify({ model: 'SenseVoice-Small', quantization: 'int8', platform: 'win32', arch: 'arm64' }))
    expect(() => validateSpeechAssets(options, 'win32', 'x64')).toThrow('win32/x64')
    await rm(join(root, 'bin/onnxruntime.dll'))
    expect((await service.status()).ready).toBe(false)
    expect(() => validateSpeechAssets(options, 'win32', 'arm64')).toThrow('onnxruntime.dll')
  })

  it('terminates an active decoder on cancel and removes its temporary recording', async () => {
    let callback!: Function
    const kill = vi.fn(() => callback({ killed: true }, '', 'private diagnostics'))
    vi.mocked(execFile).mockImplementation(((_exe: string, _args: string[], _options: unknown, done: Function) => {
      callback = done
      return { kill }
    }) as any)
    const task = service.transcribe({ id: 'active', wavBase64: wav().toString('base64') })
    await vi.waitFor(() => expect(execFile).toHaveBeenCalledOnce())
    service.cancel('different-task')
    expect(kill).not.toHaveBeenCalled()
    const canceled = expect(task).rejects.toThrow('canceled')
    service.cancel('active')
    await canceled
    expect(kill).toHaveBeenCalledOnce()
    expect((await readdir(root)).some(name => name.startsWith('traceforge-speech-'))).toBe(false)
  })

  it('waits for decoder exit and recording deletion before the desktop host shuts down', async () => {
    let done!: Function
    const kill = vi.fn()
    vi.mocked(execFile).mockImplementation(((_exe: string, _args: string[], _options: unknown, callback: Function) => {
      done = callback
      return { kill }
    }) as any)
    const task = service.transcribe({ id: 'shutdown', wavBase64: wav().toString('base64') })
    const canceled = expect(task).rejects.toThrow('canceled')
    await vi.waitFor(() => expect(execFile).toHaveBeenCalledOnce())
    let closed = false
    const shutdown = service.shutdown().then(() => { closed = true })
    await Promise.resolve()
    expect(kill).toHaveBeenCalledOnce()
    expect(closed).toBe(false)
    done({ killed: true }, '', '')
    await shutdown
    await canceled
    expect((await readdir(root)).some(name => name.startsWith('traceforge-speech-'))).toBe(false)
  })
})
