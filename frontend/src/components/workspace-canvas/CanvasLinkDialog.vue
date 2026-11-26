<script setup lang="ts">
import { computed, onScopeDispose, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import type { RequirementTaskRelation } from '@/types/workspaceAssets'
import type { SourceItem } from './model'

const props = defineProps<{ title: string; label: string; items: SourceItem[]; document: boolean; saving: boolean;
  lookup?: (query: string, signal: AbortSignal) => Promise<SourceItem[]> }>()
const emit = defineEmits<{ close: []; save: [id: string, type: RequirementTaskRelation] }>()
const { t } = useI18n()
const target = shallowRef('')
const type = shallowRef<RequirementTaskRelation>('COVERS')
const found = shallowRef<SourceItem[] | null>(null)
const chosen = shallowRef<SourceItem>()
const searching = shallowRef(false)
const searchFailed = shallowRef(false)
let request: AbortController | undefined
let searchTimer: ReturnType<typeof setTimeout> | undefined
const options = computed(() => {
  const items = found.value ?? props.items
  const selected = chosen.value
  return selected && !items.some(item => item.reference.id === selected.reference.id) ? [selected, ...items] : items
})
const targetOptions = computed(() => options.value.map(item => ({ value: item.reference.id, label: item.details.title })))
const relationOptions = computed(() => [
  { value: 'COVERS', label: t('workspace_assets.requirements.relation_types.covers_short') },
  { value: 'RELATES_TO', label: t('workspace_assets.requirements.relation_types.relates_to_short') },
])

function search(query: string) {
  clearTimeout(searchTimer)
  request?.abort()
  searchTimer = setTimeout(() => void lookup(query), query ? 180 : 0)
}

async function lookup(input: string) {
  request?.abort()
  request = undefined
  searching.value = false
  searchFailed.value = false
  const query = input.trim().slice(0, 120)
  if (!query || !props.lookup) { found.value = null; return }
  const controller = new AbortController()
  request = controller
  searching.value = true
  try {
    const items = await props.lookup(query, controller.signal)
    if (!controller.signal.aborted) found.value = items
  } catch {
    if (!controller.signal.aborted) searchFailed.value = true
  } finally {
    if (request === controller) { request = undefined; searching.value = false }
  }
}

function choose(id: string) {
  chosen.value = options.value.find(item => item.reference.id === id)
}

function save() {
  if (target.value && options.value.some(item => item.reference.id === target.value)) emit('save', target.value, type.value)
}

onScopeDispose(() => { clearTimeout(searchTimer); request?.abort() })
</script>

<template>
  <el-dialog :model-value="true" class="canvas-dialog" :title="title" width="min(530px, 95vw)" :close-on-click-modal="false"
    :show-close="!saving" :close-on-press-escape="!saving" append-to-body @close="emit('close')">
    <div class="link-form">
      <strong>{{ label }}</strong>
      <BaseSelect v-model="target" :options="targetOptions" searchable :remote-search="Boolean(props.lookup)"
        :disabled="saving" :aria-label="t('workspace_canvas.menu.link_target')" @update:model-value="choose"
        :placeholder="t('workspace_canvas.menu.link_target')" :search-placeholder="t('workspace_canvas.domains.search_by_title')"
        @open="search('')" @search="search" />
      <span v-if="searching" role="status">{{ t('common.loading') }}</span>
      <span v-if="searchFailed" role="status">{{ t('workspace_canvas.domains.lookup_failed') }}</span>
      <BaseSelect v-if="!document" v-model="type" :options="relationOptions" :disabled="saving"
        :aria-label="t('workspace_canvas.actions.relation_type')" />
    </div>
    <template #footer>
      <el-button :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :disabled="!target" :loading="saving" @click="save">{{ t('common.confirm') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.link-form { display: grid; gap: 12px; }
</style>
