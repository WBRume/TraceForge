class PcmRecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    // Send 20 ms at the actual device rate, including when it ignores 16 kHz.
    this.buffer = new Float32Array(Math.round(sampleRate * 0.02))
    this.offset = 0
    this.stopped = false
    this.port.onmessage = () => {
      this.stopped = true
      if (this.offset) this.port.postMessage(this.buffer.slice(0, this.offset))
      this.port.postMessage('stopped')
    }
  }
  process(inputs) {
    if (this.stopped) return false
    const channels = inputs[0]
    if (!channels?.length) return true
    for (let i = 0; i < channels[0].length; i++) {
      let value = 0
      for (const channel of channels) value += channel[i] / channels.length
      this.buffer[this.offset++] = value
      if (this.offset === this.buffer.length) {
        this.port.postMessage(this.buffer)
        this.offset = 0
      }
    }
    return true
  }
}
registerProcessor('traceforge-pcm-recorder', PcmRecorderProcessor)
