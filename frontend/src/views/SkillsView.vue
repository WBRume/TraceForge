<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Plus,
  Wrench,
  Globe,
  FolderOpen,
  Pencil,
  Loader2,
  Sparkles,
  Search,
} from 'lucide-vue-next'
import api from '@/utils/api'
import { useWorkspaceStore } from '@/stores/workspace'
import AppSidebar from '@/components/AppSidebar.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import SkillCardMeta from '@/components/skills/SkillCardMeta.vue'
import SkillGithubImportModal from '@/components/skills/SkillGithubImportModal.vue'
import {
  useSkillsListQuery,
  type SkillItem,
  type SkillDimension,
} from '@/composables/skills/useSkillsListQuery'

const router = useRouter()
const wsStore = useWorkspaceStore()
const { t } = useI18n()

const deletingSkillId = ref('')
const activeScope = ref<'all' | 'global' | 'workspace'>('all')
const skillNameKeyword = ref('')
const workspaceFilterId = ref('')
const showDeleteConfirm = ref(false)
const skillToDelete = ref<any>(null)
const showEditConfirm = ref(false)
const skillToEdit = ref<any>(null)
const showGithubImportModal = ref(false)

const {
  loading,
  skills,
  skillPage,
  skillTotalPages,
  loadSkills,
  prevSkillPage,
  nextSkillPage,
} = useSkillsListQuery({
  activeScope,
  skillNameKeyword,
  workspaceFilterId,
  pageSize: 20,
})

const scopeOptions = computed(() => [
  { key: 'all', label: t('skills.list.scope_all') },
  { key: 'global', label: t('skills.list.scope_global') },
  { key: 'workspace', label: t('skills.list.scope_workspace') },
])

const sidebarNavItems = computed(() => [
  {
    key: 'skills-manage',
    label: t('skills.list.sidebar_manage'),
    icon: Wrench,
    active: true,
    noClick: true,
  },
])

const workspaceNameMap = computed(() => {
  const entries = wsStore.workspaces.map((ws) => [String(ws.id), String(ws.name || '')] as const)
  return new Map(entries)
})

const resolveSkillWorkspaceName = (skill: SkillItem) => {
  if (skill.dimension !== 'WORKSPACE') return ''
  const targetWorkspaceId = skill.workspace_id || ''
  if (!targetWorkspaceId) return ''
  return workspaceNameMap.value.get(targetWorkspaceId) || targetWorkspaceId
}

const resolveCreatorDisplayName = (skill: SkillItem) => (
  skill.creator_display_name
  || skill.creator_id?.slice(0, 8)
  || t('skills.list.unknown_user')
)

const resolveLastModifierDisplayName = (skill: SkillItem) => (
  skill.last_modifier_display_name
  || skill.last_modifier_id?.slice(0, 8)
  || t('skills.list.unknown_user')
)

const workspaceFilterOptions = computed(() => {
  const options = [
    { label: t('skills.list.workspace_filter_all'), value: '' },
  ]
  wsStore.workspaces.forEach((ws) => {
    options.push({
      label: ws.name || String(ws.id),
      value: String(ws.id),
    })
  })
  return options
})

const goBack = () => {
  router.push('/workspaces')
}

const goCreate = () => {
  router.push({
    name: 'skillsCreate',
  })
}

const goCreateFromGithub = () => {
  showGithubImportModal.value = true
}

const resolveSkillEditorWorkspaceId = (skill: SkillItem) => (
  skill.dimension === 'WORKSPACE'
    ? String(skill.workspace_id || '')
    : ''
)

const goEdit = (skill: SkillItem) => {
  const contextWorkspaceId = resolveSkillEditorWorkspaceId(skill)
  if (skill.dimension === 'WORKSPACE' && !contextWorkspaceId) return
  if (!skill.can_manage) return
  if (skill.source_locked) return
  skillToEdit.value = skill
  showEditConfirm.value = true
}

