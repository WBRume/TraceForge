<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import { Plus, Briefcase, LogOut, Trash2, AlertTriangle, Languages, BookCopy } from 'lucide-vue-next'
import api from '@/utils/api'

const { locale } = useI18n()
const router = useRouter()
const wsStore = useWorkspaceStore()
const authStore = useAuthStore()

const toggleLanguage = () => {
  const newLang = locale.value === 'zh' ? 'en' : 'zh'
  locale.value = newLang
  localStorage.setItem('sdd_lang', newLang)
}

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

const openSkillsConfig = (ws: any) => {
  wsStore.setCurrent(ws)
  router.push({ path: '/skills', query: { wsId: ws.id } })
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
      <div class="header-right">
        <div class="user-info">
          <span class="username">{{ authStore.user?.display_name }}</span>
          <button class="icon-btn" @click="logout" :title="$t('common.logout')">
            <LogOut class="w-5 h-5" />
          </button>
        </div>
        <div class="v-divider"></div>
        <!-- Language Switcher -->
        <button class="lang-switch-btn" @click="toggleLanguage" :title="$t('portal.switch_lang_title')">
          <Languages class="w-4 h-4" />
          <span>{{ locale === 'zh' ? 'EN' : 'ZH' }}</span>
        </button>
      </div>
    </nav>

    <main class="ws-main">
      <div class="ws-header-row">
        <h2 class="title-gradient-small">{{ $t('workspaces.title') }}</h2>
        <div class="flex items-center gap-2">
          <button
            v-if="wsStore.workspaces.length > 0"
            class="btn-secondary flex items-center gap-2"
            @click="openSkillsConfig(wsStore.workspaces[0])"
          >
            <BookCopy class="w-4 h-4" /> {{ $t('skills.entry') }}
          </button>
          <button class="btn-primary flex items-center gap-2" @click="showCreateModal = true">
            <Plus class="w-4 h-4" /> {{ $t('workspaces.new_workspace') }}
          </button>
        </div>
      </div>

      <div v-if="loading" class="loading-state">{{ $t('workspaces.loading') }}</div>
      
      <div v-else-if="wsStore.workspaces.length === 0" class="empty-state glass-panel">
        <Briefcase class="w-12 h-12 text-muted mb-4" />
        <h3>{{ $t('workspaces.no_workspaces') }}</h3>
        <p>{{ $t('workspaces.empty_desc') }}</p>
        <button class="btn-primary mt-4" @click="showCreateModal = true">{{ $t('workspaces.create_button') }}</button>
      </div>

      <div v-else class="ws-grid">
        <div 
          v-for="(ws, index) in wsStore.workspaces" 
          :key="ws.id" 
          class="ws-card glass-panel group hover-lift animate-pop-in"
          :style="{ animationDelay: `${index * 50}ms` }"
          @click="enterWorkspace(ws)"
        >
          <div class="ws-card-header flex justify-between items-start">
            <h3>{{ ws.name }}</h3>
            <button class="delete-ws-btn opacity-0 group-hover:opacity-100 transition-all hover:bg-rose-500 hover:text-white hover:shadow-lg hover:shadow-rose-500/30" @click.stop="handleDeleteWorkspace(ws)">
              <Trash2 class="w-4 h-4" />
            </button>
          </div>
          <p class="ws-card-desc">{{ ws.description || $t('workspaces.no_desc') }}</p>
          <div class="ws-card-footer">
            <span class="text-xs text-muted">{{ $t('workspaces.created_at', { date: new Date(ws.created_at).toLocaleDateString(locale) }) }}</span>
          </div>
        </div>
      </div>
    </main>

    <!-- Modal -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
      <div class="modal glass-panel">
        <h3>{{ $t('workspaces.new_workspace') }}</h3>
        <form @submit.prevent="handleCreate" class="mt-4 flex flex-col gap-4">
          <div class="form-group flex flex-col gap-2">
            <label>{{ $t('workspaces.modal.name') }}</label>
            <input v-model="newWsName" type="text" class="input-field" required :placeholder="$t('workspaces.modal.name_placeholder')">
          </div>
          <div class="form-group flex flex-col gap-2">
            <label>{{ $t('workspaces.modal.desc') }}</label>
            <textarea v-model="newWsDesc" class="input-field" rows="2" :placeholder="$t('workspaces.modal.desc_placeholder')"></textarea>
          </div>
          <div class="form-group flex flex-col gap-2">
            <label>{{ $t('workspaces.modal.path') }}</label>
            <input v-model="newWsPath" type="text" class="input-field" required :placeholder="$t('workspaces.modal.path_placeholder')">
          </div>
          <div class="form-group flex flex-col gap-2">
            <label>{{ $t('workspaces.modal.git') }}</label>
            <input v-model="newWsGit" type="text" class="input-field" :placeholder="$t('workspaces.modal.git_placeholder')">
          </div>
          <div class="flex justify-end gap-3 mt-4">
            <button type="button" class="btn-secondary" @click="showCreateModal = false">{{ $t('common.cancel') }}</button>
            <button type="submit" class="btn-primary" :disabled="creating">
              {{ creating ? $t('workspaces.modal.creating') : $t('common.confirm') }}
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
          <span class="text-xl font-bold leading-none">{{ $t('workspaces.delete_ws') }}</span>
        </div>
        <p class="text-sm text-slate-600 mb-6">
          {{ $t('workspaces.delete_confirm', { name: wsToDelete?.name }) }}
          <br/><br/>
          {{ $t('workspaces.delete_warning') }}
        </p>
        <div class="flex justify-end gap-3">
          <button class="btn-secondary" @click="showDeleteConfirm = false">{{ $t('workspaces.keep_it') }}</button>
          <button class="btn-primary bg-rose-500 border-rose-600 hover:shadow-rose-lg" @click="confirmDeleteWorkspace">
            {{ $t('workspaces.delete_permanently') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap');

.ws-container {
  min-height: 100vh;
  background-color: var(--color-bg-base);
  font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
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
  gap: 0.5rem;
  font-weight: 500;
  color: var(--color-text-body);
}

.username {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
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
  font-size: 1.75rem;
  font-weight: 800;
  background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
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
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  position: relative;
  overflow: hidden;
}

.ws-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, #0ea5e9, #3b82f6);
  opacity: 0;
  transition: opacity 0.3s;
}

.ws-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 20px 25px -5px rgba(14, 165, 233, 0.1), 0 10px 10px -5px rgba(14, 165, 233, 0.04);
  border-color: rgba(14, 165, 233, 0.3);
}

.ws-card:hover::before {
  opacity: 1;
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
  background: #f1f5f9;
  border: none;
  cursor: pointer;
  padding: 6px;
  border-radius: 8px;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
}

.delete-ws-btn:hover {
  background-color: #ef4444 !important;
  color: white !important;
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.3);
  transform: translateY(-2px);
}

.ws-card-footer {
  margin-top: auto;
  padding-top: var(--space-4);
  border-top: 1px solid rgba(0,0,0,0.05);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
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
.header-right {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.v-divider {
  width: 1px;
  height: 20px;
  background-color: var(--color-border);
  opacity: 0.5;
}

.lang-switch-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid var(--color-border);
  padding: 0.4rem 0.75rem;
  border-radius: var(--radius-md);
  color: var(--color-text-body);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 0.8125rem;
}

.lang-switch-btn:hover {
  background: white;
  border-color: var(--color-primary-500);
  color: var(--color-primary-500);
}

/* Animations */
@keyframes popIn {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.animate-pop-in {
  animation: popIn 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
}
</style>
