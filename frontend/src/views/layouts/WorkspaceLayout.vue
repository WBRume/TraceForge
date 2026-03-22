<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkspaceStore } from '@/stores/workspace'
import { LayoutDashboard, MessageSquare, Box, Settings, ArrowLeft } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const wsStore = useWorkspaceStore()

const loading = ref(true)

onMounted(async () => {
  const wsId = route.params.wsId as string
  if (!wsStore.currentWorkspace || wsStore.currentWorkspace.id !== wsId) {
    localStorage.setItem('sdd_ws_id', wsId)
    await wsStore.restoreCurrent()
  }
  loading.value = false
})

const goBack = () => router.push('/workspaces')
</script>

<template>
  <div class="layout-container">
    <!-- Sidebar -->
    <aside class="sidebar glass-panel">
      <div class="sidebar-header">
        <button class="back-btn" @click="goBack" title="Back to Workspaces">
          <ArrowLeft class="w-5 h-5" />
        </button>
        <span class="ws-name truncate">{{ wsStore.currentWorkspace?.name || 'Loading...' }}</span>
      </div>

      <nav class="sidebar-nav">
        <router-link :to="`/ws/${route.params.wsId}/dashboard`" class="nav-item" active-class="active">
          <LayoutDashboard class="w-5 h-5" />
          <span>Dashboard</span>
        </router-link>
        
        <router-link :to="`/ws/${route.params.wsId}/chat`" class="nav-item" active-class="active">
          <MessageSquare class="w-5 h-5" />
          <span>SDD Chat</span>
        </router-link>

        <router-link :to="`/ws/${route.params.wsId}/assets`" class="nav-item" active-class="active">
          <Box class="w-5 h-5" />
          <span>Assets</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div class="nav-item">
          <Settings class="w-5 h-5" />
          <span>Settings</span>
        </div>
      </div>
    </aside>

    <!-- Main Content Area -->
    <main class="main-content">
      <router-view v-if="!loading" />
    </main>
  </div>
</template>

<style scoped>
.layout-container {
  display: flex;
  height: 100vh;
  background-color: var(--color-bg-base);
  overflow: hidden;
}

.sidebar {
  width: 260px;
  display: flex;
  flex-direction: column;
  border-radius: 0 var(--radius-xl) var(--radius-xl) 0;
  margin-right: var(--space-1);
  box-shadow: 2px 0 10px rgba(0,0,0,0.02);
  z-index: 10;
}

.sidebar-header {
  padding: var(--space-6) var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border-bottom: 1px solid rgba(0,0,0,0.05);
}

.back-btn {
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
}

.back-btn:hover {
  background: rgba(0,0,0,0.05);
  color: var(--color-text-title);
}

.ws-name {
  font-weight: 600;
  color: var(--color-primary-900);
  font-size: 1rem;
}

.truncate {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar-nav {
  padding: var(--space-4) var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  flex-grow: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  color: var(--color-text-body);
  text-decoration: none;
  font-weight: 500;
  transition: all var(--transition-fast);
  cursor: pointer;
}

.nav-item:hover {
  background-color: var(--color-primary-50);
  color: var(--color-primary-600);
}

.nav-item.active {
  background-color: var(--color-primary-100);
  color: var(--color-primary-600);
  font-weight: 600;
}

.sidebar-footer {
  padding: var(--space-4) var(--space-2);
  border-top: 1px solid rgba(0,0,0,0.05);
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
