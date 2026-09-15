<script setup lang="ts">
import { computed, shallowRef, watch, onScopeDispose } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useDoubleShift } from '@/composables/useDoubleShift'
import { searchApi } from '@/services/searchApi'
import type { SearchCapabilities } from '@/types/search'
import GlobalSearchDialog from './GlobalSearchDialog.vue'
const auth = useAuthStore()
const open = shallowRef(false)
const capabilities = shallowRef<SearchCapabilities>({ enabled: false, ready: false, hybrid_available: false })
const enabled = computed(() => auth.isAuthenticated && capabilities.value.enabled)
let controller: AbortController | undefined
let generation = 0
const load = async () => {
  const token = ++generation
  controller?.abort()
  controller = new AbortController()
  open.value = false
  capabilities.value = { enabled: false, ready: false, hybrid_available: false }
  if (!auth.isAuthenticated) return
  try {
    const result = await searchApi.capabilities(controller.signal)
    if (token === generation) capabilities.value = result
  } catch { /* Search failure does not affect the application shell. */ }
}
watch(() => auth.token, load, { immediate: true })
window.addEventListener('sdd-server-changed', load)
onScopeDispose(() => { generation++; controller?.abort(); window.removeEventListener('sdd-server-changed', load) })
useDoubleShift(enabled, () => { open.value = true })
</script>
<template>
  <template v-if="enabled">
    <button class="global-search-trigger" title="搜索任务与历史消息（双击 Shift）" @click="open = true">搜索 <kbd>Shift × 2</kbd></button>
    <GlobalSearchDialog v-model="open" :capabilities="capabilities" />
  </template>
</template>
<style scoped>
.global-search-trigger { position: fixed; top: 12px; right: 20px; z-index: 100; display: flex; gap: 12px; align-items: center; padding: 7px 12px; border: 1px solid var(--el-border-color); border-radius: 7px; background: var(--el-bg-color); color: var(--el-text-color-primary); cursor: pointer; }
kbd { font-size: 11px; color: var(--el-text-color-secondary); }
:global(body:has(.global-search-trigger) .navbar), :global(body:has(.global-search-trigger) .chat-header) { padding-right: 156px; }
@media (max-width: 720px) {
  .global-search-trigger { right: 8px; padding: 7px; }
  kbd { display: none; }
  :global(body:has(.global-search-trigger) .navbar), :global(body:has(.global-search-trigger) .chat-header) { padding-right: 64px; }
}
</style>
