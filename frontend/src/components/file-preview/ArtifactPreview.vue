<script setup lang="ts">
import { computed, defineAsyncComponent, defineComponent, h, shallowRef, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { fileType } from './fileTypes'
import { prepareHtml, type HtmlAssetResolver } from './htmlPreview'

function previewState(role: string, label: string) {
  return defineComponent({
    setup() {
      const { t } = useI18n()
      return () => h('p', { class: 'preview-state', role }, t(label))
    },
  })
}
const loadingComponent = previewState('status', 'common.loading')
const errorComponent = previewState('alert', 'file_preview.failed')
const lazy = <T extends Component>(loader: () => Promise<{ default: T }>) =>
  defineAsyncComponent({ loader, loadingComponent, errorComponent, suspensible: false })
const WordPreview = lazy(() => import('./WordPreview.vue'))
const SpreadsheetPreview = lazy(() => import('./SpreadsheetPreview.vue'))
const SlidePreview = lazy(() => import('./SlidePreview.vue'))
const PdfPreview = lazy(() => import('./PdfPreview.vue'))

const props = defineProps<{ name: string; source: (signal?: AbortSignal) => Promise<ArrayBuffer>; resolveHtmlAsset?: HtmlAssetResolver }>()
const { t } = useI18n()
const engine = computed(() => fileType(props.name).engine)
const bytes = shallowRef<ArrayBuffer>()
const failed = shallowRef(false)
const image = shallowRef('')
const html = shallowRef<string>()
const pdfSource = computed(() => {
  const data = bytes.value
  return async () => data!.slice(0)
})

watch(() => props.source, async (load, _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  bytes.value = undefined
  html.value = undefined
  failed.value = false
  try {
    const data = await load(request.signal)
    if (!request.signal.aborted && engine.value === 'html') {
      const markup = await prepareHtml(data, request.signal, props.resolveHtmlAsset)
      if (!request.signal.aborted) html.value = markup
    }
    if (!request.signal.aborted) bytes.value = data
  } catch {
    if (!request.signal.aborted) failed.value = true
  }
}, { immediate: true })

watch([bytes, engine, () => props.name], ([data, type, name], _, cleanup) => {
  image.value = ''
  if (!data || type !== 'image') return
  const extension = name.split('.').at(-1)?.toLowerCase()
  const mime = extension === 'svg' ? 'image/svg+xml' : extension === 'jpg' ? 'image/jpeg' : `image/${extension}`
  const url = URL.createObjectURL(new Blob([data], { type: mime }))
  image.value = url
  cleanup(() => URL.revokeObjectURL(url))
})
</script>

<template>
  <section class="artifact-preview" :aria-label="t('file_preview.preview', { name })">
    <p v-if="failed" class="preview-state" role="alert">{{ t('file_preview.failed') }}</p>
    <p v-else-if="!bytes" class="preview-state" role="status">{{ t('common.loading') }}</p>
    <template v-else>
      <PdfPreview v-if="engine === 'pdf'" :source="pdfSource" paged />
      <WordPreview v-else-if="engine === 'word'" :bytes="bytes" :name="name" />
      <SpreadsheetPreview v-else-if="engine === 'sheet'" :bytes="bytes" />
      <SlidePreview v-else-if="engine === 'slides'" :bytes="bytes" />
      <iframe v-else-if="engine === 'html'" class="html-preview" :title="name" sandbox="allow-scripts" referrerpolicy="no-referrer" :srcdoc="html" />
      <div v-else-if="engine === 'image'" class="image-preview"><img v-if="image" :src="image" :alt="name" @error="failed = true" /></div>
      <p v-else class="preview-state">{{ t('file_preview.unsupported') }}</p>
    </template>
  </section>
</template>

<style scoped>
.artifact-preview { display: flex; flex: 1; min-height: 0; min-width: 0; overflow: hidden; background: #f8fafc; }
.preview-state { margin: auto; padding: 16px; color: #64748b; font-size: 13px; }
.html-preview { flex: 1; width: 100%; min-width: 0; border: 0; background: #fff; }
.image-preview { display: grid; flex: 1; min-width: 0; min-height: 0; place-items: center; padding: 16px; }
.image-preview img { display: block; max-width: 100%; max-height: 100%; object-fit: contain; }
</style>
