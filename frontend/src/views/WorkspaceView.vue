<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import { Plus, Briefcase, Languages, Package, FolderKanban, GitFork } from '@/components/icons'
import AppSwitcherDropdown from '@/components/AppSwitcherDropdown.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import WorkspaceCreateWorkflowDialog from '@/components/workspace/create-workflow/WorkspaceCreateWorkflowDialog.vue'
import api from '@/utils/api'
import UserIdentityBadge from '@/components/user/UserIdentityBadge.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'
import GlobalSearchTrigger from '@/components/global-search/GlobalSearchTrigger.vue'

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
const searchQuery = ref('')

const filteredWorkspaces = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return wsStore.workspaces
  return wsStore.workspaces.filter((ws: any) => {
    const name = (ws.name || '').toLowerCase()
    const desc = (ws.description || '').toLowerCase()
    const proj = (ws.project?.name || ws.custom_project_name || '').toLowerCase()
    const repos = (ws.repositories || []).map((r: any) => r.repo_name || '').join(' ').toLowerCase()
    return name.includes(query) || desc.includes(query) || proj.includes(query) || repos.includes(query)
  })
})

const getWorkspaceAvatar = (name: string) => {
  if (!name) return { text: 'WS', bg: '#f0f9ff', color: '#0284c7', border: '#bae6fd' }
  const clean = name.trim()
  const firstTwo = clean.length >= 2 ? clean.slice(0, 2).toUpperCase() : clean.toUpperCase()
  const hash = clean.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0)
  const palettes = [
    { bg: '#f0f9ff', color: '#0284c7', border: '#bae6fd' },
    { bg: '#f0fdf4', color: '#16a34a', border: '#bbf7d0' },
    { bg: '#f5f3ff', color: '#7c3aed', border: '#ddd6fe' },
    { bg: '#fdf4ff', color: '#c026d3', border: '#f5d0fe' },
    { bg: '#fffbeb', color: '#d97706', border: '#fde68a' },
    { bg: '#f0fdfa', color: '#0d9488', border: '#99f6e4' },
  ]
  return { text: firstTwo, ...palettes[hash % palettes.length] }
}

onMounted(async () => {
  await wsStore.fetchWorkspaces()
  loading.value = false
})

const enterWorkspace = (ws: any) => {
  wsStore.setCurrent(ws)
  router.push(`/workspaces/${ws.id}/dashboard`)
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
      <div class="brand-area">
        <AppSwitcherDropdown />
        <router-link to="/" class="logo-link" :title="$t('common.home')">
          <span class="logo-text">TraceForge</span>
        </router-link>
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
        <GlobalSearchTrigger />
      </div>
    </nav>

    <main class="ws-main">
      <div class="ws-header-row">
        <div class="ws-header-left">
          <h2 class="title-gradient-small">{{ $t('workspaces.title') }}</h2>
        </div>
        <div class="ws-header-actions">
          <div class="ws-search-wrapper">
            <svg class="ws-search-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              v-model="searchQuery"
              type="text"
              class="ws-search-input"
              :placeholder="locale === 'zh' ? '过滤工作区或仓库...' : 'Filter workspaces...'"
            />
          </div>
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

      <div v-else-if="filteredWorkspaces.length === 0" class="empty-state glass-panel">
        <p class="text-muted">{{ locale === 'zh' ? '未找到符合条件的工作区' : 'No matching workspaces found' }}</p>
      </div>

      <div v-else class="ws-grid">
        <div
          v-for="(ws, index) in filteredWorkspaces"
          :key="ws.id"
          class="ws-card bento-card group hover-lift animate-pop-in"
          :style="{ animationDelay: `${index * 50}ms` }"
          @click="enterWorkspace(ws)"
        >
          <div>
            <div class="ws-card-header flex justify-between items-center mb-2">
              <div class="flex items-center gap-3 min-w-0">
                <div
                  class="ws-avatar-badge"
                  :style="{
                    backgroundColor: getWorkspaceAvatar(ws.name).bg,
                    color: getWorkspaceAvatar(ws.name).color,
                    borderColor: getWorkspaceAvatar(ws.name).border,
                  }"
                >
                  {{ getWorkspaceAvatar(ws.name).text }}
                </div>
                <h3 class="ws-card-title truncate" :title="ws.name">{{ ws.name }}</h3>
              </div>

              <DeleteActionButton
                v-if="ws.can_delete_workspace"
                :title="$t('workspaces.delete_ws')"
                @click.stop="handleDeleteWorkspace(ws)"
              />
            </div>

            <p class="ws-card-desc">{{ ws.description || $t('workspaces.no_desc') }}</p>

            <!-- 设计样例 B-1 微质感参数盒 -->
            <div class="ws-metadata-box">
              <div class="ws-metadata-row" :title="ws.project?.name || ws.custom_project_name">
                <span class="ws-metadata-label">
                  <FolderKanban class="ws-meta-icon" />
                  {{ $t('workspaces.card_project') }}
                </span>
                <span class="ws-metadata-value">{{ ws.project?.name || ws.custom_project_name || $t('workspaces.not_set') }}</span>
              </div>
              <div class="ws-metadata-row" :title="summarize(ws.products, productLabel, 10) || ws.custom_product_name">
                <span class="ws-metadata-label">
                  <Package class="ws-meta-icon" />
                  {{ $t('workspaces.card_products') }}
                </span>
                <span class="ws-metadata-value">{{ summarize(ws.products, productLabel) || ws.custom_product_name || $t('workspaces.not_set') }}</span>
              </div>
              <div class="ws-metadata-row" :title="summarize(ws.repositories, (repo) => repo?.repo_name, 10)">
                <span class="ws-metadata-label">
                  <GitFork class="ws-meta-icon" />
                  {{ $t('workspaces.card_repositories') }}
                </span>
                <span class="ws-metadata-value font-mono-chip">{{ summarize(ws.repositories, (repo) => repo?.repo_name) || $t('workspaces.not_set') }}</span>
              </div>
              <div class="ws-metadata-row" :title="ws.owner?.display_name || ws.owner?.email">
                <span class="ws-metadata-label">
                  <UserAvatar
                    class="ws-meta-icon ws-meta-avatar"
                    :display-name="ws.owner?.display_name"
                    :email="ws.owner?.email"
                    :user-id="ws.owner?.id"
                    :avatar-svg="ws.owner?.avatar_svg"
                    :avatar-url="ws.owner?.avatar_url"
                    size="xs"
                  />
                  {{ $t('workspaces.card_creator') }}
                </span>
                <span class="ws-metadata-value">{{ ws.owner?.display_name || ws.owner?.email || $t('workspaces.not_set') }}</span>
              </div>
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

