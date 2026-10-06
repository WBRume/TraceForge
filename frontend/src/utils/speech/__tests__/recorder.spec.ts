import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SpeechRecorder } from '../recorder'

const getUserMedia = vi.fn()
const addModule = vi.fn()
const closeContext = vi.fn()
const track = { stop: vi.fn(), addEventListener: vi.fn() }
const device = { getTracks: () => [track], getAudioTracks: () => [track] }

beforeEach(() => {
  getUserMedia.mockResolvedValue(device)
  addModule.mockResolvedValue(undefined)
  closeContext.mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL() { return 'blob:speech-test' }
    static revokeObjectURL() {}
  })
  vi.stubGlobal('AudioContext', class {
    state = 'suspended'
    sampleRate = 16000
    audioWorklet = { addModule }
    destination = {}
    resume() { this.state = 'running'; return Promise.resolve() }
    createMediaStreamSource() { return { connect() {}, disconnect() {} } }
    close() { this.state = 'closed'; return closeContext() }
  })
  vi.stubGlobal('AudioWorkletNode', class {
    port = { onmessage: undefined, close() {} }
    connect() {}
    disconnect() {}
  })
})

afterEach(() => { vi.unstubAllGlobals() })

describe('speech device startup', () => {
  it('loads the worklet while microphone acquisition is pending', async () => {
    let grant!: (value: typeof device) => void
    getUserMedia.mockImplementationOnce(() => new Promise(resolve => { grant = resolve }))
    const recorder = new SpeechRecorder()
    const started = recorder.start()
    expect(getUserMedia).toHaveBeenCalledOnce()
    expect(addModule).toHaveBeenCalledOnce()
    grant(device); await started
    recorder.dispose()
    expect(track.stop).toHaveBeenCalledOnce()
    expect(closeContext).toHaveBeenCalledOnce()
  })

  it('stops a device granted after worklet startup has already failed', async () => {
    let grant!: (value: typeof device) => void
    getUserMedia.mockImplementationOnce(() => new Promise(resolve => { grant = resolve }))
    addModule.mockRejectedValueOnce(new Error('module failed'))
    const recorder = new SpeechRecorder()
    await expect(recorder.start()).rejects.toThrow('module failed')
    expect(closeContext).toHaveBeenCalledOnce()
    grant(device); await Promise.resolve()
    expect(track.stop).toHaveBeenCalledOnce()
  })

  it('closes initialized audio resources when microphone access is denied', async () => {
    getUserMedia.mockRejectedValueOnce(new DOMException('denied', 'NotAllowedError'))
    const recorder = new SpeechRecorder()
    await expect(recorder.start()).rejects.toMatchObject({ name: 'NotAllowedError' })
    expect(closeContext).toHaveBeenCalledOnce()
  })
})
