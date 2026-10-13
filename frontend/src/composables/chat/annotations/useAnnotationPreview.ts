import { nextTick, onBeforeUnmount, onMounted, shallowRef, watch, type ShallowRef } from 'vue'

export function useAnnotationPreview(
  contextKey: () => string | undefined,
  itemCount: () => number,
  anchor: Readonly<ShallowRef<HTMLElement | null>>,
  panel: Readonly<ShallowRef<HTMLElement | null>>,
) {
  const expanded = shallowRef(false)
  const pinned = shallowRef(false)
  const position = shallowRef({ left: '8px', bottom: '0px', width: '384px', maxHeight: '320px' })
  let closeTimer: ReturnType<typeof setTimeout> | undefined

  function cancelClose() { clearTimeout(closeTimer); closeTimer = undefined }
  function close() { cancelClose(); expanded.value = false; pinned.value = false }
  function contains(target: EventTarget | null) {
    return target instanceof Node && Boolean(anchor.value?.contains(target) || panel.value?.contains(target))
  }
  function place() {
    const rect = anchor.value?.getBoundingClientRect()
    if (!expanded.value || !rect) return
    const width = Math.min(384, window.innerWidth - 16)
    position.value = {
      left: `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`,
      bottom: `${window.innerHeight - rect.top + 8}px`,
      width: `${width}px`,
      maxHeight: `${Math.max(0, Math.min(320, rect.top - 16))}px`,
    }
  }
  function enter(event?: PointerEvent) {
    if (event?.pointerType === 'touch') return
    cancelClose()
    expanded.value = true
  }
  function leave() {
    cancelClose()
    if (pinned.value) return
    closeTimer = setTimeout(() => { if (!contains(document.activeElement)) close() }, 180)
  }
  function toggle() {
    if (pinned.value) close()
    else { cancelClose(); pinned.value = true; expanded.value = true }
  }
  function outside(event: PointerEvent) { if (!contains(event.target)) close() }
  function focusOut(event: FocusEvent) { if (event.relatedTarget && !contains(event.relatedTarget)) close() }
  function keydown(event: KeyboardEvent) {
    if (event.key !== 'Escape' || !expanded.value) return
    event.stopPropagation()
    if (panel.value?.contains(document.activeElement)) anchor.value?.querySelector('button')?.focus()
    close()
  }
  watch(expanded, active => { if (active) void nextTick(place) })
  watch(contextKey, close)
  watch(itemCount, (next, previous) => { if (!next || next > previous) close() })
  onMounted(() => {
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', keydown)
    document.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
  })
  onBeforeUnmount(() => {
    cancelClose()
    document.removeEventListener('pointerdown', outside)
    document.removeEventListener('keydown', keydown)
    document.removeEventListener('scroll', place, true)
    window.removeEventListener('resize', place)
  })
  return { expanded, position, enter, leave, toggle, cancelClose, focusOut }
}
