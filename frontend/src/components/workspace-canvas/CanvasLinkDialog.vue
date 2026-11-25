<script setup lang="ts">
import { computed, onScopeDispose, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
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
const options = computed(() => {
  const items = found.value ?? props.items
  const selected = chosen.value
  return selected && !items.some(item => item.reference.id === selected.reference.id) ? [selected, ...items] : items
})

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

onScopeDispose(() => request?.abort())
</script>

<template>
  <el-dialog :model-value="true" :title="title" width="min(530px, 95vw)" :close-on-click-modal="false"
    :show-close="!saving" :close-on-press-escape="!saving" append-to-body @close="emit('close')">
    <form class="link-form" @submit.prevent="save">
      <strong>{{ label }}</strong>
      <el-select v-model="target" filterable :remote="Boolean(props.lookup)" :remote-method="lookup" :loading="searching"
        :disabled="saving" :aria-label="t('workspace_canvas.menu.link_target')" @change="choose"
        :placeholder="t(props.lookup ? 'workspace_canvas.domains.search_by_title' : 'workspace_canvas.menu.link_target')">
        <el-option v-for="item in options" :key="item.reference.id" :value="item.reference.id" :label="item.details.title" />
      </el-select>
      <span v-if="searchFailed" role="status">{{ t('workspace_canvas.domains.lookup_failed') }}</span>
      <el-select v-if="!document" v-model="type" :disabled="saving" :aria-label="t('workspace_canvas.actions.relation_type')">
        <el-option value="COVERS" :label="t('workspace_assets.requirements.relation_types.covers_short')" />
        <el-option value="RELATES_TO" :label="t('workspace_assets.requirements.relation_types.relates_to_short')" />
      </el-select>
      <footer>
        <el-button :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" native-type="submit" :disabled="!target" :loading="saving">{{ t('common.confirm') }}</el-button>
      </footer>
    </form>
  </el-dialog>
</template>

<style scoped>
.link-form { display: grid; gap: 12px; }
footer { display: flex; justify-content: flex-end; }
</style>