const goView = (skill: SkillItem) => {
  const contextWorkspaceId = resolveSkillEditorWorkspaceId(skill)
  if (skill.dimension === 'WORKSPACE' && !contextWorkspaceId) return
  router.push({
    name: 'skillsEdit',
    params: { skillId: skill.id },
    query: {
      ...(contextWorkspaceId ? { wsId: contextWorkspaceId } : {}),
      readonly: '1',
    },
  })
}

const deleteSkill = (skill: SkillItem) => {
  if (skill.dimension === 'WORKSPACE' && !resolveSkillEditorWorkspaceId(skill)) return
  skillToDelete.value = skill
  showDeleteConfirm.value = true
}

const closeDeleteConfirm = () => {
  if (deletingSkillId.value) return
  showDeleteConfirm.value = false
  skillToDelete.value = null
}

const closeEditConfirm = () => {
  showEditConfirm.value = false
  skillToEdit.value = null
}

const confirmEnterEdit = () => {
  if (!skillToEdit.value) return
  const skill = skillToEdit.value
  const contextWorkspaceId = resolveSkillEditorWorkspaceId(skill)
  if (skill.dimension === 'WORKSPACE' && !contextWorkspaceId) return
  showEditConfirm.value = false
  skillToEdit.value = null
  router.push({
    name: 'skillsEdit',
    params: { skillId: skill.id },
    query: {
      ...(contextWorkspaceId ? { wsId: contextWorkspaceId } : {}),
    },
  })
}

const confirmDeleteSkill = async () => {
  if (!skillToDelete.value) return
  const skill = skillToDelete.value
  deletingSkillId.value = skill.id
  try {
    const params: Record<string, string> = {}
    if (skill.dimension === 'WORKSPACE') {
      const contextWorkspaceId = resolveSkillEditorWorkspaceId(skill)
      if (!contextWorkspaceId) return
      params.workspace_id = contextWorkspaceId
    }
     
    await api.delete(`/skills/${skill.id}`, { params })
    await loadSkills({ resetPage: true })
    showDeleteConfirm.value = false
    skillToDelete.value = null
  } catch (e) {
    console.error('Failed to delete skill', e)
  } finally {
    deletingSkillId.value = ''
  }
}

const dimensionLabel = (dimension: SkillDimension) =>
  dimension === 'GLOBAL' ? t('skills.list.scope_global') : t('skills.list.scope_workspace')

let keywordDebounceTimer: number | null = null

const scheduleKeywordQuery = () => {
  if (keywordDebounceTimer !== null) {
    window.clearTimeout(keywordDebounceTimer)
  }
  keywordDebounceTimer = window.setTimeout(() => {
    keywordDebounceTimer = null
    void loadSkills({ resetPage: true })
  }, 280)
}

watch(activeScope, () => {
  if (activeScope.value !== 'workspace') {
    workspaceFilterId.value = ''
  }
  void loadSkills({ resetPage: true })
})

watch(workspaceFilterOptions, (options) => {
  if (workspaceFilterId.value && !options.some((option) => option.value === workspaceFilterId.value)) {
    workspaceFilterId.value = ''
  }
})

watch(workspaceFilterId, () => {
  void loadSkills({ resetPage: true })
})

watch(skillNameKeyword, () => {
  scheduleKeywordQuery()
})

onMounted(async () => {
  await wsStore.fetchWorkspaces()

  await loadSkills({ resetPage: true })
})

onUnmounted(() => {
  if (keywordDebounceTimer !== null) {
    window.clearTimeout(keywordDebounceTimer)
    keywordDebounceTimer = null
  }
})
</script>

