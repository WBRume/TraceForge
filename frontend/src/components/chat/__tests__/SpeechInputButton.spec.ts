import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import SpeechInputButton from '../SpeechInputButton.vue'
import zh from '@/locales/zh.json'

const mocks = vi.hoisted(() => ({
  captureStart: vi.fn(), captureStop: vi.fn(), dispose: vi.fn(),
  streamStart: vi.fn(), streamFinish: vi.fn(), streamCancel: vi.fn(), beginCapture: vi.fn(), keepAlive: vi.fn(), pcm: vi.fn(), post: vi.fn(), get: vi.fn(),
  transcript: undefined as ((text: string) => void) | undefined,
  failure: undefined as ((reason: Error) => void) | undefined,
}))
vi.mock('@/utils/api', () => ({ default: { post: mocks.post, get: mocks.get } }))
vi.mock('@/utils/speech/recorder', () => ({ SpeechRecorder: class {
  start = mocks.captureStart; stop = mocks.captureStop; dispose = mocks.dispose
} }))
vi.mock('@/utils/speech/qwen', () => ({ QwenSpeechStream: class {
  constructor(onTranscript: (text: string) => void, onFailure: (reason: Error) => void) { mocks.transcript = onTranscript; mocks.failure = onFailure }
  start = mocks.streamStart; finish = mocks.streamFinish; cancel = mocks.streamCancel; sendPcm = mocks.pcm
  beginCapture = mocks.beginCapture
  keepAlive = mocks.keepAlive
} }))
const i18n = createI18n({ legacy: false, locale: 'zh', messages: { zh } })
const mountButton = () => mount(SpeechInputButton, { props: { disabled: false, contextKey: 'task-a' }, global: { plugins: [i18n] } })
const start = async (wrapper: ReturnType<typeof mountButton>) => { await wrapper.get('button').trigger('click'); await flushPromises() }

beforeEach(() => {
  mocks.get.mockRejectedValue(new Error('Legacy server without capabilities'))
  vi.stubEnv('VITE_SPEECH_MODE', 'api')
  mocks.captureStart.mockImplementation(async (_pcm, _ended, beforeCapture) => { await beforeCapture?.(16000) })
  mocks.captureStop.mockResolvedValue('wav')
  mocks.post.mockResolvedValue({ data: { token: 'st-test', expires_at: Math.floor(Date.now() / 1000) + 120 } })
  mocks.streamStart.mockResolvedValue(undefined)
  mocks.streamFinish.mockResolvedValue('识别结果')
})
afterEach(() => { vi.unstubAllEnvs(); vi.useRealTimers(); delete window.sddDesktop })

