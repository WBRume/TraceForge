import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch, type Ref } from 'vue'

/** A shared position for the collapsed handle and expanded background-job panel. */
export function useFloatingPosition(element: Ref<HTMLElement | null>) {
  const key = 'backgroundJobsPosition'
  const position = ref({ right: 20, bottom: 120 })
  const dragging = shallowRef(false)
  let start: { x: number; y: number; right: number; bottom: number; pointerId: number } | null = null
  let suppressClick = false
  let observer: ResizeObserver | undefined
  try {
    const saved = JSON.parse(localStorage.getItem(key) || 'null')
    if (Number.isFinite(saved?.right) && Number.isFinite(saved?.bottom)) position.value = saved
  } catch { /* Use the default position when storage is invalid. */ }
  const clamp = () => {
    const rect = element.value?.getBoundingClientRect()
    position.value = {
      right: Math.max(8, Math.min(position.value.right, Math.max(8, window.innerWidth - (rect?.width || 280) - 8))),
      bottom: Math.max(8, Math.min(position.value.bottom, Math.max(8, window.innerHeight - (rect?.height || 40) - 8))),
    }
  }
  const move = (event: PointerEvent) => {
    if (!start || event.pointerId !== start.pointerId) return
    const dx = event.clientX - start.x
    const dy = event.clientY - start.y
    if (!dragging.value && Math.hypot(dx, dy) < 4) return
    dragging.value = true
    suppressClick = true
    position.value = { right: start.right - dx, bottom: start.bottom - dy }
    clamp()
  }
  const end = () => {
    if (start) localStorage.setItem(key, JSON.stringify(position.value))
    start = null
    dragging.value = false
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', end)
    window.removeEventListener('pointercancel', end)
  }
  const startDrag = (event: PointerEvent) => {
    if (event.button !== 0) return
    if (event.currentTarget !== (event.target as HTMLElement).closest('button')
      && (event.target as HTMLElement).closest('button')) return
    suppressClick = false
    start = { x: event.clientX, y: event.clientY, ...position.value, pointerId: event.pointerId }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
  }
  const consumeDragClick = (event: MouseEvent) => {
    if (!suppressClick) return
    event.preventDefault()
    event.stopPropagation()
    suppressClick = false
  }
  onMounted(() => {
    window.addEventListener('resize', clamp)
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(clamp)
      if (element.value) observer.observe(element.value)
    }
    void nextTick(clamp)
  })
  watch(element, (current, previous) => {
    if (previous) observer?.unobserve(previous)
    if (current) observer?.observe(current)
    void nextTick(clamp)
  })
  onUnmounted(() => { end(); observer?.disconnect(); window.removeEventListener('resize', clamp) })
  return { style: computed(() => ({ right: `${position.value.right}px`, bottom: `${position.value.bottom}px` })),
    dragging, startDrag, consumeDragClick, clamp }
}
