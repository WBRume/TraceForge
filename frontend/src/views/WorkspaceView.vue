<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import { Plus, Briefcase, LogOut, Trash2, AlertTriangle } from 'lucide-vue-next'
import api from '@/utils/api'

const router = useRouter()
const wsStore = useWorkspaceStore()
const authStore = useAuthStore()

const loading = ref(true)
const showCreateModal = ref(false)
const newWsName = ref('')
const newWsDesc = ref('')
const newWsPath = ref('')
const newWsGit = ref('')
const creating = ref(false)
const showDeleteConfirm = ref(false)
const wsToDelete = ref<any>(null)

onMounted(async () => {
  await wsStore.fetchWorkspaces()
  loading.value = false
})

const enterWorkspace = (ws: any) => {
  wsStore.setCurrent(ws)
  router.push(`/ws/${ws.id}/dashboard`)
}

const handleCreate = async () => {
  if (!newWsName.value) return
  creating.value = true
  try {
    const res = await api.post('/workspaces', {
      name: newWsName.value,
      description: newWsDesc.value,
      project_path: newWsPath.value,
      git_repo_url: newWsGit.value
    })
    await wsStore.fetchWorkspaces()
    showCreateModal.value = false
    enterWorkspace(res.data)
  } catch (e) {
    console.error('Failed to create workspace', e)
  } finally {
    creating.value = false
  }
}

const logout = () => {
  authStore.logout()
}

const handleDeleteWorkspace = (ws: any) => {
  wsToDelete.value = ws
  showDeleteConfirm.value = true
}

const confirmDeleteWorkspace = async () => {
  if (!wsToDelete.value) return
  try {
    await api.delete(`/workspaces/${wsToDelete.value.id}`)
    showDeleteConfirm.value = false
    wsToDelete.value = null
    await wsStore.fetchWorkspaces()
  } catch (e) {
    console.error('Failed to delete workspace', e)
  }
}
</script>

<template>
  <div class="ws-container">
    <nav class="ws-header glass-panel">
      <div class="logo">SDD Native</div>
      <div class="user-info">
        <span>{{ authStore.user?.display_name }}</span>
        <button class="icon-btn" @click="logout" title="Logout">
          <LogOut class="w-5 h-5" />
        </button>
      </div>
    </nav>

    <main class="ws-main">
      <div class="ws-header-row">
        <h2>Your Workspaces</h2>
        <button class="btn-primary flex items-center gap-2" @click="showCreateModal = true">
          <Plus class="w-4 h-4" /> New Workspace
        </button>
      </div>

      <div v-if="loading" class="loading-state">Loading workspaces...</div>
      
      <div v-else-if="wsStore.workspaces.length === 0" class="empty-state glass-panel">
        <Briefcase class="w-12 h-12 text-muted mb-4" />
        <h3>No Workspaces Yet</h3>
        <p>Create your first workspace to start generating code.</p>
        <button class="btn-primary mt-4" @click="showCreateModal = true">Create Workspace</button>
      </div>

      <div v-else class="ws-grid">
        <div 
          v-for="ws in wsStore.workspaces" 
          :key="ws.id" 
          class="ws-card glass-panel group relative"
          @click="enterWorkspace(ws)"
        >
          <div class="ws-card-header flex justify-between items-start">
            <h3>{{ ws.name }}</h3>
            <button class="delete-ws-btn opacity-0 group-hover:opacity-100 transition-opacity" @click.stop="handleDeleteWorkspace(ws)">
              <Trash2 class="w-4 h-4 text-slate-400 hover:text-rose-500" />
            </button>
          </div>
          <p class="ws-card-desc">{{ ws.description || 'No description provided.' }}</p>
          <div class="ws-card-footer">
            <span class="text-xs text-muted">Created {{ new Date(ws.created_at).toLocaleDateString() }}</span>
          </div>
        </div>
      </div>
    </main>

    <!-- Modal -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
      <div class="modal glass-panel">
        <h3>Create Workspace</h3>
        <form @submit.prevent="handleCreate" class="mt-4 flex flex-col gap-4">
          <div class="form-group flex flex-col gap-2">
            <label>Name</label>
            <input v-model="newWsName" type="text" class="input-field" required placeholder="e.g. Acme E-Commerce">
          </div>
          <div class="form-group flex flex-col gap-2">
            <label>Description (Optional)</label>
            <textarea v-model="newWsDesc" class="input-field" rows="2" placeholder="What is this project about?"></textarea>
          </div>
          <div class="form-group flex flex-col gap-2">
            <label>Generation Path (Mandatory)</label>
            <input v-model="newWsPath" type="text" class="input-field" required placeholder="e.g. /home/user/projects/my-app">
          </div>
          <div class="form-group flex flex-col gap-2">
            <label>GitHub Repo URL (Optional)</label>
            <input v-model="newWsGit" type="text" class="input-field" placeholder="e.g. https://github.com/user/repo">
          </div>
          <div class="flex justify-end gap-3 mt-4">
            <button type="button" class="btn-secondary" @click="showCreateModal = false">Cancel</button>
            <button type="submit" class="btn-primary" :disabled="creating">
              {{ creating ? 'Creating...' : 'Create' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div v-if="showDeleteConfirm" class="modal-overlay" @click.self="showDeleteConfirm = false">
      <div class="modal glass-panel" style="border-top: 4px solid var(--color-accent-rose)">
        <div class="flex items-center gap-3 mb-4 text-rose-600">
          <AlertTriangle class="w-6 h-6 flex-shrink-0" />
          <span class="text-xl font-bold leading-none">Delete Workspace?</span>
        </div>
        <p class="text-sm text-slate-600 mb-6">
          Are you sure you want to delete <strong>{{ wsToDelete?.name }}</strong>?
          <br/><br/>
          This will permanently remove all associated tasks, logs, and assets. This action cannot be undone.
        </p>
        <div class="flex justify-end gap-3">
          <button class="btn-secondary" @click="showDeleteConfirm = false">Keep It</button>
          <button class="btn-primary bg-rose-500 border-rose-600 hover:shadow-rose-lg" @click="confirmDeleteWorkspace">
            Delete Permanently
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ws-container {
  min-height: 100vh;
  background-color: var(--color-bg-base);
}

.ws-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) var(--space-8);
  margin-bottom: var(--space-8);
  border-radius: 0 0 var(--radius-xl) var(--radius-xl);
}

