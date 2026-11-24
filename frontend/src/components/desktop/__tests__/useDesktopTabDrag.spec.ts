import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DesktopWorkspaceWindowsApi } from '@/types/workspaceWindows'
import { useDesktopTabDrag } from '../useDesktopTabDrag'

const capture = { setPointerCapture: vi.fn(), hasPointerCapture: () => true, releasePointerCapture: vi.fn() }
const pointer = (x: number, y: number) => ({
  clientX: x, clientY: y, pointerId: 1, isPrimary: true, button: 0, currentTarget: capture,
}) as unknown as PointerEvent

function fixture() {
  const drag = vi.fn<DesktopWorkspaceWindowsApi['drag']>().mockResolvedValue({ position: { x: 30, y: 40 } })
  const moveWindow = vi.fn<DesktopWorkspaceWindowsApi['moveWindow']>().mockResolvedValue(undefined)
  const moveTab = vi.fn()
  const effects = effectScope()
  const gesture = effects.run(() => useDesktopTabDrag({ drag, moveWindow, onDropHint: () => () => {} }, moveTab, vi.fn()))!
  return { gesture, drag, moveWindow, moveTab, stop: () => effects.stop() }
}

describe('desktop tab and window dragging', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('keeps a drag that starts immediately in the tab strip', async () => {
    const { gesture, drag, moveWindow, moveTab, stop } = fixture()
    gesture.start(pointer(50, 20), 'tab')
    gesture.update(pointer(60, 20))
    vi.advanceTimersByTime(450)
    await gesture.finish(true, pointer(60, 20))
    expect(drag).toHaveBeenCalledWith('tab', 'drop')
    expect(moveTab).toHaveBeenCalledWith('tab', { position: { x: 30, y: 40 } })
    expect(moveWindow).not.toHaveBeenCalled()
    expect(gesture.wasDragged('tab')).toBe(true)
    stop()
  })

  it('uses the original grab point to move the window after a hold', async () => {
    const { gesture, drag, moveWindow, moveTab, stop } = fixture()
    gesture.start(pointer(50, 20), 'tab')
    vi.advanceTimersByTime(400)
    expect(gesture.windowGrip.value).toBe('tab')
    gesture.update(pointer(60, 27))
    await gesture.finish(true, pointer(60, 27))
    expect(moveWindow).toHaveBeenCalledWith({ x: 50, y: 20 })
    expect(drag).not.toHaveBeenCalled()
    expect(moveTab).not.toHaveBeenCalled()
    expect(gesture.wasDragged('tab')).toBe(true)
    stop()
  })

  it('keeps a stationary hold selectable and clears the drag state on release', async () => {
    const { gesture, moveWindow, stop } = fixture()
    gesture.start(pointer(50, 20), 'tab')
    vi.advanceTimersByTime(400)
    await gesture.finish(true, pointer(51, 20))
    expect(moveWindow).not.toHaveBeenCalled()
    expect(gesture.windowGrip.value).toBeUndefined()
    expect(gesture.wasDragged('tab')).toBe(false)
    stop()
  })
})
