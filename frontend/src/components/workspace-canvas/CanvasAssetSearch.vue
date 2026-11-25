<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Search } from '@/components/icons'
import { sourceIcons, type CanvasNode } from './model'

const props = defineProps<{ nodes: CanvasNode[] }>()
const emit = defineEmits<{ locate: [id: string] }>()
const { t } = useI18n()
const search = shallowRef('')
const matches = computed(() => {
  const keyword = search.value.trim().toLocaleLowerCase()
  if (!keyword) return []
  return props.nodes.filter(node => node.reference && node.details
    && [node.details.title, node.details.context].some(text => text?.toLocaleLowerCase().includes(keyword))).slice(0, 10)
})

function locate(id?: string) {
  if (!id) return
  emit('locate', id)
  search.value = ''
}
</script>

<template>
  <div class="asset-search" @keydown.esc.stop="search = ''">
    <label class="search-box">
      <Search :size="16" />
      <input v-model="search" type="search" maxlength="200" :placeholder="t('workspace_canvas.search')"
        :aria-label="t('workspace_canvas.search')" @keydown.enter.prevent="locate(matches[0]?.id)" />
    </label>
    <ul v-if="search.trim()" class="search-results">
      <li v-for="item in matches" :key="item.id">
        <button type="button" @click="locate(item.id)">
          <component :is="sourceIcons[item.reference!.kind]" :size="16" /> <span>{{ item.details?.title }}</span>
        </button>
      </li>
      <li v-if="!matches.length" class="no-match">{{ t('workspace_canvas.no_results') }}</li>
    </ul>
  </div>
</template>

<style scoped>
.asset-search { position: relative; width: min(225px, 40vw); }
.search-box { display: flex; align-items: center; gap: 7px; min-height: 34px; padding: 0 9px; border-radius: 8px; border: 1px solid #e2e8f0; background: #f8fafc; color: #64748b; }
.search-box:focus-within { border-color: #0ea5e9; }
.search-box input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; font: inherit; font-size: 13px; color: #0f172a; }
.search-results { position: absolute; z-index: 9; inset: calc(100% + 4px) 0 auto; margin: 0; padding: 4px; max-height: 270px; overflow: auto; list-style: none; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; box-shadow: 0 8px 24px #0f172a1a; }
.search-results button { display: flex; align-items: center; gap: 7px; width: 100%; min-height: 34px; padding: 5px 7px; border: 0; border-radius: 5px; text-align: start; font: inherit; font-size: 12px; color: #0369a1; background: transparent; cursor: pointer; }
.search-results button:hover, .search-results button:focus-visible { background: #e0f2fe; }
.search-results button span { overflow-wrap: anywhere; }
.no-match { color: #64748b; font-size: 12px; padding: 8px; }
</style>
