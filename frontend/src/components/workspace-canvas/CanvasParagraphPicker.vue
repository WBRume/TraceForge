<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Search, X } from '@/components/icons'
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
  <aside class="paragraph-picker" :aria-label="t('workspace_canvas.pin')">
    <header class="picker-head"><strong :title="title">{{ title }}</strong>
      <button type="button" class="picker-icon" :aria-label="t('common.close')" @click="emit('close')"><X :size="17" /></button>
    </header>
    <label class="paragraph-search"><Search :size="16" />
      <input v-model="query" type="search" maxlength="200" :aria-label="t('workspace_canvas.search_paragraphs')"
        :placeholder="t('workspace_canvas.search_paragraphs')" />
    </label>
    <div class="paragraph-list" :aria-busy="loading">
      <button v-for="item in items" :key="referenceKey(item.reference)" class="paragraph-row" type="button" :disabled="disabled" @click="emit('add', item)">
        <span>{{ item.details.detail }}</span><Plus :size="16" />
      </button>
      <p v-if="loading" class="picker-state" role="status">{{ t('common.loading') }}</p>
      <div v-else-if="error" class="picker-state" role="alert">{{ error }}
        <button type="button" class="more-paragraphs" @click="load(items.length ? page + 1 : 1, owner)">{{ t('workspace_canvas.retry') }}</button>
      </div>
      <p v-else-if="!items.length" class="picker-state">{{ t('workspace_canvas.no_paragraphs') }}</p>
      <button v-else-if="hasMore" type="button" class="more-paragraphs" @click="load(page + 1, owner)">{{ t('workspace_canvas.more') }}</button>
    </div>
  </aside>
</template>

<style scoped>
.paragraph-picker { position: absolute; z-index: 6; top: 61px; right: 12px; width: min(328px, calc(100% - 70px)); max-height: calc(100% - 94px); padding: 12px; display: flex; flex-direction: column; gap: 8px; background: var(--canvas-chrome); border: 1px solid var(--canvas-line); border-radius: 11px; box-shadow: 0 12px 32px #0f172a24; }
.picker-head, .paragraph-search { display: flex; align-items: center; gap: 6px; }
.picker-head strong { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.picker-icon { display: grid; place-items: center; border: 0; background: transparent; padding: 4px; color: var(--canvas-muted); cursor: pointer; }
.paragraph-search { padding: 0 7px; border: 1px solid var(--canvas-line); border-radius: 7px; background: var(--canvas-paper); color: var(--canvas-muted); }
.paragraph-search input { width: 100%; min-width: 0; border: 0; outline: 0; padding: 6px 0; color: var(--canvas-ink); background: transparent; font: inherit; font-size: 12px; }
.paragraph-list { overflow: auto; min-height: 0; }
.paragraph-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; border: 0; border-radius: 6px; padding: 7px; color: var(--canvas-ink); background: transparent; font: inherit; font-size: 12px; line-height: 1.5; text-align: start; cursor: pointer; }
.paragraph-row svg { flex: 0 0 auto; color: var(--canvas-accent); }
.paragraph-row:hover, .paragraph-row:focus-visible { background: var(--canvas-hover); }
.picker-state { margin: 4px 0; text-align: center; color: var(--canvas-muted); font-size: 12px; }
.more-paragraphs { display: block; margin: 6px auto; border: 1px solid var(--canvas-line); border-radius: 5px; padding: 4px 6px; background: transparent; color: var(--canvas-accent); font: inherit; font-size: 12px; cursor: pointer; }
</style>