<template>
  <div class="skills-page">
    <AppSidebar
      :title="t('skills.list.title')"
      :back-title="t('skills.list.back_to_workspaces')"
      :toggle-title="t('layout.toggle_sidebar')"
      :nav-items="sidebarNavItems"
      @back="goBack"
    />

    <main class="skills-main">
      <section class="page-caption glass-panel">
        <h2 class="content-title">{{ $t('skills.list.content_title') }}</h2>
      </section>

      <section class="toolbar glass-panel">
        <div class="toolbar-filters">
          <div class="scope-tabs">
            <button
              v-for="opt in scopeOptions"
              :key="opt.key"
              class="scope-btn"
              :class="{ active: activeScope === opt.key }"
              @click="activeScope = opt.key as 'all' | 'global' | 'workspace'"
            >
              {{ opt.label }}
            </button>
          </div>

          <div class="filter-group">
            <div class="search-box">
              <Search class="search-icon" />
              <input
                v-model="skillNameKeyword"
                type="text"
                class="skill-name-filter-input"
                :placeholder="$t('skills.list.skill_name_filter_placeholder')"
              >
            </div>

            <div v-if="activeScope === 'workspace'" class="workspace-filter">
              <BaseSelect
                v-model="workspaceFilterId"
                :options="workspaceFilterOptions"
                :placeholder="$t('skills.list.workspace_filter_all')"
                size="sm"
                class="workspace-filter-select"
              />
            </div>
          </div>
        </div>

        <div class="toolbar-actions">
          <button class="btn-secondary create-btn toolbar-create-btn github-create-btn" @click="goCreateFromGithub">
            <Sparkles class="w-4 h-4" />
            {{ $t('skills.list.new_skill_github') }}
          </button>
          <button class="btn-primary create-btn toolbar-create-btn" @click="goCreate">
            <Plus class="w-4 h-4" />
            {{ $t('skills.list.new_skill') }}
          </button>
        </div>
      </section>

      <section class="skills-list glass-panel">
        <div v-if="loading" class="list-state">
          <Loader2 class="w-5 h-5 spin text-primary" />
          <span>{{ $t('skills.list.loading') }}</span>
        </div>

        <div v-else-if="skills.length === 0" class="list-state empty">
          <Sparkles class="w-5 h-5 text-primary" />
          <span>{{ $t('skills.list.empty') }}</span>
        </div>

        <div v-else class="skill-grid">
          <article v-for="skill in skills" :key="skill.id" class="skill-card" @click="goView(skill)">
            <div class="skill-card-inner">
              <div class="skill-card-header">
                <div class="skill-icon-wrapper">
                  <Wrench class="w-5 h-5" />
                </div>
                <span class="dimension-badge" :class="skill.dimension === 'GLOBAL' ? 'is-global' : 'is-workspace'">
                  <Globe v-if="skill.dimension === 'GLOBAL'" class="w-3 h-3" />
                  <FolderOpen v-else class="w-3 h-3" />
                  {{ dimensionLabel(skill.dimension) }}
                </span>
              </div>

              <div class="skill-content">
                <h3 class="skill-title">{{ skill.name }}</h3>
                <p class="skill-desc">{{ skill.description || $t('skills.list.no_description') }}</p>
              </div>

              <SkillCardMeta
                :skill="skill"
                :creator-name="resolveCreatorDisplayName(skill)"
                :last-modifier-name="resolveLastModifierDisplayName(skill)"
                :workspace-name="resolveSkillWorkspaceName(skill)"
              />

              <div class="skill-actions">
                <button
                  type="button"
                  class="btn-secondary mini"
                  :class="{ 'is-readonly': !skill.can_manage || skill.source_locked }"
                  :disabled="!skill.can_manage || skill.source_locked"
                  :title="skill.source_locked ? $t('skills.list.official_source_locked') : undefined"
                  @click.stop="goEdit(skill)"
                >
                  <Pencil class="w-3 h-3" />
                  {{ $t('skills.list.edit') }}
                </button>
                <DeleteActionButton
                  mode="mini"
                  :label="$t('skills.list.delete')"
                  :disabled="!skill.can_manage || deletingSkillId === skill.id"
                  :loading="deletingSkillId === skill.id"
                  @click.stop="deleteSkill(skill)"
                />
              </div>
            </div>
          </article>
        </div>

        <footer class="skills-pagination">
          <button
            v-if="skillTotalPages > 1 && skillPage > 1"
            class="btn-secondary mini"
            :disabled="loading"
            @click="prevSkillPage"
          >
            {{ $t('skills.list.prev_page') }}
          </button>
          <div class="pagination-info">
            <span class="skills-page-info">
              {{ $t('skills.list.page_info', { page: skillPage, total: skillTotalPages }) }}
            </span>
          </div>
          <button
            v-if="skillTotalPages > 1 && skillPage < skillTotalPages"
            class="btn-secondary mini"
            :disabled="loading"
            @click="nextSkillPage"
          >
            {{ $t('skills.list.next_page') }}
          </button>
        </footer>
      </section>
    </main>

    <ConfirmActionModal
      :show="showDeleteConfirm"
      :title="$t('common.delete')"
      :message="$t('skills.list.confirm_delete', { name: skillToDelete?.name || '' })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('skills.list.delete')"
      tone="danger"
      :loading="Boolean(deletingSkillId)"
      @cancel="closeDeleteConfirm"
      @confirm="confirmDeleteSkill"
    />

    <ConfirmActionModal
      :show="showEditConfirm"
      :title="$t('skills.list.edit')"
      :message="$t('skills.editor.enter_edit_confirm')"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="primary"
      @cancel="closeEditConfirm"
      @confirm="confirmEnterEdit"
    />

    <SkillGithubImportModal
      :show="showGithubImportModal"
      :workspaces="wsStore.workspaces"
      @close="showGithubImportModal = false"
    />
  </div>
