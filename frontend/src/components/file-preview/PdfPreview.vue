<script setup lang="ts">
import { ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import * as pdfjs from 'pdfjs-dist'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { Minus, Plus } from '@/components/icons'
import PreviewPager from './PreviewPager.vue'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
const props = defineProps<{ source: () => Promise<ArrayBuffer>; paged?: boolean }>()
const { t } = useI18n()
const viewport = ref<HTMLElement>()
const pages = ref<HTMLElement>()
const doc = shallowRef<PDFDocumentProxy>()
const page = ref(1)
const zoom = ref(1)
const width = ref(0)
const loading = ref(true)
const failed = ref(false)

watch(viewport, (element, _, cleanup) => {
  if (!element) return
  width.value = element.clientWidth
  if (typeof ResizeObserver === 'undefined') return
  const observer = new ResizeObserver(() => { width.value = element.clientWidth })
  observer.observe(element)
  cleanup(() => observer.disconnect())
})

watch(() => props.source, async (load, _, cleanup) => {
  let current = true
  let task: ReturnType<typeof pdfjs.getDocument> | undefined
  cleanup(() => { current = false; void task?.destroy?.().catch(() => {}) })
  doc.value = undefined
  pages.value?.replaceChildren()
  page.value = 1
  zoom.value = 1
  loading.value = true
  failed.value = false
  try {
    const bytes = await load()
    if (!current) return
    task = pdfjs.getDocument({ data: new Uint8Array(bytes), isEvalSupported: false })
    const loaded = await task.promise
    if (current) doc.value = loaded
  } catch {
    if (current) { failed.value = true; loading.value = false }
  }
}, { immediate: true })

watch([doc, pages, page, zoom, width], async ([pdf, element, currentPage, magnification, available], _, cleanup) => {
  if (!pdf || !element) return
  let current = true
  let render: RenderTask | undefined
  cleanup(() => { current = false; render?.cancel?.() })
  failed.value = false
  const first = props.paged ? currentPage : 1
  const last = props.paged ? currentPage : pdf.numPages
  const canvases: HTMLCanvasElement[] = []
  try {
    for (let n = first; n <= last; n++) {
      const sheet = await pdf.getPage(n)
      if (!current) return
      const natural = sheet.getViewport({ scale: 1 })
      const fit = available > 32 ? (available - 32) / natural.width : 1
      const view = sheet.getViewport({ scale: Math.min(2, fit) * magnification })
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2, 4096 / Math.max(view.width, view.height))
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.floor(view.width * pixelRatio))
      canvas.height = Math.max(1, Math.floor(view.height * pixelRatio))
      canvas.style.width = `${view.width}px`
      canvas.style.height = `${view.height}px`
      canvas.className = 'pdf-page'
      canvas.setAttribute('aria-label', t('file_preview.pdf_page', { page: n }))
      const context = canvas.getContext('2d')!
      render = sheet.render({ canvasContext: context, viewport: view, transform: [pixelRatio, 0, 0, pixelRatio, 0, 0] })
      await render.promise
      if (!current) return
      canvases.push(canvas)
    }
    element.replaceChildren(...canvases)
  } catch {
    if (current) failed.value = true
  } finally {
    if (current) loading.value = false
  }
}, { flush: 'post' })
</script>

<template>
  <section class="pdf-preview">
    <div v-if="paged && doc" class="pdf-controls">
      <PreviewPager v-model="page" :total="doc.numPages" :previous-label="t('file_preview.previous_page')" :next-label="t('file_preview.next_page')" />
      <div class="zoom-controls">
        <button type="button" :aria-label="t('file_preview.zoom_out')" :disabled="zoom <= .5" @click="zoom = Math.max(.5, zoom - .25)"><Minus :size="14" /></button>
        <button type="button" :aria-label="t('file_preview.fit')" @click="zoom = 1">{{ Math.round(zoom * 100) }}%</button>
        <button type="button" :aria-label="t('file_preview.zoom_in')" :disabled="zoom >= 3" @click="zoom = Math.min(3, zoom + .25)"><Plus :size="14" /></button>
      </div>
    </div>
    <div ref="viewport" class="pdf-viewport custom-scrollbar">
      <p v-if="loading" class="pdf-hint" role="status">{{ t('doc_review.pdf_loading') }}</p>
      <p v-else-if="failed" class="pdf-hint pdf-error" role="alert">{{ t('doc_review.pdf_failed') }}</p>
      <div ref="pages" class="pdf-pages" />
    </div>
  </section>
</template>

<style scoped>
.pdf-preview { display: flex; flex-direction: column; flex: 1; min-height: 0; min-width: 0; height: 100%; }
.pdf-controls { display: flex; align-items: center; justify-content: center; gap: 16px; padding: 5px 10px; color: #475569; background: #f8fafc; border-bottom: 1px solid #e2e8f0; font-size: 12px; }
.zoom-controls { display: flex; gap: 4px; }
.zoom-controls button { display: grid; place-items: center; min-width: 28px; height: 28px; padding: 0 6px; color: #475569; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; cursor: pointer; }
.zoom-controls button:hover:not(:disabled) { color: #0284c7; background: #f0f9ff; }
.zoom-controls button:disabled { opacity: .45; cursor: default; }
.pdf-viewport { flex: 1; overflow: auto; background: #edf2f7; }
.pdf-pages { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 16px; min-width: max-content; }
.pdf-pages :deep(.pdf-page) { display: block; background: #fff; box-shadow: 0 2px 10px #0f172a24; border-radius: 2px; }
.pdf-hint { text-align: center; color: #64748b; font-size: .85rem; }
.pdf-error { color: #b91c1c; }
</style>