describe('voice input modes and lifecycle', () => {
  it('uses server mode after a build with voice input disabled', async () => {
    vi.stubEnv('VITE_SPEECH_MODE', 'off')
    mocks.get.mockResolvedValue({ data: { mode: 'api', generation: 'first', configured: true } })
    const wrapper = mountButton()
    await flushPromises()
    expect(wrapper.find('button').exists()).toBe(true)
    await start(wrapper)
    expect(mocks.captureStart).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('hides the microphone and releases cached streams after a runtime disable', async () => {
    mocks.get.mockResolvedValueOnce({ data: { mode: 'api', generation: 'first', configured: true } })
    const wrapper = mountButton()
    await flushPromises()
    mocks.get.mockResolvedValue({ data: { mode: 'off', generation: 'disabled', configured: true } })
    window.dispatchEvent(new Event('traceforge-features-changed'))
    await flushPromises()
    expect(wrapper.find('button').exists()).toBe(false)
    expect(mocks.streamCancel).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('invalidates prepared credentials when the server generation changes', async () => {
    mocks.get.mockResolvedValueOnce({ data: { mode: 'api', generation: 'first', configured: true } })
    const wrapper = mountButton()
    await flushPromises()
    const before = mocks.post.mock.calls.length
    mocks.get.mockResolvedValue({ data: { mode: 'api', generation: 'changed-key', configured: true } })
    window.dispatchEvent(new Event('traceforge-features-changed'))
    await flushPromises()
    await start(wrapper)
    expect(mocks.post.mock.calls.length).toBeGreaterThan(before)
    wrapper.unmount()
  })
  it('writes interim recognition to the input immediately, without a separate preview', async () => {
    const wrapper = mountButton(); await start(wrapper)
    mocks.transcript?.('你好'); await flushPromises()
    expect(wrapper.emitted('transcript')).toEqual([['你好']])
    expect(wrapper.get('[role="status"]').text()).not.toContain('你好')
    mocks.transcript?.('您好。'); await flushPromises()
    expect(wrapper.emitted('transcript')?.at(-1)).toEqual(['您好。'])
    wrapper.unmount()
  })

  it('starts capture without waiting for credentials and releases it when canceled during connection', async () => {
    let complete!: (value: unknown) => void
    mocks.post.mockImplementation(() => new Promise(resolve => { complete = resolve }))
    const wrapper = mountButton(); await start(wrapper)
    expect(wrapper.get('button').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[role="status"]').text()).toContain('正在录音')
    expect(mocks.streamStart).not.toHaveBeenCalled()
    await wrapper.findAll('button')[1]!.trigger('click')
    expect(mocks.post.mock.calls[0]![2].signal.aborted).toBe(true)
    complete({ data: { token: 'st-test' } }); await flushPromises()
    expect(mocks.streamStart).not.toHaveBeenCalled()
    expect(mocks.dispose).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('prepares on mount without focus, hover or microphone access and reuses the task on a direct click', async () => {
    const wrapper = mountButton(); await flushPromises()
    expect(mocks.post).toHaveBeenCalledOnce()
    expect(mocks.streamStart).toHaveBeenCalledOnce()
    expect(mocks.captureStart).not.toHaveBeenCalled()
    mocks.transcript?.('预连接内容'); await flushPromises()
    expect(wrapper.emitted('transcript')).toBeUndefined()
    await start(wrapper)
    expect(mocks.post).toHaveBeenCalledOnce()
    expect(mocks.streamStart).toHaveBeenCalledOnce()
    expect(mocks.beginCapture).toHaveBeenCalledOnce()
    expect(wrapper.get('[role="status"]').text()).toBe('请开始说话，正在录音…')
    wrapper.unmount()
  })

  it('records and accepts opening words while the ASR task is still starting', async () => {
    let complete!: () => void
    mocks.streamStart.mockImplementation(() => new Promise<void>(resolve => { complete = resolve }))
    const wrapper = mountButton(); await start(wrapper)
    expect(wrapper.get('[role="status"]').text()).toContain('请开始说话')
    const firstWords = new Uint8Array([12, 34])
    mocks.captureStart.mock.calls[0]![0](firstWords)
    expect(mocks.pcm).toHaveBeenCalledWith(firstWords)
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(mocks.streamFinish).not.toHaveBeenCalled()
    complete(); await flushPromises()
    expect(mocks.streamFinish).toHaveBeenCalledOnce()
    expect(wrapper.emitted('transcript')).toEqual([['识别结果']])
    wrapper.unmount()
  })

  it('keeps the task ready past the former fifteen-second expiry without reissuing credentials', async () => {
    vi.useFakeTimers()
    const wrapper = mountButton(); await flushPromises()
    await vi.advanceTimersByTimeAsync(90000)
    expect(mocks.keepAlive).toHaveBeenCalledTimes(91)
    expect(mocks.streamCancel).not.toHaveBeenCalled()
    expect(mocks.captureStart).not.toHaveBeenCalled()
    await start(wrapper)
    expect(mocks.post).toHaveBeenCalledOnce()
    expect(mocks.streamStart).toHaveBeenCalledOnce()
    expect(wrapper.get('button').attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
  })

  it('stops synthetic silence once the microphone takes over', async () => {
    vi.useFakeTimers()
    const wrapper = mountButton()
    await wrapper.get('button').trigger('focus'); await flushPromises()
    await vi.advanceTimersByTimeAsync(100)
    expect(mocks.keepAlive).toHaveBeenCalledOnce()
    await start(wrapper)
    await vi.advanceTimersByTimeAsync(1000)
    expect(mocks.keepAlive).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('silently discards failed standby connections and retries on click', async () => {
    const wrapper = mountButton()
    await wrapper.get('button').trigger('focus'); await flushPromises()
    mocks.failure?.(new Error('closed')); await flushPromises()
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    await start(wrapper)
    expect(mocks.streamStart).toHaveBeenCalledTimes(2)
    expect(wrapper.get('button').attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
  })

  it('reconnects using the actual sample rate before sending device audio', async () => {
    mocks.captureStart.mockImplementation(async (pcm, _ended, format) => { format(48000); pcm(new Uint8Array([1, 2])) })
    const wrapper = mountButton()
    await wrapper.get('button').trigger('focus'); await flushPromises()
    await start(wrapper)
    expect(mocks.streamCancel).toHaveBeenCalledOnce()
    expect(mocks.streamStart.mock.calls.at(-1)?.[1]).toBe(48000)
    expect(mocks.pcm).toHaveBeenLastCalledWith(new Uint8Array([1, 2]))
    wrapper.unmount()
  })

  it('discards a pending warmup when navigating and never opens its late connection', async () => {
    let complete!: (value: unknown) => void
    mocks.post.mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
    const wrapper = mountButton()
    await wrapper.get('button').trigger('focus'); await flushPromises()
    await wrapper.setProps({ disabled: true })
    complete({ data: { token: 'st-test' } }); await flushPromises()
    expect(mocks.streamStart).not.toHaveBeenCalled()
    expect(mocks.post.mock.calls[0]![2].signal.aborted).toBe(true)
    expect(mocks.captureStart).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('releases idle preparation when the page is hidden without acquiring the microphone', async () => {
    const wrapper = mountButton()
    await wrapper.get('button').trigger('focus'); await flushPromises()
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    document.dispatchEvent(new Event('visibilitychange'))
    expect(mocks.streamCancel).toHaveBeenCalledOnce()
    expect(mocks.post.mock.calls[0]![2].signal.aborted).toBe(true)
    expect(mocks.captureStart).not.toHaveBeenCalled()
    await wrapper.get('button').trigger('pointerenter'); await flushPromises()
    expect(mocks.post).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('releases standby on window blur and automatically prepares again on return', async () => {
    vi.useFakeTimers()
    const wrapper = mountButton(); await flushPromises()
    window.dispatchEvent(new Event('blur'))
    expect(mocks.streamCancel).toHaveBeenCalledOnce()
    const heartbeats = mocks.keepAlive.mock.calls.length
    await vi.advanceTimersByTimeAsync(5000)
    expect(mocks.keepAlive).toHaveBeenCalledTimes(heartbeats)
    window.dispatchEvent(new Event('focus')); await flushPromises()
    expect(mocks.streamStart).toHaveBeenCalledTimes(2)
    expect(mocks.post).toHaveBeenCalledOnce() // reuse an unexpired temporary credential
    expect(mocks.captureStart).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('automatically prepares the next recording while reusing a valid credential', async () => {
    vi.useFakeTimers()
    const wrapper = mountButton(); await start(wrapper)
    await wrapper.get('button').trigger('click'); await flushPromises()
    await vi.advanceTimersByTimeAsync(1)
    expect(mocks.streamStart).toHaveBeenCalledTimes(2)
    expect(mocks.post).toHaveBeenCalledOnce()
    expect(mocks.captureStart).toHaveBeenCalledOnce()
    await start(wrapper)
    expect(mocks.streamStart).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('refreshes expired credentials on foreground return and clears them on server changes', async () => {
    vi.useFakeTimers()
    const wrapper = mountButton(); await flushPromises()
    window.dispatchEvent(new Event('blur'))
    await vi.advanceTimersByTimeAsync(110000)
    window.dispatchEvent(new Event('focus')); await flushPromises()
    expect(mocks.post).toHaveBeenCalledTimes(2)
    window.dispatchEvent(new Event('sdd-server-changed'))
    await vi.advanceTimersByTimeAsync(1)
    expect(mocks.post).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })

  it('backs off for sixty seconds after credential rate limiting instead of spinning', async () => {
    vi.useFakeTimers()
    mocks.post.mockRejectedValueOnce({ response: { status: 429 } })
    const wrapper = mountButton(); await flushPromises()
    await vi.advanceTimersByTimeAsync(59999)
    expect(mocks.post).toHaveBeenCalledOnce()
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(mocks.post).toHaveBeenCalledTimes(2)
    expect(mocks.captureStart).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('can stop recording before connection completes and then finalize the buffered audio', async () => {
    let complete!: (value: unknown) => void
    mocks.post.mockImplementation(() => new Promise(resolve => { complete = resolve }))
    const wrapper = mountButton(); await start(wrapper)
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(mocks.captureStop).toHaveBeenCalledOnce()
    expect(mocks.streamFinish).not.toHaveBeenCalled()
    complete({ data: { token: 'st-test' } }); await flushPromises()
    expect(mocks.streamFinish).toHaveBeenCalledOnce()
    expect(wrapper.emitted('transcript')).toEqual([['识别结果']])
    wrapper.unmount()
  })

  function offlineBridge(ready = true) {
    vi.stubEnv('VITE_SPEECH_MODE', 'offline')
    const speech = { status: vi.fn().mockResolvedValue({ available: true, ready }), transcribe: vi.fn().mockResolvedValue({ text: '本地识别结果' }), cancel: vi.fn().mockResolvedValue(undefined) }
    window.sddDesktop = { speech } as any
    return speech
  }

  it('records offline through the desktop bridge without requesting API credentials', async () => {
    const speech = offlineBridge()
    const wrapper = mountButton(); await flushPromises(); await start(wrapper)
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(speech.transcribe).toHaveBeenCalledWith({ id: expect.any(String), wavBase64: 'wav' })
    expect(wrapper.emitted('transcript')).toEqual([['本地识别结果']])
    expect(mocks.post).not.toHaveBeenCalled()
    expect(mocks.streamStart).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('disables capture when offline runtime assets are missing', async () => {
    offlineBridge(false)
    const wrapper = mountButton(); await flushPromises()
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    expect(wrapper.get('button').attributes('title')).toContain('缺少离线语音资源')
    expect(mocks.captureStart).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('cancels the offline decoder on navigation and discards its late result', async () => {
    const speech = offlineBridge()
    let finish!: (value: { text: string }) => void
    speech.transcribe.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mountButton(); await flushPromises(); await start(wrapper)
    await wrapper.get('button').trigger('click'); await flushPromises()
    const id = speech.transcribe.mock.calls[0]![0].id
    await wrapper.setProps({ contextKey: 'task-b' })
    expect(speech.cancel).toHaveBeenCalledWith(id)
    finish({ text: '旧会话内容' }); await flushPromises()
    expect(wrapper.emitted('transcript')).toBeUndefined()
    expect(mocks.dispose).toHaveBeenCalled()
    expect(mocks.post).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('hides the entry in off mode and offline browser builds without requesting credentials', async () => {
    for (const mode of ['off', 'offline']) {
      vi.stubEnv('VITE_SPEECH_MODE', mode)
      const wrapper = mountButton(); await flushPromises()
      expect(wrapper.find('button').exists()).toBe(false)
      wrapper.unmount()
    }
    expect(mocks.post).not.toHaveBeenCalled()
  })

  it('sends only a transcript event after stop and task completion', async () => {
    const wrapper = mountButton(); await start(wrapper)
    expect(mocks.post).toHaveBeenCalledWith('/speech/sessions', null, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.emitted('transcript')).toBeUndefined()
    expect(wrapper.get('button').attributes('aria-pressed')).toBe('true')
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(wrapper.emitted('transcript')).toEqual([['识别结果']])
    expect(wrapper.emitted('busy')).toEqual([[true], [false]])
    wrapper.unmount()
  })

  it('cancels pending recognition on a context change and discards the late result', async () => {
    let finish!: (text: string) => void
    mocks.streamFinish.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mountButton(); await start(wrapper)
    await wrapper.get('button').trigger('click'); await flushPromises()
    await wrapper.setProps({ contextKey: 'task-b' })
    finish('旧会话结果'); await flushPromises()
    expect(wrapper.emitted('transcript')).toBeUndefined()
    expect(mocks.streamCancel).toHaveBeenCalled()
    expect(mocks.dispose).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('releases capture and aborts credential issuance when unmounted', async () => {
    let resolve!: (value: unknown) => void
    mocks.post.mockImplementation(() => new Promise(done => { resolve = done }))
    const wrapper = mountButton(); await start(wrapper)
    const signal = mocks.post.mock.calls[0]![2].signal as AbortSignal
    wrapper.unmount()
    expect(signal.aborted).toBe(true)
    resolve({ data: {} }); await flushPromises()
    expect(mocks.streamStart).not.toHaveBeenCalled()
    expect(mocks.dispose).toHaveBeenCalled()
  })

  it('shows microphone denial and recovers for a later recording', async () => {
    mocks.captureStart.mockRejectedValueOnce(new DOMException('denied', 'NotAllowedError'))
    const wrapper = mountButton(); await start(wrapper)
    expect(wrapper.get('[role="status"]').text()).toContain('无法访问麦克风')
    expect(mocks.post.mock.calls[0]![2].signal.aborted).toBe(true)
    await start(wrapper)
    expect(wrapper.get('button').attributes('aria-pressed')).toBe('true')
    await wrapper.setProps({ disabled: true })
    expect(mocks.dispose).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('automatically stops at sixty seconds', async () => {
    vi.useFakeTimers()
    const wrapper = mountButton()
    await wrapper.get('button').trigger('click'); await flushPromises()
    await vi.advanceTimersByTimeAsync(60000); await flushPromises()
    expect(mocks.captureStop).toHaveBeenCalledOnce()
    expect(wrapper.emitted('transcript')).toEqual([['识别结果']])
    wrapper.unmount()
  })
})
