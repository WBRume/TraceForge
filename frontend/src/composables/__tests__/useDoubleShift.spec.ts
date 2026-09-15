import { describe, it, expect, vi } from 'vitest'
import { createDoubleShiftHandler } from '../useDoubleShift'

describe('Double Shift', () => {
  const key = (name = 'Shift', extra: KeyboardEventInit = {}) => new KeyboardEvent('keydown', { key: name, ...extra })
  it('requires two complete presses and rejects repeat/long hold', () => {
    let time = 0
    const open = vi.fn()
    const h = createDoubleShiftHandler(open, () => time)
    h.keydown(key()); h.keyup(key()); time = 120; h.keydown(key()); h.keyup(key())
    expect(open).toHaveBeenCalledTimes(1)
    time = 1000; h.keydown(key()); time = 1800; h.keydown(key('Shift', { repeat: true })); h.keyup(key())
    time = 1900; h.keydown(key()); h.keyup(key())
    expect(open).toHaveBeenCalledTimes(1)
  })
  it('cancels shortcuts, pointers and IME', () => {
    const open = vi.fn()
    const h = createDoubleShiftHandler(open, () => 100)
    h.keydown(key()); h.keydown(key('a', { shiftKey: true })); h.keyup(key()); h.keydown(key()); h.keyup(key())
    expect(open).not.toHaveBeenCalled()
    h.reset(); h.keydown(key()); h.keyup(key()); h.reset(); h.keydown(key()); h.keyup(key())
    expect(open).not.toHaveBeenCalled()
    h.compositionstart(); h.keydown(key()); h.keyup(key()); h.keydown(key()); h.keyup(key())
    expect(open).not.toHaveBeenCalled()
  })
  it('does not trigger in text inputs', () => {
    const open = vi.fn()
    const h = createDoubleShiftHandler(open, () => 0)
    const input = document.createElement('input')
    const event = key()
    vi.spyOn(event, 'composedPath').mockReturnValue([input])
    h.keydown(event); h.keyup(event); h.keydown(event); h.keyup(event)
    expect(open).not.toHaveBeenCalled()
  })
})
