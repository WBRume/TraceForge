<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import { Plus, Briefcase, Languages, Package, FolderKanban, GitFork, Settings2, ServerCog, LibraryBig } from 'lucide-vue-next'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import WorkspaceCreateWorkflowDialog from '@/components/workspace/create-workflow/WorkspaceCreateWorkflowDialog.vue'
import api from '@/utils/api'
import UserIdentityBadge from '@/components/user/UserIdentityBadge.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'

const { locale } = useI18n()
const router = useRouter()
const wsStore = useWorkspaceStore()
const authStore = useAuthStore()

/**
 * Summarize an array of items into a compact label list, e.g.
 * "repo-a, repo-b +2" when there are more than `max` items.
 */
const summarize = (items: any[] | undefined, labelOf: (item: any) => string, max = 2) => {
  const labels = (items || []).map(labelOf).filter((label) => label)
  if (labels.length === 0) return ''
  const shown = labels.slice(0, max)
  const extra = labels.length - shown.length
  return extra > 0 ? `${shown.join(', ')} +${extra}` : shown.join(', ')
}

const productLabel = (product: any) =>
  product?.version_no ? `${product.name} (${product.version_no})` : product?.name

const toggleLanguage = () => {
  const newLang = locale.value === 'zh' ? 'en' : 'zh'
  locale.value = newLang
  localStorage.setItem('sdd_lang', newLang)
}

const loading = ref(true)
const showCreateModal = ref(false)
const showDeleteConfirm = ref(false)
const deletingWorkspace = ref(false)
const wsToDelete = ref<any>(null)

onMounted(async () => {
  await wsStore.fetchWorkspaces()
  loading.value = false
})

const enterWorkspace = (ws: any) => {
  wsStore.setCurrent(ws)
  router.push(`/ws/${ws.id}/dashboard`)
}

const handleWorkspaceCreated = async (jobId: string) => {
  showCreateModal.value = false
  await router.push({
    path: '/ops/queue/provision/' + jobId,
  })
}

const logout = () => {
  authStore.logout()
}

const handleDeleteWorkspace = (ws: any) => {
  if (!ws?.can_delete_workspace) return
  wsToDelete.value = ws
  showDeleteConfirm.value = true
}

const closeDeleteWorkspaceModal = () => {
  if (deletingWorkspace.value) return
  showDeleteConfirm.value = false
  wsToDelete.value = null
}

const confirmDeleteWorkspace = async () => {
  if (!wsToDelete.value) return
  deletingWorkspace.value = true
  try {
    await api.delete(`/workspaces/${wsToDelete.value.id}`)
    await wsStore.fetchWorkspaces()
  } catch (e) {
    console.error('Failed to delete workspace', e)
  } finally {
    deletingWorkspace.value = false
    showDeleteConfirm.value = false
    wsToDelete.value = null
  }
}
</script>

