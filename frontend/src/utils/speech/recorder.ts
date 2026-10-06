import workletSource from './pcm-recorder.worklet.js?raw'

export function encodePcm(samples: Float32Array): Uint8Array<ArrayBuffer> {
  const bytes = new Uint8Array(samples.length * 2)
  const view = new DataView(bytes.buffer)
  samples.forEach((sample, i) => {
    const clamped = Math.max(-1, Math.min(1, sample))
    view.setInt16(i * 2, Math.round(clamped * (clamped < 0 ? 32768 : 32767)), true)
  })
  return bytes
}

export function encodeWav(samples: Float32Array): string {
  const bytes = new Uint8Array(44 + samples.length * 2)
  const view = new DataView(bytes.buffer)
  const ascii = (offset: number, value: string) => [...value].forEach((char, i) => view.setUint8(offset + i, char.charCodeAt(0)))
  ascii(0, 'RIFF'); view.setUint32(4, bytes.length - 8, true); ascii(8, 'WAVEfmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true)
  view.setUint16(32, 2, true); view.setUint16(34, 16, true)
  ascii(36, 'data'); view.setUint32(40, samples.length * 2, true)
  bytes.set(encodePcm(samples), 44)
  let binary = ''
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
  return btoa(binary)
}

export class SpeechRecorder {
  private stream?: MediaStream
  private context?: AudioContext
  private source?: MediaStreamAudioSourceNode
  private node?: AudioWorkletNode
  private chunks: Float32Array[] = []
  private count = 0
  private canceled = false
  private flush?: () => void
  private onPcm?: (pcm: Uint8Array) => void

  async start(onPcm?: (pcm: Uint8Array) => void, onEnded?: () => void, onFormat?: (sampleRate: number) => void, onLevel?: (level: number) => void) {
    this.onPcm = onPcm
    if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === 'undefined') throw new Error('unsupported')
    try {
      const context = new AudioContext({ sampleRate: 16000, latencyHint: 'interactive' })
      this.context = context
      onFormat?.(context.sampleRate)
      // Start device acquisition, AudioContext resume and worklet loading in the same
      // click gesture. None needs to wait for the others or the cloud connection.
      const microphone = navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false }).then(stream => {
        if (this.canceled) { stream.getTracks().forEach(track => track.stop()); return stream }
        this.stream = stream
        for (const track of stream.getAudioTracks()) track.addEventListener('ended', () => { if (!this.canceled) onEnded?.() }, { once: true })
        return stream
      })
      const url = URL.createObjectURL(new Blob([workletSource], { type: 'text/javascript' }))
      const module = context.audioWorklet.addModule(url).finally(() => URL.revokeObjectURL(url))
      const [stream] = await Promise.all([microphone, context.resume(), module])
      if (this.canceled) { this.dispose(); return }
      this.node = new AudioWorkletNode(context, 'traceforge-pcm-recorder')
      this.node.port.onmessage = event => {
        if (event.data === 'stopped') { this.flush?.(); return }
        if (this.canceled || !(event.data instanceof Float32Array)) return
        const chunk = event.data.subarray(0, Math.max(0, context.sampleRate * 60 - this.count))
        if (!chunk.length) return
        if (onLevel) {
          let energy = 0
          for (const sample of chunk) energy += sample * sample
          onLevel(Math.min(1, Math.sqrt(energy / chunk.length) * 5))
        }
        if (this.onPcm) this.onPcm(encodePcm(chunk))
        else this.chunks.push(chunk)
        this.count += chunk.length
      }
      this.source = context.createMediaStreamSource(stream)
      this.source.connect(this.node)
      this.node.connect(context.destination) // Worklet outputs silence, never microphone monitoring.
    } catch (error) { this.dispose(); throw error }
  }

  async stop(): Promise<string> {
    const rate = this.context?.sampleRate || 16000
    try {
      if (this.node) await new Promise<void>(resolve => {
        const timeout = window.setTimeout(resolve, 500)
        this.flush = () => { window.clearTimeout(timeout); resolve() }
        this.node!.port.postMessage('stop')
      })
      const samples = new Float32Array(this.onPcm ? 0 : this.count)
      let offset = 0
      for (const chunk of this.chunks) { samples.set(chunk, offset); offset += chunk.length }
      this.releaseAudio()
      if (this.canceled) throw new Error('canceled')
      if (this.count < rate / 10) throw new Error('too_short')
      if (this.onPcm) return ''
      if (rate === 16000) return encodeWav(samples)
      // Let Web Audio apply its resampling filter when a device ignores 16 kHz.
      const offline = new OfflineAudioContext(1, Math.min(960000, Math.floor(samples.length * 16000 / rate)), 16000)
      const buffer = offline.createBuffer(1, samples.length, rate)
      buffer.copyToChannel(samples, 0)
      const source = offline.createBufferSource()
      source.buffer = buffer; source.connect(offline.destination); source.start()
      return encodeWav((await offline.startRendering()).getChannelData(0))
    } finally { this.dispose() }
  }

  private releaseAudio() {
    this.stream?.getTracks().forEach(track => track.stop())
    this.source?.disconnect()
    this.node?.disconnect()
    if (this.node) this.node.port.close()
    if (this.context && this.context.state !== 'closed') void this.context.close().catch(() => {})
    this.stream = undefined; this.source = undefined; this.node = undefined; this.context = undefined
  }

  dispose() {
    this.canceled = true
    this.flush?.()
    this.releaseAudio()
    this.chunks = []
    this.count = 0
  }
}
