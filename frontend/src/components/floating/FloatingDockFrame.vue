<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'
import { Minus, X } from '@/components/icons'
import type { FloatPoint, FloatSize, PanelDrag } from '@/types/taskFloat'
import { fitFloatingPosition } from './floatingGeometry'

export interface FloatingGeometry {
  minimized: boolean
  position: FloatPoint
  size: FloatSize
  dockTop: number
}
const props = defineProps<{
  geometry?: FloatingGeometry
  title: string
  tone?: string
  detachable?: boolean
  desktopDragActive?: boolean
  desktopPreview?: boolean
  desktopDetached?: boolean
  desktop?: boolean
  desktopDrag?: boolean
}>()
const emit = defineEmits<{
  position: [value: FloatPoint]
  size: [value: FloatSize]
  dockTop: [value: number]
  minimize: []
  open: []
  close: []
  panelDrag: [value: PanelDrag]
  desktopDragStart: [event: PointerEvent]
}>()
type Gesture = {
  mode: 'panel' | 'pill' | 'right' | 'corner'
  x: number
  y: number
  geometry: FloatingGeometry
  moved: number
  pointerId: number
  canDetach: boolean
}
let gesture: Gesture | undefined
const dragPosition = shallowRef<FloatPoint>()
const panelStyle = computed(() => {
  if (props.desktop || !props.geometry) return undefined
  const { x, y } = props.geometry.position
  const { width, height } = props.geometry.size
  const dragging = dragPosition.value
  return {
    left: `${x}px`, top: `${y}px`, width: `${width}px`, height: `${height}px`,
    translate: dragging ? `${dragging.x - x}px ${dragging.y - y}px` : undefined,
  }
})
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(Math.max(min, max), value))
const fitPosition = (position: FloatPoint, size: FloatSize) => fitFloatingPosition(position, size, {
  width: window.innerWidth,
  height: window.innerHeight,
})

function outsidePosition(position: FloatPoint, size: FloatSize, displacement: number) {
  // Use the panel edge so the gesture also works with a maximized client.
  const overhang = Math.max(-position.x, -position.y,
    position.x + size.width - window.innerWidth, position.y + size.height - window.innerHeight)
  return displacement >= 8 && overhang >= 12 ? position : null
}

