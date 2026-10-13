<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'
import { MessageSquare } from '@/components/icons'
import { injectContextAnnotations } from '@/composables/chat/annotations/useContextAnnotations'

const annotations = injectContextAnnotations()
const pending = computed(() => annotations?.pending.value)
const panel = shallowRef<HTMLElement | null>(null)
const position = shallowRef({ left: '8px', top: '8px' })

async function place() {
  await nextTick()
  if (!pending.value) return
  const rect = panel.value?.getBoundingClientRect()
  position.value = {
    left: `${Math.max(8, Math.min(pending.value.x, window.innerWidth - (rect?.width || 100) - 8))}px`,
    top: `${Math.max(8, Math.min(pending.value.y, window.innerHeight - (rect?.height || 36) - 8))}px`,
  }
}
watch(pending, () => { void place() })
function outside(event: PointerEvent) {
  if (!panel.value?.contains(event.target as Node)) annotations?.dismiss()
}
function keydown(event: KeyboardEvent) { if (event.key === 'Escape') annotations?.dismiss() }
function onScroll(event: Event) {
  if (!panel.value?.contains(event.target as Node)) annotations?.dismiss()
}
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  document.addEventListener('keydown', keydown)
  document.addEventListener('scroll', onScroll, true)
  window.addEventListener('resize', place)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('keydown', keydown)
  document.removeEventListener('scroll', onScroll, true)
  window.removeEventListener('resize', place)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="pending" ref="panel" class="annotation-popover" :style="position" @pointerdown.stop>
      <button type="button" class="annotation-add" @mousedown.prevent @click="annotations?.add()"><MessageSquare :size="14" />添加批注</button>
    </div>
  </Teleport>
</template>

<style scoped>
.annotation-popover { position: fixed; z-index: 12000; max-width: calc(100vw - 16px); box-sizing: border-box; border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; color: #334155; box-shadow: 0 5px 20px #0f172a20; font-size: 12px; }
.annotation-add { display: flex; align-items: center; gap: 6px; padding: 8px 12px; }
button { border: 0; background: transparent; color: inherit; cursor: pointer; }
</style>
