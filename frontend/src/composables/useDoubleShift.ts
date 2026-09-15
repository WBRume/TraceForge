import { onScopeDispose, watch, type Ref } from 'vue'

export function createDoubleShiftHandler(open: () => void, now = () => performance.now()) {
  let pressedAt = 0
  let first = -Infinity
  let pressed = false
  let composing = false
  const reset = () => { pressed = false; first = -Infinity }
  const editable = (event: KeyboardEvent) => event.composedPath().some(target => target instanceof HTMLElement &&
    (target.matches('input, textarea, select, [contenteditable="true"]') || !!target.closest('.monaco-editor, .cm-editor, [role="dialog"]')))
  const keydown = (event: KeyboardEvent) => {
    if (event.key !== 'Shift' || event.ctrlKey || event.altKey || event.metaKey || event.isComposing || composing || editable(event)) { reset(); return }
    if (event.repeat) return
    pressed = true
    pressedAt = now()
  }
  const keyup = (event: KeyboardEvent) => {
    if (event.key !== 'Shift' || !pressed || event.ctrlKey || event.altKey || event.metaKey || event.isComposing || composing || editable(event)) { reset(); return }
    pressed = false
    const stamp = now()
    if (stamp - pressedAt > 400) { reset(); return }
    if (stamp - first <= 400) { reset(); open() } else first = stamp
  }
  return { keydown, keyup, reset, compositionstart: () => { composing = true; reset() }, compositionend: () => { composing = false; reset() } }
}

export function useDoubleShift(enabled: Ref<boolean>, open: () => void) {
  const handler = createDoubleShiftHandler(open)
  const events = { keydown: handler.keydown, keyup: handler.keyup, blur: handler.reset,
    pointerdown: handler.reset, compositionstart: handler.compositionstart, compositionend: handler.compositionend }
  let cleanup = () => {}
  watch(enabled, value => {
    cleanup()
    if (!value) return
    for (const [name, fn] of Object.entries(events)) window.addEventListener(name, fn as EventListener, true)
    document.addEventListener('visibilitychange', handler.reset)
    cleanup = () => {
      for (const [name, fn] of Object.entries(events)) window.removeEventListener(name, fn as EventListener, true)
      document.removeEventListener('visibilitychange', handler.reset)
      handler.reset()
    }
  }, { immediate: true })
  onScopeDispose(() => cleanup())
}