</template>

<style scoped>
.skills-page {
  display: flex;
  min-height: 100vh;
  background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
  overflow: hidden;
}

.skills-main {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.page-caption {
  padding: 1.25rem 1.5rem;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(255, 255, 255, 0.7) 100%);
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: var(--radius-xl);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
}

.content-title {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 700;
  background: linear-gradient(140deg, #0284c7, #0ea5e9, #2563eb);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: -0.02em;
}

.create-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: 0.625rem;
}

.github-create-btn {
  border-color: rgba(148, 163, 184, 0.55);
  color: #0f172a;
  background: rgba(255, 255, 255, 0.88);
}

.github-create-btn:hover:not(:disabled) {
  border-color: #94a3b8;
  background: #fff;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  padding: 1rem 1.5rem;
  position: relative;
  z-index: 30;
  overflow: visible;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(255, 255, 255, 0.7) 100%);
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: var(--radius-xl);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
  backdrop-filter: blur(16px);
}

.toolbar-filters {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  flex: 1;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex: 1;
  max-width: 600px;
}

.search-box {
  position: relative;
  flex: 1;
  max-width: 360px;
}

.search-icon {
  position: absolute;
  left: 0.85rem;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-primary-500);
  width: 1rem;
  height: 1rem;
  pointer-events: none;
  opacity: 0.7;
}

.skill-name-filter-input {
  width: 100%;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.9);
  color: var(--color-text-title);
  padding: 0.625rem 0.875rem 0.625rem 2.5rem;
  border-radius: var(--radius-lg);
  font-size: 0.9rem;
  transition: all var(--transition-base);
}

.skill-name-filter-input:focus {
  outline: none;
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15), 0 4px 6px -1px rgba(0, 0, 0, 0.05);
  background: #fff;
}

.workspace-filter {
  min-width: 180px;
  max-width: 240px;
  position: relative;
}

.workspace-filter-select {
  width: 100%;
}

.scope-tabs {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: rgba(241, 245, 249, 0.8);
  padding: 0.25rem;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(226, 232, 240, 0.5);
}

.scope-btn {
  border: none;
  background: transparent;
  color: #64748b;
  padding: 0.5rem 1rem;
  border-radius: var(--radius-md);
  font-weight: 600;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.scope-btn:hover {
  background: rgba(255, 255, 255, 0.9);
  color: #475569;
}

.scope-btn.active {
  background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
  color: #fff;
  box-shadow: 0 4px 8px rgba(14, 165, 233, 0.3), 0 2px 4px rgba(14, 165, 233, 0.2);
  font-weight: 700;
}

.skills-list {
  padding: 1.5rem;
  min-height: 300px;
  position: relative;
  z-index: 1;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.85) 0%, rgba(255, 255, 255, 0.65) 100%);
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: var(--radius-xl);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -2px rgba(0, 0, 0, 0.03);
  backdrop-filter: blur(16px);
}

