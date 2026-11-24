import { onScopeDispose, shallowRef } from 'vue'
import type { DesktopWorkspaceWindowsApi, TabDestination } from '@/types/workspaceWindows'

const WINDOW_DRAG_HOLD_MS = 350
const DRAG_THRESHOLD = 7

export function useDesktopTabDrag(
  api: Pick<DesktopWorkspaceWindowsApi, 'drag' | 'moveWindow' | 'onDropHint'>,
  move: (id: string, destination: TabDestination) => void,
  onError: (error: unknown) => void,
) {
  const draggingId = shallowRef<string>()
  const windowGrip = shallowRef<string>()
  const hint = shallowRef<{ beforeTabId?: string } | null>(null)
  const unsubscribe = api.onDropHint(value => { hint.value = value })
  let pointer: { id: number; tabId: string; x: number; y: number; target: HTMLElement; kind?: 'tab' | 'window' } | undefined
  let pending: Promise<unknown> | undefined
  let holdTimer: ReturnType<typeof setTimeout> | undefined
  let nextPreview = 0
  let trackPreview: ReturnType<typeof setInterval> | undefined
  let suppressClick: string | undefined

  function start(event: PointerEvent, tabId: string) {
    if (event.button !== 0 || !event.isPrimary || pointer) return
    const target = event.currentTarget as HTMLElement
    suppressClick = undefined
    pointer = { id: event.pointerId, tabId, x: event.clientX, y: event.clientY, target }
    target.setPointerCapture(event.pointerId)
    holdTimer = setTimeout(() => { windowGrip.value = tabId }, WINDOW_DRAG_HOLD_MS)
  }

  function preview() {
    if (!pointer || !draggingId.value || pending || performance.now() < nextPreview) return
    nextPreview = performance.now() + 32
    pending = api.drag(pointer.tabId, 'preview').catch(onError).finally(() => { pending = undefined })
  }

  function update(event: PointerEvent) {
    const gesture = pointer
    if (gesture?.id !== event.pointerId) return
    if (!gesture.kind) {
      if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) < DRAG_THRESHOLD) return
      clearTimeout(holdTimer)
      gesture.kind = windowGrip.value ? 'window' : 'tab'
      if (gesture.kind === 'tab') {
        draggingId.value = gesture.tabId
        // Native cursor updates can continue while the pointer is over another window.
        trackPreview = setInterval(preview, 64)
      }
    }

    if (gesture.kind === 'tab') preview()
    else if (!pending) pending = api.moveWindow({ x: gesture.x, y: gesture.y }).catch(onError).finally(() => { pending = undefined })
  }

  async function finish(dropped: boolean, event?: PointerEvent) {
    const gesture = pointer
    if (!gesture || (event && gesture.id !== event.pointerId)) return
    pointer = undefined
    clearTimeout(holdTimer)
    clearInterval(trackPreview)
    windowGrip.value = undefined
    if (gesture.target.hasPointerCapture(gesture.id)) gesture.target.releasePointerCapture(gesture.id)
    if (!gesture.kind) return
    suppressClick = gesture.tabId
    if (gesture.kind === 'window') return
    draggingId.value = undefined
    hint.value = null
    try {
      await pending
      const destination = await api.drag(gesture.tabId, dropped ? 'drop' : 'cancel')
      if (destination) move(gesture.tabId, destination)
    } catch (error) {
      onError(error)
    }
  }

  function escape(event: KeyboardEvent) {
    if (event.key !== 'Escape' || (!draggingId.value && !windowGrip.value)) return
    event.preventDefault()
    void finish(false)
  }

  window.addEventListener('keydown', escape)
  onScopeDispose(() => {
    window.removeEventListener('keydown', escape)
    void finish(false)
    unsubscribe()
  })

  return {
    draggingId, windowGrip, hint, start, update, finish,
    wasDragged(id: string) {
      if (suppressClick !== id) return false
      suppressClick = undefined
      return true
    },
  }
}
