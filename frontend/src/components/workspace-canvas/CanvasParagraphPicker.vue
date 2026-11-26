<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Search } from '@/components/icons'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { canvasUrl, referenceKey, type DocumentReference, type SourceItem, type SourcePage } from './model'

const props = defineProps<{ workspaceId: string; reference: DocumentReference; title: string; disabled: boolean }>()
const emit = defineEmits<{ add: [item: SourceItem]; close: [] }>()
const { t } = useI18n()
const query = shallowRef('')
const items = shallowRef<SourceItem[]>([])
const loading = shallowRef(false)
const error = shallowRef('')
const hasMore = shallowRef(false)
let page = 1
let owner: AbortController

async function load(next: number, request: AbortController) {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.post<SourcePage>(`${canvasUrl(props.workspaceId)}/paragraphs`, props.reference, {
      params: { page: next, q: query.value.trim() }, signal: request.signal,
    })
    if (request.signal.aborted) return
    items.value = next === 1 ? data.items : [...items.value, ...data.items]
    page = next
    hasMore.value = data.has_more
  } catch (cause) {
    if (!request.signal.aborted) error.value = formatApiError(cause, t('workspace_canvas.catalog_failed'), t)
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}

watch(query, (_value, previous, cleanup) => {
  const request = new AbortController()
  owner = request
  items.value = []
  loading.value = true
  hasMore.value = false
  const timer = setTimeout(() => void load(1, request), previous === undefined ? 0 : 180)
  cleanup(() => { clearTimeout(timer); request.abort() })
}, { immediate: true })
</script>

<template>
  <el-dialog :model-value="true" :title="t('workspace_canvas.pin')" width="min(640px, 95vw)" append-to-body
    :close-on-click-modal="false" :show-close="!disabled" :close-on-press-escape="!disabled" @close="emit('close')">
    <div class="paragraph-picker">
      <strong>{{ title }}</strong>
      <el-input v-model="query" :prefix-icon="Search" clearable maxlength="200"
        :aria-label="t('workspace_canvas.search_paragraphs')" :placeholder="t('workspace_canvas.search_paragraphs')" />
      <div class="paragraph-list" :aria-busy="loading">
        <button v-for="item in items" :key="referenceKey(item.reference)" class="paragraph-row" type="button"
          :disabled="disabled" @click="emit('add', item)">
          <span>{{ item.details.detail }}</span><Plus :size="16" />
        </button>
        <p v-if="loading" class="picker-state" role="status">{{ t('common.loading') }}</p>
        <div v-else-if="error" class="picker-state" role="alert">{{ error }}
          <el-button link type="primary" @click="load(items.length ? page + 1 : 1, owner)">{{ t('workspace_canvas.retry') }}</el-button>
        </div>
        <p v-else-if="!items.length" class="picker-state">{{ t('workspace_canvas.no_paragraphs') }}</p>
        <el-button v-else-if="hasMore" link type="primary" @click="load(page + 1, owner)">{{ t('workspace_canvas.more') }}</el-button>
      </div>
    </div>
    <template #footer>
      <el-button :disabled="disabled" @click="emit('close')">{{ t('common.close') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.paragraph-picker { display: grid; gap: 12px; }
.paragraph-list { overflow: auto; max-height: 48vh; }
.paragraph-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; border: 0;
  border-bottom: 1px solid #f1f5f9; padding: 10px; color: #1e293b; background: transparent; font: inherit;
  line-height: 1.5; text-align: start; cursor: pointer; }
.paragraph-row svg { flex: 0 0 auto; color: var(--el-color-primary); }
.paragraph-row:not(:disabled):is(:hover, :focus-visible) { background: #f0f9ff; }
.paragraph-row:disabled { cursor: wait; }
.picker-state { margin: 6px 0; text-align: center; color: #64748b; }
</style>
