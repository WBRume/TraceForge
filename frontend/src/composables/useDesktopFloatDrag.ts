import { onScopeDispose } from 'vue'
import type { DesktopFloatDrag, FloatPoint } from '@/types/taskFloat'

type Gesture = {
  handle: HTMLElement
  pointerId: number
  start: FloatPoint
  grab: FloatPoint
  moved: boolean
}

export function useDesktopFloatDrag(moveWindow: (request: DesktopFloatDrag) => Promise<void>, onError: () => void) {
  let gesture: Gesture | undefined
  let pending: DesktopFloatDrag | undefined
  let frame: number | undefined
  let moving = false
  let dropping = false

  function clearPointer() {
    const active = gesture
    if (!active) return
    gesture = undefined
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', drop)
    window.removeEventListener('pointercancel', cancel)
    active.handle.removeEventListener('lostpointercapture', cancel)
    if (active.handle.hasPointerCapture(active.pointerId)) active.handle.releasePointerCapture(active.pointerId)
  }

  function clearPending() {
    pending = undefined
    dropping = false
    if (frame !== undefined) cancelAnimationFrame(frame)
    frame = undefined
  }

  function cancel(event: PointerEvent) {
    if (event.pointerId !== gesture?.pointerId) return
    clearPointer()
    clearPending()
  }

  function schedule() {
    if (moving || !pending || frame !== undefined) return
    if (pending.dropped) {
      void flush()
      return
    }
    frame = requestAnimationFrame(() => {
      frame = undefined
      void flush()
    })
  }

  async function flush() {
    const request = pending
    if (!request || moving) return
    pending = undefined
    moving = true
    try {
      await moveWindow(request)
    } catch {
      clearPointer()
      clearPending()
      onError()
    } finally {
      moving = false
      if (request.dropped) dropping = false
      schedule()
    }
  }

  const movedEnough = (event: PointerEvent, active: Gesture) =>
    Math.hypot(event.screenX - active.start.x, event.screenY - active.start.y) >= 4

  function move(event: PointerEvent) {
    if (!gesture || event.pointerId !== gesture.pointerId) return
    gesture.moved ||= movedEnough(event, gesture)
    if (!gesture.moved) return
    pending = { grab: gesture.grab, dropped: false }
    schedule()
  }

  function drop(event: PointerEvent) {
    const active = gesture
    if (!active || event.pointerId !== active.pointerId) return
    clearPointer()
    if (!active.moved && !movedEnough(event, active)) return
    pending = { grab: active.grab, dropped: true }
    dropping = true
    if (frame !== undefined) cancelAnimationFrame(frame)
    frame = undefined
    schedule()
  }

  function start(event: PointerEvent) {
    if (gesture || dropping || event.button !== 0) return
    const handle = event.currentTarget as HTMLElement
    event.preventDefault()
    handle.setPointerCapture(event.pointerId)
    gesture = {
      handle, pointerId: event.pointerId,
      start: { x: event.screenX, y: event.screenY },
      grab: { x: event.clientX, y: event.clientY },
      moved: false,
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', drop)
    window.addEventListener('pointercancel', cancel)
    handle.addEventListener('lostpointercapture', cancel)
  }

  onScopeDispose(() => {
    clearPointer()
    clearPending()
  })
  return start
}