.logo {
  font-family: var(--font-heading);
  font-weight: 700;
  font-size: 1.25rem;
  color: var(--color-primary-600);
}

.user-info {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  font-weight: 500;
}

.icon-btn {
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: color var(--transition-fast);
  padding: 4px;
}

.icon-btn:hover {
  color: var(--color-accent-rose);
}

.ws-main {
  max-width: 1000px;
  margin: 0 auto;
  padding: 0 var(--space-8);
}

.ws-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-6);
}

.ws-header-row h2 {
  margin: 0;
  font-size: 1.5rem;
}

.ws-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--space-6);
}

.ws-card {
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  cursor: pointer;
  min-height: 160px;
}

.ws-card-header h3 {
  margin: 0;
  font-size: 1.25rem;
  color: var(--color-primary-900);
}

.ws-card-desc {
  color: var(--color-text-body);
  flex-grow: 1;
  font-size: 0.95rem;
}

.group:hover .group-hover\:opacity-100 {
  opacity: 1;
}

.delete-ws-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 4px;
}

.ws-card-footer {
  margin-top: auto;
  padding-top: var(--space-4);
  border-top: 1px solid rgba(0,0,0,0.05);
}

.text-muted { color: var(--color-text-muted); }

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12);
  text-align: center;
}

/* Flex Utilities for convenience */
.flex { display: flex; }
.flex-col { flex-direction: column; }
.items-center { align-items: center; }
.justify-between { justify-content: space-between; }
.justify-end { justify-content: flex-end; }
.justify-center { justify-content: center; }
.gap-2 { gap: var(--space-2); }
.gap-3 { gap: var(--space-3); }
.gap-4 { gap: var(--space-4); }
.mt-4 { margin-top: var(--space-4); }
.mb-4 { margin-bottom: var(--space-4); }
.text-xs { font-size: 0.75rem; }
.leading-6 { line-height: 1.5rem; }
.leading-none { line-height: 1; }
.font-bold { font-weight: 700; }
.text-xl { font-size: 1.25rem; }

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.modal {
  width: 90%;
  max-width: 500px;
  padding: var(--space-8);
  background-color: var(--color-surface-white);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-2xl);
}

.modal h3 {
  margin: 0 0 var(--space-4);
}

.input-field {
  padding: 10px 14px;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  font-family: inherit;
  font-size: 1rem;
  width: 100%;
}

.input-field:focus {
  border-color: var(--color-primary-500);
  outline: none;
}
</style>