.list-state {
  height: 250px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  color: #475569;
}

.list-state.empty {
  color: #64748b;
}

.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 1.25rem;
}

.skill-card {
  background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-xl);
  padding: 0;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: all var(--transition-base);
  position: relative;
}

.skill-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(90deg, #0ea5e9, #0284c7);
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.skill-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  transform: translateY(-4px);
}

.skill-card:hover::before {
  opacity: 1;
}

.skill-card-inner {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  flex: 1;
}

.skill-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
}

.skill-icon-wrapper {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, #dbeafe 0%, #e0f2fe 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #0369a1;
  box-shadow: 0 2px 4px rgba(14, 165, 233, 0.15);
}

.skill-content {
  flex: 1;
}

.skill-title {
  margin: 0 0 0.5rem;
  font-size: 1.1rem;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.3;
}

.skill-desc {
  margin: 0;
  color: #64748b;
  font-size: 0.875rem;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.dimension-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  padding: 0.3rem 0.6rem;
  border-radius: var(--radius-full);
  font-weight: 700;
  white-space: nowrap;
  transition: all var(--transition-fast);
}

.dimension-badge.is-global {
  background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
  color: #1d4ed8;
  border: 1px solid #93c5fd;
}

.dimension-badge.is-workspace {
  background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%);
  color: #166534;
  border: 1px solid #86efac;
}

.skill-actions {
  margin-top: auto;
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding-top: 0.75rem;
  border-top: 1px solid #f1f5f9;
}

.skills-pagination {
  margin-top: 1.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #f1f5f9;
}

.pagination-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.pagination-badge {
  background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
  color: #fff;
  padding: 0.35rem 0.75rem;
  border-radius: var(--radius-full);
  font-size: 0.8rem;
  font-weight: 700;
  box-shadow: 0 2px 4px rgba(14, 165, 233, 0.3);
}

.skills-page-info {
  min-width: 8rem;
  text-align: center;
  font-size: 0.875rem;
  color: #64748b;
  font-weight: 500;
}

.mini {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.75rem;
  font-size: 0.8rem;
  border-radius: var(--radius-md);
  font-weight: 600;
  transition: all var(--transition-fast);
}

.mini.is-readonly {
  color: #94a3b8;
  border-color: #cbd5e1;
  background: #f8fafc;
}

.mini:disabled {
  cursor: not-allowed;
  opacity: 0.72;
}

.mini:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.w-3 {
  width: 0.75rem;
  height: 0.75rem;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.w-5 {
  width: 1.25rem;
  height: 1.25rem;
}

.spin {
  animation: spin 1s linear infinite;
}

.text-primary {
  color: var(--color-primary-500);
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 768px) {
  .skills-page {
    flex-direction: column;
    overflow: auto;
  }

  :deep(.sidebar) {
    width: 100%;
    margin-right: 0;
    border-radius: 0 0 var(--radius-xl) var(--radius-xl);
  }

  :deep(.sidebar-header) {
    padding: var(--space-4);
  }

  :deep(.sidebar-nav) {
    padding: var(--space-2);
  }

  .skills-main {
    padding: 1rem;
  }

  .toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 1rem;
  }

  .toolbar-filters {
    flex-direction: column;
    align-items: stretch;
    gap: 1rem;
  }

  .filter-group {
    flex-direction: column;
    align-items: stretch;
    max-width: none;
  }

  .search-box {
    max-width: none;
  }

  .workspace-filter {
    max-width: none;
  }

  .toolbar-create-btn {
    width: 100%;
    justify-content: center;
  }

  .toolbar-actions {
    width: 100%;
    flex-direction: column;
  }

  .skill-grid {
    grid-template-columns: 1fr;
  }
}
</style>
