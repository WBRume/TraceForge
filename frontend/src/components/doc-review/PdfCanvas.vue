<!-- PdfCanvas:PDF 只读预览。axios 取原文件字节直接喂 pdf.js(规避 URL 鉴权),
     逐页渲染 canvas,页面宽度自适应容器。 -->
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import api from '@/utils/api'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

const props = defineProps<{
  wsId: string
  assetId: string
  versionId?: string | null
}>()

const { t } = useI18n()
const containerRef = ref<HTMLElement | null>(null)
const loading = ref(true)
const error = ref(false)

const loadPdf = async () => {
  if (!props.wsId || !props.assetId) return
  loading.value = true
  error.value = false
  try {
    const query = props.versionId ? `?version_id=${encodeURIComponent(props.versionId)}` : ''
    const res = await api.get(`/workspaces/${props.wsId}/assets/${props.assetId}/file${query}`, {
      responseType: 'arraybuffer',
    })
    const doc = await pdfjsLib.getDocument({ data: new Uint8Array(res.data) }).promise
    await renderAll(doc)
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

const renderAll = async (doc: any) => {
  const container = containerRef.value
  if (!container) return
  container.querySelectorAll('canvas').forEach((c) => c.remove())
  for (let n = 1; n <= doc.numPages; n++) {
    const page = await doc.getPage(n)
    const base = page.getViewport({ scale: 1 })
    const scale = Math.min(2, Math.max(1, (container.clientWidth - 32) / base.width))
    const viewport = page.getViewport({ scale })
    const canvas = document.createElement('canvas')
    canvas.width = Math.floor(viewport.width)
    canvas.height = Math.floor(viewport.height)
    canvas.className = 'pdf-page-canvas'
    container.appendChild(canvas)
    const ctx = canvas.getContext('2d')
    await page.render({ canvasContext: ctx, viewport }).promise
  }
}

watch(() => [props.assetId, props.versionId], () => {
  void loadPdf()
})
onMounted(() => {
  void loadPdf()
})
</script>

<template>
  <div ref="containerRef" class="pdf-canvas custom-scrollbar">
    <p v-if="loading" class="pdf-hint">{{ t('doc_review.pdf_loading') }}</p>
    <p v-else-if="error" class="pdf-hint pdf-error">{{ t('doc_review.pdf_failed') }}</p>
  </div>
</template>

<style scoped>
.pdf-canvas {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  background: #e2e8f0;
}
.pdf-page-canvas {
  background: #fff;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.14);
  border-radius: 2px;
}
.pdf-hint {
  color: #64748b;
  font-size: 0.85rem;
}
.pdf-error {
  color: #b91c1c;
}
</style>
