<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { renderAsync } from 'docx-preview'

const props = defineProps<{ bytes: ArrayBuffer; name: string }>()
const { t } = useI18n()
const frame = shallowRef<HTMLIFrameElement>()
const loaded = shallowRef(false)
const loading = shallowRef(true)
const failed = shallowRef(false)
const documentShell = `<!doctype html><meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; font-src data: blob:; form-action 'none'; base-uri 'none'">
  <style>
    html,body {margin:0;background:#edf2f7}
    main .docx-wrapper {min-height:100vh;box-sizing:border-box;background:#edf2f7;padding:16px}
    main .docx-wrapper > section.docx {zoom:var(--page-zoom,1);box-shadow:0 2px 10px #0f172a24}
  </style>
  <main></main>`

function fitPages() {
  const element = frame.value
  const target = element?.contentDocument?.querySelector('main')
  if (!element || !target || !element.clientWidth) return
  const width = Math.max(1, ...Array.from(target.querySelectorAll<HTMLElement>('section.docx'), page => page.offsetWidth))
  target.style.setProperty('--page-zoom', String(Math.min(1, Math.max(1, element.clientWidth - 48) / width)))
}

watch(frame, (element, _, cleanup) => {
  if (!element || typeof ResizeObserver === 'undefined') return
  const observer = new ResizeObserver(fitPages)
  observer.observe(element)
  cleanup(() => observer.disconnect())
})
watch(loading, fitPages, { flush: 'post' })

watch([loaded, () => props.bytes], async ([ready, bytes], _, cleanup) => {
  if (!ready) return
  const doc = frame.value?.contentDocument
  const target = doc?.querySelector('main')
  if (!doc || !target) return
  let current = true
  cleanup(() => { current = false })
  const wrapper = doc.createElement('div')
  loading.value = true
  failed.value = false
  try {
    await renderAsync(bytes, wrapper, wrapper, { renderAltChunks: false, useBase64URL: true, ignoreLastRenderedPageBreak: false })
    if (!current) return
    for (const link of wrapper.querySelectorAll('a')) {
      if (!link.getAttribute('href')?.startsWith('#')) link.removeAttribute('href')
      link.removeAttribute('xlink:href')
    }
    target.replaceChildren(wrapper)
  } catch {
    if (current) { failed.value = true; target.replaceChildren() }
  } finally {
    if (current) loading.value = false
  }
})
</script>

<template>
  <div class="word-preview">
    <p v-if="loading" class="word-state" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="failed" class="word-state" role="alert">{{ t('file_preview.failed') }}</p>
    <iframe v-show="!loading && !failed" ref="frame" :title="name" sandbox="allow-same-origin" :srcdoc="documentShell" @load="loaded = true" />
  </div>
</template>

<style scoped>
.word-preview { display: flex; flex: 1; min-height: 0; min-width: 0; background: #edf2f7; }
.word-preview iframe { flex: 1; min-width: 0; width: 100%; border: 0; }
.word-state { margin: auto; padding: 16px; color: #64748b; font-size: 13px; }
</style>
