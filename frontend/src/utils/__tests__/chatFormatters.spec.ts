import { describe, expect, it } from 'vitest'
import { formatElapsedDuration, formatTime, formatToolInput } from '@/utils/chatFormatters'

describe('formatElapsedDuration', () => {
  it('formats seconds as mm:ss', () => {
    expect(formatElapsedDuration(0)).toBe('0:00')
    expect(formatElapsedDuration(5)).toBe('0:05')
    expect(formatElapsedDuration(59)).toBe('0:59')
    expect(formatElapsedDuration(60)).toBe('1:00')
    expect(formatElapsedDuration(252)).toBe('4:12')
    expect(formatElapsedDuration(3599)).toBe('59:59')
  })

  it('formats hours as hh:mm:ss', () => {
    expect(formatElapsedDuration(3600)).toBe('1:00:00')
    expect(formatElapsedDuration(3661)).toBe('1:01:01')
    expect(formatElapsedDuration(7200 + 754)).toBe('2:12:34')
  })

  it('clamps negative / NaN / float inputs', () => {
    expect(formatElapsedDuration(-10)).toBe('0:00')
    expect(formatElapsedDuration(Number.NaN)).toBe('0:00')
    expect(formatElapsedDuration(4.9)).toBe('0:04')
  })
})

describe('existing chat formatters', () => {
  it('keeps formatTime and formatToolInput behavior', () => {
    expect(formatTime('')).toBe('')
    expect(formatToolInput('text')).toBe('text')
    expect(formatToolInput(undefined)).toBe('')
    expect(JSON.parse(formatToolInput({ a: 1 }))).toEqual({ a: 1 })
  })
})