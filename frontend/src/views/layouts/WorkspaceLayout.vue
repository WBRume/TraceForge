<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '@/stores/workspace'
import { useLocalAgentStore } from '@/stores/localAgent'
import { LayoutDashboard, MessageSquare, Box, Settings, Network } from 'lucide-vue-next'
import AppSidebar from '@/components/AppSidebar.vue'
import WorkspaceRepoSetupDialog from '@/components/local-agent/WorkspaceRepoSetupDialog.vue'

const route = useRoute()
const router = useRouter()
const wsStore = useWorkspaceStore()
const localAgent = useLocalAgentStore()
const { electronAvailable } = storeToRefs(localAgent)
const { t } = useI18n()

const loading = ref(true)
const showRepoSetupDialog = ref(false)
let workspaceLoadSeq = 0

const maybePromptRepoSetup = async () => {
  const workspace = wsStore.currentWorkspace
  showRepoSetupDialog.value = false
  if (!workspace) return
  await localAgent.loadLocalConfig()
  await localAgent.setWorkspaceContext(workspace)
  if (!electronAvailable.value) return
  const hasRemotes = (
    String(workspace.git_repo_url || '').trim()
    || (Array.isArray(workspace.repositories) && workspace.repositories.length > 0)
  )
  if (!hasRemotes) return
  if (localAgent.missingRemotes.length === 0) return
  showRepoSetupDialog.value = true
}

const skipRepoSetup = () => {
  showRepoSetupDialog.value = false
}

const loadWorkspaceForRoute = async (wsId: string) => {
  const seq = ++workspaceLoadSeq
  loading.value = true
  showRepoSetupDialog.value = false
  if (!wsId) {
    loading.value = false
    return
  }
  if (!wsStore.currentWorkspace || wsStore.currentWorkspace.id !== wsId) {
    localStorage.setItem('sdd_ws_id', wsId)
    await wsStore.restoreCurrent()
  }
  if (seq !== workspaceLoadSeq) return
  loading.value = false
  await maybePromptRepoSetup()
}

watch(
  () => route.params.wsId,
  (value) => {
    void loadWorkspaceForRoute(String(value || ''))
  },
  { immediate: true },
)

const goBack = () => router.push('/workspaces')

const sidebarNavItems = computed(() => {
  const wsId = route.params.wsId as string
  const routeName = String(route.name ?? '')
  const assetsActive = routeName.startsWith('workspaceAssets') || routeName === 'workspaceAssetTaskDetail'
  return [
    {
      key: 'dashboard',
      label: t('layout.dashboard'),
      icon: LayoutDashboard,
      to: `/ws/${wsId}/dashboard`,
      active: routeName === 'dashboard',
    },
    {
      key: 'chat',
      label: t('layout.chat'),
      icon: MessageSquare,
      to: `/ws/${wsId}/chat`,
      active: routeName === 'chat' || routeName === 'taskChat' || routeName === 'taskSpec',
    },
    {
      key: 'assets',
      label: t('workspace_assets.sidebar_label'),
      icon: Box,
      to: `/ws/${wsId}/assets/requirements`,
      active: assetsActive,
    },
    {
      key: 'api-mock',
      label: t('layout.api_mock'),
      icon: Network,
      to: `/ws/${wsId}/api-mock`,
      active: routeName === 'apiMock',
    },
  ]
})

const sidebarFooterItems = computed(() => {
  const wsId = route.params.wsId as string
  const routeName = String(route.name ?? '')
  return [
    {
      key: 'settings',
      label: t('common.settings'),
      icon: Settings,
      to: `/ws/${wsId}/settings`,
      active: routeName === 'settings',
    },
  ]
})
</script>

<template>
  <div class="layout-container">
    <AppSidebar
      :title="wsStore.currentWorkspace?.name || 'Loading...'"
      :back-title="t('skills.list.back_to_workspaces')"
      :toggle-title="t('layout.toggle_sidebar')"
      :nav-items="sidebarNavItems"
      :footer-items="sidebarFooterItems"
      @back="goBack"
    />

    <!-- Main Content Area -->
    <main class="main-content">
      <router-view v-if="!loading" />
    </main>

    <WorkspaceRepoSetupDialog
      :show="showRepoSetupDialog"
      :workspace="wsStore.currentWorkspace"
      @close="showRepoSetupDialog = false"
      @skip="skipRepoSetup"
      @saved="showRepoSetupDialog = false"
    />
  </div>
</template>

<style scoped>
.layout-container {
  display: flex;
  height: 100vh;
  background-color: var(--color-bg-base);
  overflow: hidden;
}

.main-content {
  flex-grow: 1;
  overflow-y: auto;
  position: relative;
  /* Allow the router-view to fill the space */
  display: flex;
  flex-direction: column;
}
</style>
