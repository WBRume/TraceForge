<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, shallowRef, useTemplateRef } from 'vue'
import type { CanvasContextRequest, CanvasMenuItem } from './contextMenu'

const props = defineProps<{ request: CanvasContextRequest; items: CanvasMenuItem[]; label: string }>()
const emit = defineEmits<{ choose: [key: CanvasMenuItem['key']]; close: [returnFocus?: boolean] }>()
const menu = useTemplateRef<HTMLElement>('menu')
const menuHeight = shallowRef(0)
const width = 230
const style = computed(() => ({
  left: `${Math.max(6, Math.min(props.request.anchor.x, props.request.size.width - width - 6))}px`,
  top: `${Math.max(6, Math.min(props.request.anchor.y, props.request.size.height - menuHeight.value - 6))}px`,
  width: `${Math.min(width, props.request.size.width - 12)}px`,
  maxHeight: `${Math.max(90, props.request.size.height - 12)}px`,
}))

function buttons() {
  return Array.from(menu.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])
}

function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape' || event.key === 'Tab') {
    if (event.key === 'Escape') event.preventDefault()
    emit('close', true)
    return
  }
  if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const entries = buttons()
  const current = entries.indexOf(document.activeElement as HTMLButtonElement)
  const last = entries.length - 1
  const index = event.key === 'Home' ? 0 : event.key === 'End' ? last
    : event.key === 'ArrowUp' ? (current <= 0 ? last : current - 1)
    : current >= last ? 0 : current + 1
  entries[index]?.focus()
}

function dismiss(event: PointerEvent) {
  if (!menu.value?.contains(event.target as Node)) emit('close')
}

onMounted(() => {
  menuHeight.value = menu.value?.offsetHeight ?? 0
  const first = buttons()[0] ?? menu.value
  first?.focus({ preventScroll: true })
  document.addEventListener('pointerdown', dismiss, true)
})
onBeforeUnmount(() => document.removeEventListener('pointerdown', dismiss, true))
</script>

<template>
  <div ref="menu" class="canvas-context-menu" data-testid="canvas-context-menu" role="menu" tabindex="-1"
    :aria-label="label" :style="style" @keydown.stop="keydown" @contextmenu.prevent.stop>
    <button v-for="item in items" :key="item.key" class="context-item" type="button" role="menuitem"
      :class="{ 'new-group': item.divider, danger: item.danger }"
      :disabled="item.disabled" @click="emit('choose', item.key)">
      <component :is="item.icon" :size="17" />
      {{ item.label }}
    </button>
  </div>
</template>

<style scoped>
.canvas-context-menu {
  position: absolute;
  z-index: 10;
  overflow: auto;
  box-sizing: border-box;
  padding: 5px;
  background: #fff;
  color: #192a40;
  border: 1px solid #d9e3ef;
  border-radius: 11px;
  box-shadow: 0 12px 34px #1e3c552b;
  outline: none;
}
.context-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  min-height: 33px;
  padding: 5px 9px;
  text-align: start;
  background: transparent;
  border: 0;
  border-radius: 6px;
  color: inherit;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.context-item.new-group { margin-top: 5px; border-top: 1px solid #e4edf5; padding-top: 8px; }
.context-item.danger { color: #a42e42; }
.context-item:is(:hover, :focus-visible) { background: #eaf5fd; outline: none; }
.context-item:disabled { color: #a5afbb; cursor: default; }
</style>
