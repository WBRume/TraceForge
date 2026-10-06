import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QwenSpeechStream } from '../qwen'

class Socket {
  static OPEN = 1
  static CONNECTING = 0
  static instances: Socket[] = []
  readyState = 0
  bufferedAmount = 0
  url: string
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  send = vi.fn()
  close = vi.fn(() => { this.readyState = 3 })
  constructor(url: string) { this.url = url; Socket.instances.push(this) }
  open() { this.readyState = 1; this.onopen?.() }
  event(event: string, payload = {}, taskId?: string) {
    const id = taskId || JSON.parse(this.send.mock.calls[0]![0]).header.task_id
    this.onmessage?.({ data: JSON.stringify({ header: { event, task_id: id }, payload }) })
  }
}
const credentials = () => ({ token: 'st-temporary', expires_at: Math.floor(Date.now() / 1000) + 120,
  websocket_url: 'wss://dashscope.aliyuncs.com/api-ws/v1/inference', model: 'qwen-audio-3.1-asr-flash-streaming' })

beforeEach(() => { Socket.instances = []; vi.stubGlobal('WebSocket', Socket) })
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

describe('Qwen duplex speech', () => {
  it('waits for task-started, deduplicates interim/final sentences and waits for task-finished', async () => {
    const preview = vi.fn(); const failure = vi.fn()
    const stream = new QwenSpeechStream(preview, failure)
    const ready = stream.start(credentials(), 16000)
    const socket = Socket.instances[0]!
    expect(new URL(socket.url).searchParams.get('api_key')).toBe('st-temporary')
    socket.open()
    expect(JSON.parse(socket.send.mock.calls[0]![0]).payload).toMatchObject({ model: credentials().model,
      parameters: { format: 'pcm', sample_rate: 16000, semantic_punctuation_enabled: false, max_sentence_silence: 600 } })
    const buffered = new Uint8Array([2, 3])
    stream.sendPcm(buffered)
    expect(socket.send).toHaveBeenCalledOnce() // run-task only until the server is ready
    socket.event('task-started'); await ready
    expect(socket.send).toHaveBeenLastCalledWith(buffered)
    stream.sendPcm(new Uint8Array([0, 1]))
    const result = (id: number, text: string, end: boolean) => socket.event('result-generated', { output: { sentence: { sentence_id: id, text, sentence_end: end } } })
    result(1, '你', false); result(1, '你好。', true); result(1, '你', false)
    result(2, '世界。', true); result(2, '世界。', true)
    expect(preview).toHaveBeenLastCalledWith('你好。世界。')
    const completed = stream.finish()
    expect(JSON.parse(socket.send.mock.calls.at(-1)![0]).header.action).toBe('finish-task')
    socket.event('task-finished')
    await expect(completed).resolves.toBe('你好。世界。')
    expect(socket.close).toHaveBeenCalledOnce(); expect(failure).not.toHaveBeenCalled()
  })

  it('rejects permanent keys, expired credentials and unexpected hosts before connecting', async () => {
    for (const change of [{ token: 'sk-never-send' }, { expires_at: 1 }, { websocket_url: 'wss://untrusted.example/api-ws/v1/inference' }]) {
      const stream = new QwenSpeechStream(vi.fn(), vi.fn())
      await expect(stream.start({ ...credentials(), ...change }, 16000)).rejects.toThrow('Invalid speech session')
      stream.cancel()
    }
    expect(Socket.instances).toHaveLength(0)
  })

  it('bounds queued audio when the connection cannot keep up', async () => {
    const failure = vi.fn(); const stream = new QwenSpeechStream(vi.fn(), failure)
    const ready = stream.start(credentials(), 16000); const socket = Socket.instances[0]!
    socket.open(); socket.event('task-started'); await ready
    socket.bufferedAmount = 256001
    stream.sendPcm(new Uint8Array(16000 * 2 * 20 + 1))
    await expect(stream.finish()).rejects.toThrow('too slow')
    expect(failure).toHaveBeenCalledOnce()
  })

  it('drains captured audio in order before finish-task and drops buffered audio on cancellation', async () => {
    vi.useFakeTimers()
    const stream = new QwenSpeechStream(vi.fn(), vi.fn())
    const first = new Uint8Array([1, 2]); const second = new Uint8Array([3, 4])
    stream.sendPcm(first) // recording can begin before credentials arrive
    const ready = stream.start(credentials(), 16000); const socket = Socket.instances[0]!
    socket.open(); socket.bufferedAmount = 256001
    socket.event('task-started'); await ready
    stream.sendPcm(second)
    const finished = stream.finish()
    expect(socket.send).toHaveBeenCalledOnce()
    socket.bufferedAmount = 0
    await vi.advanceTimersByTimeAsync(25)
    expect(socket.send.mock.calls.slice(1, 3).map(call => call[0])).toEqual([first, second])
    expect(JSON.parse(socket.send.mock.calls.at(-1)![0]).header.action).toBe('finish-task')
    socket.event('task-finished'); await finished
    const canceled = new QwenSpeechStream(vi.fn(), vi.fn())
    canceled.sendPcm(first); canceled.cancel()
    await expect(canceled.start(credentials(), 16000)).rejects.toThrow('canceled')
    expect(Socket.instances).toHaveLength(1)
  })

  it('cancels a connection still opening and times out a missing task-started event', async () => {
    vi.useFakeTimers()
    const stream = new QwenSpeechStream(vi.fn(), vi.fn())
    const ready = stream.start(credentials(), 16000)
    const rejected = expect(ready).rejects.toThrow('timed out')
    await vi.advanceTimersByTimeAsync(15000); await rejected
    Socket.instances[0]!.open()
    expect(Socket.instances[0]!.close).toHaveBeenCalledOnce()
  })

  it('gives capture a full recording deadline after time spent in standby', async () => {
    vi.useFakeTimers()
    const failure = vi.fn()
    const stream = new QwenSpeechStream(vi.fn(), failure)
    const ready = stream.start(credentials(), 16000); const socket = Socket.instances[0]!
    socket.open(); socket.event('task-started'); await ready
    await vi.advanceTimersByTimeAsync(14000)
    stream.beginCapture()
    await vi.advanceTimersByTimeAsync(62000)
    expect(failure).not.toHaveBeenCalled()
    const finished = stream.finish()
    socket.event('task-finished')
    await expect(finished).resolves.toBe('')
  })

  it('keeps an idle task alive with bounded synthetic silence and stops sending after cancel', async () => {
    vi.useFakeTimers()
    const failure = vi.fn()
    const stream = new QwenSpeechStream(vi.fn(), failure)
    const ready = stream.start(credentials(), 16000); const socket = Socket.instances[0]!
    stream.keepAlive()
    expect(socket.send).not.toHaveBeenCalled()
    socket.open(); socket.event('task-started'); await ready
    for (let index = 0; index < 90; index++) { stream.keepAlive(); await vi.advanceTimersByTimeAsync(1000) }
    expect(failure).not.toHaveBeenCalled()
    const silence = socket.send.mock.calls.at(-1)![0]
    expect(silence).toBeInstanceOf(Uint8Array)
    expect(silence.byteLength).toBe(3200)
    expect(silence.every((byte: number) => byte === 0)).toBe(true)
    stream.cancel(); const count = socket.send.mock.calls.length
    stream.keepAlive()
    expect(socket.send).toHaveBeenCalledTimes(count)
  })
})
