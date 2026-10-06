import { describe, expect, it } from 'vitest'
import source from '../pcm-recorder.worklet.js?raw'

type Processor = {
  process(inputs: Float32Array[][]): boolean
  port: { onmessage: () => void }
}

function recorder(sampleRate: number) {
  const messages: (Float32Array | string)[] = []
  let create!: new () => Processor
  class AudioWorkletProcessor {
    port = { onmessage: () => {}, postMessage: (value: Float32Array | string) => messages.push(typeof value === 'string' ? value : value.slice()) }
  }
  new Function('AudioWorkletProcessor', 'registerProcessor', 'sampleRate', source)(
    AudioWorkletProcessor, (_name: string, constructor: new () => Processor) => { create = constructor }, sampleRate,
  )
  return { processor: new create(), messages }
}

describe('speech PCM capture', () => {
  it.each([16000, 44100, 48000])('sends 20 ms chunks at %i Hz and flushes the tail without losing or duplicating samples', rate => {
    const { processor, messages } = recorder(rate)
    const samples = Float32Array.from({ length: 4096 }, (_, index) => index / 4096)
    for (let offset = 0; offset < samples.length; offset += 128) {
      processor.process([[samples.slice(offset, offset + 128)]])
    }
    expect(messages.length).toBeGreaterThan(0)
    expect(messages.every(chunk => chunk.length === Math.round(rate * 0.02))).toBe(true)
    processor.port.onmessage()
    expect(messages.at(-1)).toBe('stopped')
    const captured = messages.filter((chunk): chunk is Float32Array => chunk instanceof Float32Array).flatMap(chunk => [...chunk])
    expect(captured).toEqual([...samples])
    expect(processor.process([[new Float32Array(128)]])).toBe(false)
  })
})
