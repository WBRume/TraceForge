<script setup lang="ts">
import { RouterView } from 'vue-router'
import { onMounted, onUnmounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useProvisioningStore } from '@/stores/provisioning'
import { useNotificationStore } from '@/stores/notification'
import GlobalSearchHost from '@/components/global-search/GlobalSearchHost.vue'
import ProvisionFloatingWidget from '@/components/ProvisionFloatingWidget.vue'
import { useTaskAwarenessHost } from '@/composables/useTaskAwarenessHost'
import { useDesktopTabs } from '@/desktop/workspaceTabs'
import DesktopTitleBar from '@/components/desktop/DesktopTitleBar.vue'

const authStore = useAuthStore()
const provisioningStore = useProvisioningStore()
const notificationStore = useNotificationStore()
const desktopTabs = useDesktopTabs()
useTaskAwarenessHost()

// User notifications carry background-job updates across every application route.
watch(() => [authStore.token, authStore.user?.id] as const, ([token, userId]) => {
  notificationStore.reset()
  if (token && userId) notificationStore.start()
  void provisioningStore.restoreRevisionJobs(token && userId ? userId : '')
}, { immediate: true })
onUnmounted(() => notificationStore.stop())

onMounted(async () => {
  if (authStore.isAuthenticated) {
    if (!authStore.user) await authStore.fetchCurrentUser()
    // 恢复当前用户（创建人）名下仍在进行的任务准备，浮窗状态跨刷新/新开应用保持
    await provisioningStore.restoreFromServer()
  }
})
</script>

<template>
  <div v-if="desktopTabs" class="desktop-app">
    <DesktopTitleBar />
    <div id="desktop-workspace-panel" class="desktop-route" :role="desktopTabs.enabled.value ? 'tabpanel' : undefined">
      <RouterView />
    </div>
  </div>
  <RouterView v-else />
  <ProvisionFloatingWidget />
  <GlobalSearchHost />
</template>

<style>
.desktop-app {
  --desktop-titlebar-height: max(46px, env(titlebar-area-height, 0px));
  --app-viewport-height: calc(100dvh - var(--desktop-titlebar-height));
}
.desktop-route { position: relative; z-index: 0; height: var(--app-viewport-height); overflow: auto; }

/* 可以在此处添加全局过渡效果 */
.v-enter-active,
.v-leave-active {
  transition: opacity 0.3s ease;
}

.v-enter-from,
.v-leave-to {
  opacity: 0;
}
</style>