const move = (event: PointerEvent) => {
  if (!gesture || event.pointerId !== gesture.pointerId) return
  const { mode, geometry, x, y } = gesture
  const dx = event.clientX - x, dy = event.clientY - y
  gesture.moved = Math.max(gesture.moved, Math.hypot(dx, dy))
  if (mode === 'pill') emit('dockTop', clamp(geometry.dockTop + dy, 60, window.innerHeight - 50))
  else if (mode === 'panel') {
    const position = { x: geometry.position.x + dx, y: geometry.position.y + dy }
    if (gesture.canDetach) {
      dragPosition.value = position
      emit('panelDrag', { type: 'move', position: outsidePosition(position, geometry.size, gesture.moved) })
    } else emit('position', fitPosition(position, geometry.size))
  }
  else emit('size', {
    width: clamp(geometry.size.width + dx, Math.min(300, window.innerWidth - 20), window.innerWidth - geometry.position.x - 10),
    height: mode === 'corner' ? clamp(geometry.size.height + dy, Math.min(200, window.innerHeight - 20), window.innerHeight - geometry.position.y - 10) : geometry.size.height,
  })
}
const cleanup = () => {
  gesture = undefined
  dragPosition.value = undefined
  window.removeEventListener('pointermove', move)
  window.removeEventListener('pointerup', finish)
  window.removeEventListener('pointercancel', cancel)
}
const cancel = (event?: PointerEvent) => {
  if (!gesture || (event && event.pointerId !== gesture.pointerId)) return
  const canDetach = gesture.canDetach
  cleanup()
  if (canDetach) emit('panelDrag', { type: 'end', position: null })
}
const finish = (event: PointerEvent) => {
  if (!gesture || event.pointerId !== gesture.pointerId) return
  const { geometry, x, y, moved, mode, canDetach } = gesture
  const dx = event.clientX - x
  const dy = event.clientY - y
  const displacement = Math.max(moved, Math.hypot(dx, dy))
  cleanup()
  if (mode === 'pill' && displacement <= 4) emit('open')
  if (canDetach) {
    const position = { x: geometry.position.x + dx, y: geometry.position.y + dy }
    const outside = outsidePosition(position, geometry.size, displacement)
    if (outside && props.desktopDragActive) dragPosition.value = position
    if (!outside && displacement) emit('position', fitPosition(position, geometry.size))
    emit('panelDrag', { type: 'end', position: outside })
  }
}
const begin = (event: PointerEvent, mode: Gesture['mode']) => {
  const geometry = props.geometry
  if (event.button !== 0 || (event.target as Element).closest('button, a, input')) return
  if (props.desktop) {
    if (props.desktopDrag) emit('desktopDragStart', event)
    return
  }
  if (!geometry) return
  event.preventDefault()
  cancel()
  const canDetach = mode === 'panel' && Boolean(props.detachable)
  gesture = { mode, x: event.clientX, y: event.clientY, moved: 0, pointerId: event.pointerId, canDetach,
    geometry: { ...geometry, position: { ...geometry.position }, size: { ...geometry.size } } }
  const handle = event.currentTarget as HTMLElement
  handle.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', finish)
  window.addEventListener('pointercancel', cancel)
  if (canDetach) emit('panelDrag', { type: 'start' })
}
const fitViewport = () => {
  if (props.desktop || !props.geometry) return
  const { position, size: panelSize, dockTop } = props.geometry
  const size = { width: Math.min(panelSize.width, window.innerWidth - 20), height: Math.min(panelSize.height, window.innerHeight - 20) }
  emit('size', size)
  emit('position', fitPosition(position, size))
  emit('dockTop', clamp(dockTop, 60, window.innerHeight - 50))
}
onMounted(() => {
  if (props.desktop) return
  fitViewport()
  window.addEventListener('resize', fitViewport)
})
watch(() => props.desktopDragActive, active => {
  if (!active && !gesture) dragPosition.value = undefined
})
onBeforeUnmount(() => { cancel(); window.removeEventListener('resize', fitViewport) })
</script>

<template>
  <div v-if="!desktop && geometry?.minimized" class="right-docked-pill" :class="tone" :style="{ top: `${geometry.dockTop}px` }"
    role="button" tabindex="0" :aria-label="`展开 ${title}`" :title="`${title}（上下拖拽，轻点展开）`"
    @pointerdown="begin($event, 'pill')" @keydown.enter.prevent="emit('open')" @keydown.space.prevent="emit('open')">
    <div class="docked-pill-inner"><slot name="pill" /></div>
    <button type="button" class="pill-close action-icon-btn" aria-label="关闭浮窗" @pointerdown.stop @keydown.stop @click.stop="emit('close')"><X class="w-3 h-3" /></button>
  </div>
  <section v-else class="pinned-panel" :class="[tone, { 'desktop-window': desktop, 'desktop-preview': desktopPreview, 'desktop-detached': desktopDetached }]"
    :aria-label="title" :aria-hidden="desktopPreview || desktopDetached || undefined" :inert="desktopDetached || undefined" :style="panelStyle">
    <header class="panel-header" :class="{ 'native-drag': desktop && !desktopDrag }"
      :data-tauri-drag-region="desktop && !desktopDrag ? '' : undefined"
      @pointerdown="begin($event, 'panel')" @lostpointercapture="cancel($event)">
      <div class="header-left" :title="detachable ? '拖出客户端边缘可移到桌面' : undefined"><slot name="header" /></div>
      <div class="header-actions">
        <slot name="actions" />
        <button v-if="!desktop" type="button" class="action-icon-btn" title="最小化到右侧" aria-label="最小化到右侧" @click.stop="emit('minimize')"><Minus class="w-3.5 h-3.5" /></button>
        <button type="button" class="action-icon-btn is-close" title="关闭浮窗" aria-label="关闭浮窗" @click.stop="emit('close')"><X class="w-3.5 h-3.5" /></button>
      </div>
    </header>
    <main class="panel-body"><slot /></main>
    <div v-if="!desktop" class="resize-handle-right" @pointerdown="begin($event, 'right')" />
    <div v-if="!desktop" class="resize-handle-corner" @pointerdown="begin($event, 'corner')" />
  </section>
