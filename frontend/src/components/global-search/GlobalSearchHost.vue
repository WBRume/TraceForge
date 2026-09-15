<script setup lang="ts">
import { watch, onScopeDispose, toRef } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useGlobalSearchStore } from '@/stores/globalSearch'
import { useDoubleShift } from '@/composables/useDoubleShift'
import GlobalSearchDialog from './GlobalSearchDialog.vue'
import GlobalPinnedFloatsWidget from './GlobalPinnedFloatsWidget.vue'

const auth = useAuthStore()
const searchStore = useGlobalSearchStore()

watch(() => auth.token, () => {
  searchStore.loadCapabilities()
}, { immediate: true })

const onServerChanged = () => {
  searchStore.loadCapabilities()
}

window.addEventListener('sdd-server-changed', onServerChanged)
onScopeDispose(() => {
  window.removeEventListener('sdd-server-changed', onServerChanged)
})

// 全局双击 Shift 快捷键唤起
useDoubleShift(toRef(searchStore, 'enabled'), () => {
  searchStore.openSearch()
})
</script>

<template>
  <!-- 全局搜索弹窗 -->
  <GlobalSearchDialog
    v-if="searchStore.enabled"
    v-model="searchStore.isOpen"
    :capabilities="searchStore.capabilities"
  />

  <!-- 钉在窗口中的浮窗（会话简易面板、消息快照），认证后常驻 -->
  <GlobalPinnedFloatsWidget v-if="auth.isAuthenticated" />
</template>
