<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ServerCog } from 'lucide-vue-next'
import { useWorkspaceStore } from '@/stores/workspace'
import AppSidebar from '@/components/AppSidebar.vue'
import WorkspaceQueueTab from '@/components/workspace/WorkspaceQueueTab.vue'

const router = useRouter()
const wsStore = useWorkspaceStore()
const { t } = useI18n()

const goWorkspaces = () => {
  router.push('/workspaces')
}

const sidebarNavItems = computed(() => [
  {
    key: 'queue-ops',
    label: t('queue_ops.title'),
    icon: ServerCog,
    active: true,
    noClick: true,
  },
])

onMounted(async () => {
  await wsStore.fetchWorkspaces()
})
</script>

<template>
  <div class="queue-page">
    <AppSidebar
      :title="t('queue_ops.title')"
      :back-title="t('queue_ops.back_workspaces')"
      :nav-items="sidebarNavItems"
      @back="goWorkspaces"
    />

    <main class="queue-main">
      <WorkspaceQueueTab :workspaces="wsStore.workspaces" />
    </main>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');

.queue-page {
  display: flex;
  height: 100vh;
  background-color: var(--color-bg-base);
  font-family: 'Open Sans', sans-serif;
  overflow: hidden;
}

.queue-main {
  flex-grow: 1;
  overflow-y: auto;
  padding: 2rem;
}
</style>

