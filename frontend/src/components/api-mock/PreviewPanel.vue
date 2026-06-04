<script setup lang="ts">
import { reactive, watch } from 'vue'
import { Play, Copy } from 'lucide-vue-next'
import type { ApiMockEndpoint, ApiMockPreviewResponse } from '@/types/apiMock'

const props = defineProps<{
  endpoint: ApiMockEndpoint | null
  preview: ApiMockPreviewResponse | null
  previewBusy: boolean
}>()

const emit = defineEmits<{
  (e: 'run-preview', payload: { method: string; path: string; body: unknown }): void
}>()

const form = reactive({
  method: 'GET',
  path: '/',
  bodyText: '{}',
})

watch(
  () => props.endpoint,
  (endpoint) => {
    if (!endpoint) return
    form.method = endpoint.method
    form.path = endpoint.path
  },
  { immediate: true },
)

const parseBody = () => {
  const text = (form.bodyText || '').trim()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

const runPreview = () => {
  if (!props.endpoint || props.previewBusy) return
  emit('run-preview', {
    method: form.method,
    path: form.path,
    body: parseBody(),
  })
}

const copyRestc = async () => {
  const command = props.preview?.restc_command
  if (!command) return
  try {
    await navigator.clipboard.writeText(command)
  } catch {
    // ignore clipboard errors
  }
}
</script>

<template>
  <section class="panel glass-panel">
    <header class="head">
      <h3>{{ $t('api_mock.preview_title') }}</h3>
      <button type="button" class="btn-primary mini" :disabled="!endpoint || previewBusy" @click="runPreview">
        <Play class="w-4 h-4" />
        {{ previewBusy ? $t('api_mock.previewing') : $t('api_mock.preview_now') }}
      </button>
    </header>

    <div class="grid">
      <label class="field">
        <span>{{ $t('api_mock.method') }}</span>
        <input v-model="form.method" class="input-field" />
      </label>
      <label class="field">
        <span>{{ $t('api_mock.path') }}</span>
        <input v-model="form.path" class="input-field" />
      </label>
    </div>

    <label class="field">
      <span>{{ $t('api_mock.preview_body') }}</span>
      <textarea v-model="form.bodyText" class="input-field textarea" />
    </label>

    <div v-if="preview" class="result">
      <div class="result-meta">
        <span class="chip">{{ preview.mode }}</span>
        <span class="chip">{{ preview.status_code }}</span>
        <span class="chip">{{ preview.latency_ms }}ms</span>
      </div>
      <pre>{{ JSON.stringify(preview.body, null, 2) }}</pre>
      <div class="restc">
        <code>{{ preview.restc_command }}</code>
        <button type="button" class="btn-secondary mini" @click="copyRestc">
          <Copy class="w-4 h-4" />
          {{ $t('api_mock.copy_restc') }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.panel {
  padding: 0.9rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.head h3 {
  margin: 0;
  font-size: 0.92rem;
  color: #0f172a;
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.6rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.field span {
  font-size: 0.74rem;
  color: #475569;
}

.textarea {
  min-height: 80px;
  resize: vertical;
  padding-top: 0.6rem;
}

.result {
  border: 1px solid #dbeafe;
  border-radius: 10px;
  padding: 0.65rem;
  background: #fff;
}

.result-meta {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.45rem;
}

.chip {
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 700;
  color: #0369a1;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 0.16rem 0.45rem;
}

pre {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.55rem;
  background: #f8fafc;
  color: #0f172a;
  font-size: 0.74rem;
}

.restc {
  margin-top: 0.6rem;
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

code {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.72rem;
  color: #0f172a;
}

.mini {
  padding: 0.42rem 0.75rem;
  font-size: 0.76rem;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
