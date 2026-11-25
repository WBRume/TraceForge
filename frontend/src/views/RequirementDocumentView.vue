<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Download } from '@/components/icons'
import TextReviewCanvas from '@/components/doc-review/TextReviewCanvas.vue'
import { requirementDocumentUrl } from '@/components/workspace-assets/requirements/requirementDocuments'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'

interface RequirementDocument { id: string; name: string; markdown: string; focus_text: string | null }

const route = useRoute()
const { t } = useI18n()
const doc = shallowRef<RequirementDocument | null>(null)
const error = shallowRef('')
const url = computed(() => requirementDocumentUrl(String(route.params.wsId), String(route.params.documentId)))
const block = computed(() => typeof route.query.block === 'string' ? route.query.block : undefined)

watch([url, block], async ([path, focus], _old, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  doc.value = null
  error.value = ''
  try {
    const { data } = await api.get<RequirementDocument>(path, { params: { block: focus }, signal: controller.signal })
    if (!controller.signal.aborted) doc.value = data
  } catch (cause) {
    if (!controller.signal.aborted) error.value = formatApiError(cause, t('workspace_canvas.load_failed'), t)
  }
}, { immediate: true })

async function download() {
  if (!doc.value) return
  const name = doc.value.name
  try {
    const response = await api.get<Blob>(`${url.value}/download`, { responseType: 'blob' })
    const link = document.createElement('a')
    const encoded = /filename\*=UTF-8''([^;]+)/i.exec(String(response.headers['content-disposition']))?.[1]
    link.href = URL.createObjectURL(response.data)
    link.download = encoded ? decodeURIComponent(encoded) : name
    link.click()
    URL.revokeObjectURL(link.href)
  } catch (cause) {
    error.value = formatApiError(cause, t('workspace_canvas.load_failed'), t)
  }
}
</script>

<template>
  <section class="requirement-document-view">
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!doc" role="status">{{ t('common.loading') }}</p>
    <template v-if="doc">
      <header><h2>{{ doc.name }}</h2>
        <button class="btn-secondary" type="button" @click="download"><Download :size="16" />{{ t('workspace_canvas.actions.download') }}</button>
      </header>
      <div class="canvas-shell">
        <TextReviewCanvas :source="doc.markdown" markdown :markers-by-block="{}" :threads="[]"
          :selected-thread-id="''" :inline-review-enabled="false" :focus-text="doc.focus_text || undefined" />
      </div>
    </template>
  </section>
</template>

<style scoped>
.requirement-document-view { display: flex; flex-direction: column; height: 100%; min-height: 0; padding: 16px; }
header { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding-bottom: 10px; }
h2 { margin: 0; font-size: 18px; overflow-wrap: anywhere; }
button { display: inline-flex; align-items: center; gap: 6px; }
.canvas-shell { min-height: 0; flex: 1; overflow: auto; border: 1px solid #e2e8f0; border-radius: 10px; }
</style>