</template>

<style scoped>
.pinned-panel { position: fixed; display: flex; flex-direction: column; pointer-events: auto; border-radius: 14px; background: #fff; border: 1px solid #e2e8f0; box-shadow: 0 20px 35px -5px rgb(15 23 42 / 16%), 0 10px 15px -5px rgb(15 23 42 / 8%); overflow: hidden; z-index: 3000; }
.pinned-panel.desktop-preview { opacity: 0; pointer-events: none; }
.pinned-panel.desktop-detached { visibility: hidden; }
.pinned-panel.desktop-window { inset: 0; border-radius: 0; box-shadow: none; }
.panel-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 9px 12px; border-bottom: 1px solid #f1f5f9; background: #fff; cursor: grab; touch-action: none; user-select: none; }
.panel-header.native-drag { -webkit-app-region: drag; app-region: drag; }
.native-drag .header-left { pointer-events: none; }
.native-drag .header-actions { -webkit-app-region: no-drag; app-region: no-drag; }
.panel-header:active, .right-docked-pill:active { cursor: grabbing; }
.header-left { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1; }
.header-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.action-icon-btn, :slotted(.action-icon-btn) { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border: none; background: transparent; color: #64748b; border-radius: 6px; cursor: pointer; }
.action-icon-btn:hover, :slotted(.action-icon-btn:hover) { background: #f1f5f9; color: #0f172a; }
.is-close:hover, .pill-close:hover { background: #fff1f2; color: #e11d48; }
.panel-body { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; background: #fff; }
.resize-handle-right { position: absolute; top: 0; right: 0; width: 7px; height: 100%; cursor: ew-resize; z-index: 10; touch-action: none; }
.resize-handle-corner { position: absolute; right: 0; bottom: 0; width: 14px; height: 14px; cursor: nwse-resize; z-index: 11; touch-action: none; }
.resize-handle-corner::after { content: ''; position: absolute; right: 3px; bottom: 3px; width: 6px; height: 6px; border-right: 2px solid #94a3b8; border-bottom: 2px solid #94a3b8; }
.right-docked-pill { position: fixed; right: 0; pointer-events: auto; display: flex; align-items: center; height: 40px; max-width: 192px; border-radius: 20px 0 0 20px; background: #fff; border: 1px solid #e2e8f0; border-right: none; box-shadow: -4px 6px 16px rgb(15 23 42 / 12%); cursor: grab; touch-action: none; user-select: none; z-index: 3000; padding: 3px 6px 3px 8px; transition: transform .18s ease, box-shadow .18s ease; }
.right-docked-pill:hover { transform: translateX(-4px); box-shadow: -6px 8px 22px rgb(15 23 42 / 18%); }
.right-docked-pill:focus-visible { outline: 2px solid #0284c7; outline-offset: 2px; }
.docked-pill-inner { display: flex; align-items: center; gap: 6px; min-width: 0; }
.pill-close { opacity: 0; width: 18px; flex-shrink: 0; }
.right-docked-pill:hover .pill-close, .right-docked-pill:focus-within .pill-close { opacity: 1; }
.right-docked-pill.is-waiting { border-color: #fbbf24; box-shadow: -4px 6px 16px rgb(217 119 6 / 16%); }
.right-docked-pill.is-finished { border-color: #86efac; }
.right-docked-pill.is-error { border-color: #fda4af; }
@media (prefers-reduced-motion: reduce) { .right-docked-pill { transition: none; } }
</style>
