<script setup lang="ts">
import { RouterView } from 'vue-router'
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useProvisioningStore } from '@/stores/provisioning'
import ProvisionFloatingWidget from '@/components/ProvisionFloatingWidget.vue'

const authStore = useAuthStore()
const provisioningStore = useProvisioningStore()

onMounted(async () => {
  if (authStore.isAuthenticated) {
    await authStore.fetchCurrentUser()
    // 恢复当前用户（创建人）名下仍在进行的任务准备，浮窗状态跨刷新/新开应用保持
    await provisioningStore.restoreFromServer()
  }
})
</script>

<template>
  <RouterView />
  <ProvisionFloatingWidget />
</template>

<style>
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