<template>
  <div class="ws-container">
    <nav class="navbar">
      <div class="logo">
        <div class="logo-icon"></div>
        <router-link to="/" class="logo-link logo-text">{{ $t('portal.title') }}</router-link>
      </div>
      <div class="nav-links">
        <UserIdentityBadge
          :display-name="authStore.user?.display_name"
          :email="authStore.user?.email"
          :user-id="authStore.user?.id"
          :avatar-svg="authStore.user?.avatar_svg"
          :avatar-url="authStore.user?.avatar_url"
          size="sm"
        />
        <button class="btn-ghost" @click="logout">{{ $t('common.logout') }}</button>
        <div class="v-divider"></div>
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
            class="btn-secondary flex items-center gap-2"
            @click="router.push('/management')"
          >
            <Settings2 class="w-4 h-4" /> {{ $t('management.entry_config_center') }}
          </button>
          <button
            class="btn-secondary flex items-center gap-2"
            @click="router.push('/ops')"
          >
            <ServerCog class="w-4 h-4" /> {{ $t('management.entry_ops_center') }}
          </button>
          <button
            class="btn-secondary flex items-center gap-2"
            @click="router.push('/knowledge')"
          >
            <LibraryBig class="w-4 h-4" /> {{ $t('management.entry_knowledge_center') }}
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
            <DeleteActionButton
              mode="icon"
              class="opacity-0 group-hover:opacity-100 transition-all"
              :title="$t('common.delete')"
              :disabled="!ws.can_delete_workspace"
              @click.stop="handleDeleteWorkspace(ws)"
            />
          </div>
          <p class="ws-card-desc">{{ ws.description || $t('workspaces.no_desc') }}</p>
          <div class="ws-card-meta">
            <div class="ws-meta-row" :title="ws.project?.name">
              <FolderKanban class="ws-meta-icon" />
              <span class="ws-meta-label">{{ $t('workspaces.card_project') }}</span>
              <span class="ws-meta-value">{{ ws.project?.name || $t('workspaces.not_set') }}</span>
            </div>
            <div class="ws-meta-row" :title="summarize(ws.products, productLabel, 10)">
              <Package class="ws-meta-icon" />
              <span class="ws-meta-label">{{ $t('workspaces.card_products') }}</span>
              <span class="ws-meta-value">{{ summarize(ws.products, productLabel) || $t('workspaces.not_set') }}</span>
            </div>
            <div class="ws-meta-row" :title="summarize(ws.repositories, (repo) => repo?.repo_name, 10)">
              <GitFork class="ws-meta-icon" />
              <span class="ws-meta-label">{{ $t('workspaces.card_repositories') }}</span>
              <span class="ws-meta-value">{{ summarize(ws.repositories, (repo) => repo?.repo_name) || $t('workspaces.not_set') }}</span>
            </div>
            <div class="ws-meta-row" :title="ws.owner?.display_name || ws.owner?.email">
              <UserAvatar
                class="ws-meta-icon ws-meta-avatar"
                :display-name="ws.owner?.display_name"
                :email="ws.owner?.email"
                :user-id="ws.owner?.id"
                :avatar-svg="ws.owner?.avatar_svg"
                :avatar-url="ws.owner?.avatar_url"
                size="xs"
              />
              <span class="ws-meta-label">{{ $t('workspaces.card_creator') }}</span>
              <span class="ws-meta-value">{{ ws.owner?.display_name || ws.owner?.email || $t('workspaces.not_set') }}</span>
            </div>
          </div>
          <div class="ws-card-footer">
            <span class="text-xs text-muted">{{ $t('workspaces.created_at', { date: new Date(ws.created_at).toLocaleDateString(locale) }) }}</span>
          </div>
        </div>
      </div>
    </main>

    <WorkspaceCreateWorkflowDialog
      :show="showCreateModal"
      @close="showCreateModal = false"
      @created="handleWorkspaceCreated"
    />

    <ConfirmActionModal
      :show="showDeleteConfirm"
      :title="$t('workspaces.delete_ws')"
      :message="$t('workspaces.delete_confirm', { name: wsToDelete?.name || '' })"
      :emphasis-label="$t('workspaces.delete_path_label')"
      :emphasis-value="wsToDelete?.project_path || $t('workspaces.path_not_set')"
      :description="$t('workspaces.delete_warning')"
      :cancel-text="$t('workspaces.keep_it')"
      :confirm-text="$t('workspaces.delete_permanently')"
      tone="danger"
      :loading="deletingWorkspace"
      @cancel="closeDeleteWorkspaceModal"
      @confirm="confirmDeleteWorkspace"
    />
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');

.ws-container {
  min-height: 100vh;
  background-color: var(--color-bg-base);
  font-family: 'Open Sans', sans-serif;
}

.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem 4rem;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(10px);
  position: sticky;
  top: 0;
  z-index: 100;
  border-bottom: 1px solid #e2e8f0;
}

.logo {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, #0ea5e9, #3b82f6);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3);
}

.logo-text {
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: -0.5px;
  color: #1e3a8a;
}

.logo-link {
  text-decoration: none;
  color: inherit;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 2rem;
}

.btn-ghost {
  background: none;
  border: none;
  color: #475569;
  font-weight: 600;
  cursor: pointer;
  padding: 0.625rem 1rem;
  transition: color 0.2s;
}

.btn-ghost:hover {
  color: #0ea5e9;
}

.ws-main {
  max-width: 1000px;
  margin: 2rem auto 0;
  padding: 0 var(--space-8) var(--space-8);
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

.ws-card-meta {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-1);
}

.ws-meta-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8125rem;
  min-width: 0;
}

.ws-meta-icon {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  color: var(--color-text-muted);
}

.ws-meta-avatar {
  border-radius: 50%;
}

.ws-meta-label {
  flex-shrink: 0;
  width: 3.75rem;
  color: var(--color-text-muted);
}

.ws-meta-value {
  color: var(--color-text-body);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group:hover .group-hover\:opacity-100 {
  opacity: 1;
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

.create-error {
  margin: 0;
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: var(--radius-md);
  padding: 10px 12px;
  font-size: 0.875rem;
}
.v-divider {
  width: 1px;
  height: 24px;
  background-color: #e2e8f0;
}

.lang-switch-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 0.5rem 0.875rem;
  border-radius: 8px;
  color: #475569;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 0.8125rem;
  margin-left: 0.5rem;
}

.lang-switch-btn:hover {
  background: #f1f5f9;
  border-color: #0ea5e9;
  color: #0ea5e9;
}

@media (max-width: 1024px) {
  .navbar { padding: 1.5rem 2rem; }
  .nav-links { gap: 1rem; }
  .ws-main {
    margin-top: 1.5rem;
    padding: 0 var(--space-4) var(--space-8);
  }
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