.brand-area {
  display: flex;
  align-items: center;
  gap: 0.875rem;
}

.logo-link {
  text-decoration: none;
  color: inherit;
  display: flex;
  align-items: center;
}

.logo-text {
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: -0.5px;
  color: #1e3a8a;
  transition: color 0.2s;
}

.logo-link:hover .logo-text {
  color: #0284c7;
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
  max-width: 1100px;
  margin: 2rem auto 0;
  padding: 0 var(--space-8) var(--space-8);
}

.ws-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-6);
  gap: 1rem;
  flex-wrap: wrap;
}

.ws-header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
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

.ws-header-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.ws-search-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.ws-search-icon {
  position: absolute;
  left: 0.625rem;
  width: 14px;
  height: 14px;
  color: #94a3b8;
  pointer-events: none;
}

.ws-search-input {
  padding: 0.45rem 0.75rem 0.45rem 2rem;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 0.8125rem;
  background: #ffffff;
  color: #1e293b;
  width: 200px;
  transition: all 0.2s ease;
  outline: none;
}

.ws-search-input:focus {
  border-color: #0284c7;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
  width: 230px;
}

.ws-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
  gap: var(--space-6);
}

/* 纯净卡片：对齐设计样例 B-1 微质感风格，彻底移除顶部彩色色卡条 */
.ws-card {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  cursor: pointer;
  min-height: 170px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  transition: all 0.28s cubic-bezier(0.16, 1, 0.3, 1);
  position: relative;
}

.ws-card:hover {
  transform: translateY(-4px);
  border-color: #93c5fd;
  box-shadow: 0 16px 28px -6px rgba(14, 165, 233, 0.09), 0 6px 10px -4px rgba(14, 165, 233, 0.03);
}

.ws-avatar-badge {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 0.875rem;
  border-width: 1px;
  border-style: solid;
  flex-shrink: 0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.ws-card-title {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--color-primary-900, #0c4a6e);
  transition: color 0.2s ease;
}

.ws-card:hover .ws-card-title {
  color: #0284c7;
}

.ws-card-desc {
  font-size: 0.75rem;
  color: #94a3b8;
  font-style: italic;
  margin: 0.25rem 0 0.875rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 设计样例 B-1 微质感参数盒 */
.ws-metadata-box {
  background: rgba(248, 250, 252, 0.85);
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  padding: 0.75rem 0.875rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.ws-metadata-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.75rem;
  min-width: 0;
}

.ws-metadata-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  color: #94a3b8;
  font-size: 0.75rem;
  flex-shrink: 0;
}

.ws-metadata-value {
  color: #334155;
  font-weight: 500;
  font-size: 0.75rem;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
}

.opacity-0 {
  opacity: 0;
}

.transition-opacity {
  transition: opacity 0.2s ease;
}

.font-mono-chip {
  font-family: var(--font-mono, monospace);
  font-size: 0.6875rem;
  background: #ffffff;
  color: #475569;
  border: 1px solid #e2e8f0;
  padding: 0.1rem 0.375rem;
  border-radius: 4px;
}

.ws-meta-icon {
  width: 14px;
  height: 14px;
  color: #94a3b8;
  flex-shrink: 0;
}

.ws-meta-avatar {
  border-radius: 50%;
  flex-shrink: 0;
}

.group:hover .group-hover\:opacity-100 {
  opacity: 1;
}

.ws-card-footer {
  margin-top: 0.875rem;
  padding-top: 0.75rem;
  border-top: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: flex-end;
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
