<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Search } from '@/components/icons'
import { sourceIcons, type CanvasAsset } from './model'

const props = defineProps<{ assets: CanvasAsset[]; remote?: (q: string, signal?: AbortSignal) => Promise<CanvasAsset[]> }>()
const emit = defineEmits<{ locate: [asset: CanvasAsset] }>()
const { t } = useI18n()
const search = shallowRef('')
const remoteMatches = shallowRef<CanvasAsset[]>([])
const loading = shallowRef(false)
const failed = shallowRef(false)
watch([search, () => props.remote], ([input, lookup], _, cleanup) => {
  const keyword = input.trim()
  remoteMatches.value = []
  failed.value = false
  loading.value = Boolean(keyword && lookup)
  if (!keyword || !lookup) return
  const controller = new AbortController()
  const timer = setTimeout(async () => {
    try {
      const result = await lookup(keyword, controller.signal)
      if (!controller.signal.aborted) remoteMatches.value = result
    } catch {
      if (!controller.signal.aborted) failed.value = true
    } finally {
      if (!controller.signal.aborted) loading.value = false
    }
  }, 180)
  cleanup(() => { clearTimeout(timer); controller.abort() })
})
const matches = computed(() => {
  const keyword = search.value.trim().toLocaleLowerCase()
  if (!keyword) return []
  const buckets: CanvasAsset[][] = [[], [], [], []]
  const candidates = new Map(props.assets.map(asset => [asset.node_id, asset]))
  for (const asset of remoteMatches.value) candidates.set(asset.node_id, asset)
  for (const asset of candidates.values()) {
    const title = asset.details.title.toLocaleLowerCase()
    const rank = title === keyword ? 0 : title.startsWith(keyword) ? 1
      : title.includes(keyword) ? 2 : asset.details.context?.toLocaleLowerCase().includes(keyword) ? 3 : -1
    const matches = buckets[rank]
    if (matches && matches.length < 12) matches.push(asset)
  }
  return buckets.flat().slice(0, 12)
})

function locate(asset?: CanvasAsset) {
  if (!asset) return
  emit('locate', asset)
  search.value = ''
}
</script>

<template>
  <div class="asset-search" @keydown.esc.stop="search = ''">
    <label class="search-box">
      <Search :size="16" />
      <input v-model="search" type="search" maxlength="120"
        :placeholder="t(remote ? 'workspace_canvas.domains.search_by_title' : 'workspace_canvas.search')"
        :aria-label="t('workspace_canvas.search')" @keydown.enter.prevent="locate(matches[0])" />
    </label>
    <ul v-if="search.trim()" class="search-results">
      <li v-for="item in matches" :key="item.node_id">
        <button class="locate-asset" type="button" :title="item.details.context || undefined" @click="locate(item)">
          <component :is="sourceIcons[item.reference.kind]" :size="16" /> <span>{{ item.details.title }}</span>
        </button>
      </li>
      <li v-if="loading || failed || !matches.length" class="no-match" role="status">
        {{ t(loading ? 'common.loading' : failed ? 'workspace_canvas.domains.lookup_failed' : 'workspace_canvas.no_results') }}
      </li>
    </ul>
  </div>
</template>

<style scoped>
.asset-search { position: relative; width: min(225px, 40vw); }
.search-box { display: flex; align-items: center; gap: 7px; min-height: 34px; padding: 0 9px; border-radius: 8px; border: 1px solid #e2e8f0; background: #f8fafc; color: #64748b; }
.search-box:focus-within { border-color: #0ea5e9; }
.search-box input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; font: inherit; font-size: 13px; color: #0f172a; }
.search-results { position: absolute; z-index: 9; inset: calc(100% + 4px) 0 auto; margin: 0; padding: 4px; max-height: 270px; overflow: auto; list-style: none; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; box-shadow: 0 8px 24px #0f172a1a; }
.search-results li { display: flex; align-items: stretch; }
.search-results button { display: flex; align-items: center; gap: 7px; min-height: 34px; padding: 5px 7px; border: 0; border-radius: 5px; text-align: start; font: inherit; font-size: 12px; color: #0369a1; background: transparent; cursor: pointer; }
.locate-asset { flex: 1; min-width: 0; }
.search-results button:hover, .search-results button:focus-visible { background: #e0f2fe; }
.search-results button span { overflow-wrap: anywhere; }
.no-match { color: #64748b; font-size: 12px; padding: 8px; }
</style>
