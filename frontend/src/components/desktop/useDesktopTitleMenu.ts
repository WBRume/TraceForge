import { computed, onScopeDispose, readonly, shallowRef, useTemplateRef, watch } from 'vue'

export interface UseDesktopTitleMenuOptions {
  panelWidth: number
  offset?: number
  onOpen?: () => void
  onClose?: () => void
}

/**
 * 桌面标题栏弹出菜单的公共定位与生命周期控制。
 * 使用 fixed 定位并按当前视口宽度自动夹紧左右边界，避免在窄窗口下溢出。
 */
export function useDesktopTitleMenu(options: UseDesktopTitleMenuOptions) {
  const trigger = useTemplateRef<HTMLButtonElement>('trigger')
  const panel = useTemplateRef<HTMLElement>('panel')
  const open = shallowRef(false)
  const position = shallowRef({ left: 8, top: 48, maxHeight: 420 })

  const panelStyle = computed(() => ({
    left: `${position.value.left}px`,
    top: `${position.value.top}px`,
    '--desktop-menu-width': `${options.panelWidth}px`,
    '--desktop-menu-max-height': `${position.value.maxHeight}px`,
  }))

  function updatePosition() {
    const button = trigger.value
    if (!button) return
    const rect = button.getBoundingClientRect()
    const margin = 12
    const offset = options.offset ?? 6
    const maxAllowedWidth = Math.max(200, window.innerWidth - margin * 2)
    const width = Math.min(options.panelWidth, maxAllowedWidth)
    const left = Math.max(margin, Math.min(Math.round(rect.left), window.innerWidth - width - margin))
    const top = Math.round(rect.bottom + offset)
    const maxHeight = Math.max(180, window.innerHeight - top - 16)
    position.value = { left, top, maxHeight }
  }

  function openMenu() {
    updatePosition()
    if (open.value) return
    open.value = true
    options.onOpen?.()
  }

  function closeMenu(restoreFocus = false) {
    if (!open.value) return
    open.value = false
    options.onClose?.()
    if (restoreFocus) trigger.value?.focus({ preventScroll: true })
  }

  function toggleMenu() {
    if (open.value) closeMenu()
    else openMenu()
  }

  function onPointerDown(event: PointerEvent) {
    const target = event.target as Node | null
    if (!target) return
    if (panel.value?.contains(target) || trigger.value?.contains(target)) return
    closeMenu(false)
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key !== 'Escape' || !open.value) return
    event.preventDefault()
    event.stopPropagation()
    closeMenu(true)
  }

  function onBlur() {
    closeMenu(false)
  }

  function bindListeners(active: boolean) {
    if (active) {
      window.addEventListener('pointerdown', onPointerDown, true)
      window.addEventListener('keydown', onKeydown, true)
      window.addEventListener('blur', onBlur)
      window.addEventListener('resize', updatePosition)
      return
    }
    window.removeEventListener('pointerdown', onPointerDown, true)
    window.removeEventListener('keydown', onKeydown, true)
    window.removeEventListener('blur', onBlur)
    window.removeEventListener('resize', updatePosition)
  }

  watch(open, active => bindListeners(active))
  onScopeDispose(() => bindListeners(false))

  return {
    trigger,
    panel,
    isOpen: readonly(open),
    panelStyle,
    openMenu,
    closeMenu,
    toggleMenu,
    updatePosition,
  }
}

export interface MoveMenuFocusOptions {
  selector?: string
  columns?: number
}

/**
 * 在弹出菜单内的可聚焦选项之间移动焦点（支持单列上下与双排网格方向键）。
 */
export function moveMenuFocus(
  container: HTMLElement | null | undefined,
  key: string,
  options: MoveMenuFocusOptions = {},
): boolean {
  const { selector = '[data-menu-item]:not(:disabled)', columns = 1 } = options
  const items = Array.from(container?.querySelectorAll<HTMLElement>(selector) ?? [])
  if (!items.length) return false
  const current = items.findIndex(item => item === document.activeElement)
  const last = items.length - 1
  let next = 0
  if (key === 'ArrowRight' && columns > 1) {
    next = current < 0 ? 0 : (current + 1) % items.length
  } else if (key === 'ArrowLeft' && columns > 1) {
    next = current < 0 ? last : (current - 1 + items.length) % items.length
  } else if (key === 'ArrowDown') {
    if (current < 0) next = 0
    else if (current + columns < items.length) next = current + columns
    else next = current < last ? last : 0
  } else if (key === 'ArrowUp') {
    if (current < 0) next = last
    else if (current - columns >= 0) next = current - columns
    else next = last
  } else if (key === 'Home') {
    next = 0
  } else if (key === 'End') {
    next = last
  } else {
    return false
  }
  items[next]?.focus()
  items[next]?.scrollIntoView?.({ block: 'nearest' })
  return true
}
