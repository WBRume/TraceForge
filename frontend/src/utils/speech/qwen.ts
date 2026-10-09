import type { SpeechSession, SpeechStream } from './types'
export type { SpeechSession } from './types'
type Sentence = { text: string; final: boolean }

/** One duplex ASR task. Only temporary credentials are accepted. */
export class QwenSpeechStream implements SpeechStream {
  private socket?: WebSocket
  private readonly taskId = crypto.randomUUID()
  private readonly sentences = new Map<number, Sentence>()
  private started = false
  private finishing = false
  private closed = false
  private pendingPcm: Uint8Array[] = []
  private pendingBytes = 0
  private maxPendingBytes = 16000 * 2 * 20
  private silence = new Uint8Array(3200)
  private drainTimer?: number
  private finishSent = false
  private timer?: number
  private readyResolve?: () => void
  private readyReject?: (error: Error) => void
  private doneResolve?: (text: string) => void
  private doneReject?: (error: Error) => void
  private readonly result: Promise<string>
  private readonly preview: (text: string) => void
  private readonly onFailure: (error: Error) => void

  constructor(preview: (text: string) => void, onFailure: (error: Error) => void) {
    this.preview = preview; this.onFailure = onFailure
    this.result = new Promise((resolve, reject) => { this.doneResolve = resolve; this.doneReject = reject })
    void this.result.catch(() => {}) // Failure may arrive while still recording.
  }

  async start(session: SpeechSession, sampleRate: number): Promise<void> {
    if (this.closed) throw new Error('canceled')
    const endpoint = new URL(session.websocket_url)
    if (endpoint.protocol !== 'wss:' || !['dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com'].includes(endpoint.hostname)
      || endpoint.pathname !== '/api-ws/v1/inference' || endpoint.port || endpoint.username || endpoint.password
      || !session.token.startsWith('st-') || session.expires_at * 1000 <= Date.now()
      || (session.provider !== undefined && session.provider !== 'bailian')
      || typeof session.model !== 'string' || !session.model.trim() || session.model.length > 200) throw new Error('Invalid speech session')
    endpoint.search = ''
    endpoint.searchParams.set('api_key', session.token)
    const socket = new WebSocket(endpoint.href)
    this.maxPendingBytes = sampleRate * 2 * 20
    this.silence = new Uint8Array(Math.round(sampleRate / 10) * 2)
    this.socket = socket
    const ready = new Promise<void>((resolve, reject) => { this.readyResolve = resolve; this.readyReject = reject })
    this.deadline(15000)
    socket.onopen = () => {
      if (this.closed) return
      this.send({ header: { action: 'run-task', task_id: this.taskId, streaming: 'duplex' }, payload: {
        task_group: 'audio', task: 'asr', function: 'recognition', model: session.model,
        parameters: { format: 'pcm', sample_rate: sampleRate, heartbeat: true,
          semantic_punctuation_enabled: false, max_sentence_silence: 600 }, input: {},
      } })
    }
    socket.onmessage = event => this.receive(event.data)
    socket.onerror = () => this.fail(new Error('Speech connection failed'))
    socket.onclose = () => { if (!this.closed) this.fail(new Error('Speech connection closed before completion')) }
    return ready
  }

  sendPcm(pcm: Uint8Array) {
    if (this.finishing || this.closed) throw new Error('Speech stream is not ready')
    // Capture begins immediately; hold a bounded amount until task-started.
    if (this.pendingBytes + pcm.byteLength > this.maxPendingBytes) {
      this.fail(new Error('Speech connection is too slow')); return
    }
    this.pendingPcm.push(pcm); this.pendingBytes += pcm.byteLength
    this.drain()
  }

  beginCapture() {
    // Standby time must not consume the user's recording deadline or transcript.
    this.sentences.clear()
    if (this.started && !this.closed) this.deadline(75000)
  }

  keepAlive() {
    if (!this.started || this.closed || this.finishing) return
    this.deadline(75000)
    this.sendPcm(this.silence)
  }

  finish(): Promise<string> {
    if (this.closed) return this.result
    if (!this.started) { this.fail(new Error('Speech stream is not ready')); return this.result }
    this.finishing = true
    this.deadline(15000)
    this.drain()
    return this.result
  }

  private drain() {
    window.clearTimeout(this.drainTimer)
    if (!this.started || this.closed || !this.socket) return
    try {
      while (this.pendingPcm.length && this.socket.bufferedAmount < 256000) {
        const pcm = this.pendingPcm.shift()!
        this.pendingBytes -= pcm.byteLength
        this.socket.send(pcm as Uint8Array<ArrayBuffer>)
      }
      if (this.pendingPcm.length) this.drainTimer = window.setTimeout(() => this.drain(), 25)
      else if (this.finishing && !this.finishSent) {
        this.finishSent = true
        this.send({ header: { action: 'finish-task', task_id: this.taskId, streaming: 'duplex' }, payload: { input: {} } })
      }
    } catch { this.fail(new Error('Speech connection failed')) }
  }

  cancel() {
    if (this.closed) return
    this.readyReject?.(new Error('canceled')); this.doneReject?.(new Error('canceled'))
    this.close()
  }

  private transcript(finalOnly = false) {
    return [...this.sentences.entries()].sort(([a], [b]) => a - b)
      .filter(([, value]) => !finalOnly || value.final).map(([, value]) => value.text).join('')
  }

  private receive(raw: unknown) {
    if (this.closed || typeof raw !== 'string') return
    try {
      const event = JSON.parse(raw)
      if (event.header?.task_id !== this.taskId) return
      switch (event.header?.event) {
        case 'task-started':
          this.started = true; this.deadline(75000); this.drain(); this.readyResolve?.(); break
        case 'result-generated': {
          const sentence = event.payload?.output?.sentence
          if (!sentence || sentence.heartbeat || typeof sentence.text !== 'string') break
          const id = sentence.sentence_id ?? sentence.begin_time
          if (typeof id !== 'number') break
          // Late interim packets must not replace a confirmed sentence.
          if (!this.sentences.get(id)?.final) this.sentences.set(id, { text: sentence.text, final: sentence.sentence_end === true })
          this.preview(this.transcript()); break
        }
        case 'task-finished':
          if (!this.finishing) { this.fail(new Error('Speech task ended unexpectedly')); break }
          this.doneResolve?.(this.transcript(true).trim()); this.close(); break
        case 'task-failed': this.fail(new Error('Bailian speech recognition failed')); break
      }
    } catch { this.fail(new Error('Invalid speech response')) }
  }

  private send(message: unknown) {
    try { this.socket!.send(JSON.stringify(message)) } catch { this.fail(new Error('Speech connection failed')) }
  }
  private deadline(ms: number) {
    window.clearTimeout(this.timer)
    this.timer = window.setTimeout(() => this.fail(new Error('Speech request timed out')), ms)
  }
  private fail(error: Error) {
    if (this.closed) return
    this.readyReject?.(error); this.doneReject?.(error); this.close(); this.onFailure(error)
  }
  private close() {
    this.closed = true; window.clearTimeout(this.timer)
    window.clearTimeout(this.drainTimer); this.pendingPcm = []; this.pendingBytes = 0
    const socket = this.socket
    if (socket) {
      socket.onopen = null; socket.onmessage = null; socket.onerror = null; socket.onclose = null
      if (socket.readyState === WebSocket.CONNECTING) socket.onopen = () => socket.close()
      else if (socket.readyState === WebSocket.OPEN) socket.close()
    }
    this.sentences.clear()
  }
}
