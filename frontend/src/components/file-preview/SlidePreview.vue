<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getSlideSize, getVisibleSlides, loadPresentation } from '@office-kit/pptx'
import { renderSlideToSvg } from '@office-kit/pptx-preview'
import { Maximize2, X } from '@/components/icons'
import PreviewPager from './PreviewPager.vue'

const props = defineProps<{ bytes: ArrayBuffer }>()
const { t } = useI18n()
const reader = shallowRef<HTMLElement>()
const deck = shallowRef<Awaited<ReturnType<typeof loadPresentation>>>()
const slide = shallowRef(1)
const image = shallowRef('')
const failed = shallowRef(false)
const fullscreen = shallowRef(false)
const slides = computed(() => deck.value ? getVisibleSlides(deck.value) : [])
const ratio = computed(() => {
  const size = deck.value && getSlideSize(deck.value)
  return size ? size.width / size.height : 16 / 9
})

watch(() => props.bytes, async (bytes, _, cleanup) => {
  let current = true
  cleanup(() => { current = false })
  failed.value = false
  deck.value = undefined
  slide.value = 1
  try {
    const loaded = await loadPresentation(bytes)
    if (current) {
      deck.value = loaded
      failed.value = !getVisibleSlides(loaded).length
    }
  } catch {
    if (current) failed.value = true
  }
}, { immediate: true })

watch([deck, slide], ([presentation, index], _, cleanup) => {
  image.value = ''
  const current = slides.value[index - 1]
  if (!presentation || !current) return
  try {
    const svg = renderSlideToSvg(presentation, current)
    const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
    image.value = url
    failed.value = false
    cleanup(() => URL.revokeObjectURL(url))
  } catch { failed.value = true }
})

function syncFullscreen() {
  fullscreen.value = Boolean(reader.value && document.fullscreenElement === reader.value)
}
onMounted(() => document.addEventListener('fullscreenchange', syncFullscreen))
onUnmounted(() => document.removeEventListener('fullscreenchange', syncFullscreen))

async function present() {
  if (!reader.value?.requestFullscreen) return
  try {
    if (fullscreen.value) { await document.exitFullscreen(); return }
    await reader.value.requestFullscreen()
    reader.value.focus()
  } catch { /* The embedded slide view remains available. */ }
}

function navigate(event: KeyboardEvent) {
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault()
    slide.value = Math.max(1, Math.min(slides.value.length, slide.value + (event.key === 'ArrowRight' ? 1 : -1)))
  }
}
</script>

<template>
  <section ref="reader" class="slide-preview" tabindex="0" :aria-label="t('file_preview.slides')" @keydown="navigate">
    <div v-if="slides.length" class="slide-controls">
      <PreviewPager v-model="slide" :total="slides.length" :previous-label="t('file_preview.previous_slide')" :next-label="t('file_preview.next_slide')" />
      <button v-if="!failed" type="button" class="btn-secondary btn-xs" @click="present">
        <X v-if="fullscreen" :size="14" /><Maximize2 v-else :size="14" />
        {{ t(fullscreen ? 'file_preview.end_presentation' : 'file_preview.present') }}
      </button>
    </div>
    <div v-if="image && !failed" class="slide-stage" :style="{ '--slide-ratio': ratio }">
      <img :src="image" :alt="t('file_preview.slide_number', { page: slide })" @error="failed = true" />
    </div>
    <p v-else-if="failed" class="slide-state" role="alert">{{ t('file_preview.failed') }}</p>
    <p v-else class="slide-state" role="status">{{ t('common.loading') }}</p>
  </section>
</template>

<style scoped>
.slide-preview { display: flex; flex: 1; flex-direction: column; min-height: 0; min-width: 0; background: #edf2f7; }
.slide-controls { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 5px 10px; border-bottom: 1px solid #e2e8f0; color: #475569; background: #f8fafc; font-size: 12px; }
.slide-controls button { display: inline-flex; align-items: center; gap: 4px; }
.slide-stage { display: grid; flex: 1; min-height: 0; place-items: center; padding: 16px; container-type: size; }
.slide-stage img { display: block; width: min(100cqw, calc(100cqh * var(--slide-ratio))); max-height: 100%; background: #fff; box-shadow: 0 2px 10px #0f172a24; }
.slide-state { margin: auto; padding: 16px; color: #64748b; font-size: 13px; }
.slide-preview:fullscreen { background: #111827; }
</style>
