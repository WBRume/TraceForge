<script setup lang="ts">
import { computed, nextTick, shallowRef, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight, Briefcase, Check, ChevronDown, ChevronRight, Search, X } from '@/components/icons'
import WorkspaceAvatar from '@/components/workspace/WorkspaceAvatar.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import './desktopTitleBarMenus.css'
import { moveMenuFocus, useDesktopTitleMenu } from './useDesktopTitleMenu'

interface WorkspaceListItem {
  id: string
  name: string
  description?: string | null
  avatar_url?: string | null
  avatar_svg?: string | null
  custom_project_name?: string | null
  project?: { name?: string | null } | null
  repositories?: Array<{ repo_name?: string | null }> | null
}

const props = defineProps<{ workspaceId: string }>()
const emit = defineEmits<{ select: [id: string] }>()

const workspace = useWorkspaceStore()
const { t } = useI18n()
const menuId = `workspace-picker-${useId()}`
const searchInput = useTemplateRef<HTMLInputElement>('searchInput')
const listEl = useTemplateRef<HTMLElement>('listEl')
const loading = shallowRef(false)
const failed = shallowRef(false)
const searchQuery = shallowRef('')

const items = computed(() => (workspace.workspaces || []) as WorkspaceListItem[])
const current = computed(() => (
  workspace.currentWorkspace?.id === props.workspaceId
    ? workspace.currentWorkspace
    : items.value.find(item => item.id === props.workspaceId)
))
const showSearch = computed(() => items.value.length > 5)

const filteredWorkspaces = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return items.value
  return items.value.filter(item => {
    const projectName = item.project?.name || item.custom_project_name || ''
    const repoNames = (item.repositories || []).map(repo => repo?.repo_name || '').join(' ')
    const haystack = `${item.name} ${projectName} ${repoNames} ${item.description || ''}`.toLowerCase()
    return haystack.includes(query)
  })
})

function workspaceMeta(item: WorkspaceListItem): string {
  const projectName = (item.project?.name || item.custom_project_name || '').trim()
  const repoCount = Array.isArray(item.repositories) ? item.repositories.length : 0
  if (projectName && repoCount > 0) {
    return `${projectName} · ${t('desktop_tabs.workspace_repos_count', { count: repoCount }, repoCount)}`
  }
  if (projectName) return projectName
  if (repoCount > 0) return t('desktop_tabs.workspace_repos_count', { count: repoCount }, repoCount)
  return item.description?.trim() || ''
}

async function fetchWorkspacesList() {
  if (loading.value) return
  loading.value = true
  failed.value = false
  try {
    await workspace.fetchWorkspaces(false)
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

async function focusAfterOpen() {
  await nextTick()
  updatePosition()
  listEl.value?.querySelector<HTMLElement>('.is-current')?.scrollIntoView?.({ block: 'nearest' })
  if (showSearch.value && searchInput.value) {
    searchInput.value.focus({ preventScroll: true })
    return
  }
  const preferred = listEl.value?.querySelector<HTMLElement>('.is-current')
    ?? panel.value?.querySelector<HTMLElement>('[data-menu-item]')
  preferred?.focus({ preventScroll: true })
}

const { panel, isOpen, panelStyle, closeMenu, toggleMenu, updatePosition } = useDesktopTitleMenu({
  panelWidth: 364,
  onOpen: () => {
    searchQuery.value = ''
    void fetchWorkspacesList()
    void focusAfterOpen()
  },
})

watch(() => props.workspaceId, () => closeMenu(false))

function selectItem(id: string) {
  closeMenu(false)
  emit('select', id)
}

function onPanelKeydown(event: KeyboardEvent) {
  if (event.target === searchInput.value) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      moveMenuFocus(panel.value, 'ArrowDown')
    } else if (event.key === 'Enter' && filteredWorkspaces.value.length > 0) {
      event.preventDefault()
      selectItem(filteredWorkspaces.value[0]!.id)
    }
    return
  }
  if (moveMenuFocus(panel.value, event.key)) event.preventDefault()
}
</script>

<template>
  <button
    ref="trigger"
    class="workspace-picker"
    :class="{ 'is-open': isOpen }"
    type="button"
    aria-haspopup="dialog"
    :aria-expanded="isOpen"
    :aria-controls="isOpen ? menuId : undefined"
    :aria-label="t('desktop_tabs.switch_workspace')"
    :title="current?.name || t('desktop_tabs.switch_workspace')"
    @click="toggleMenu"
  >
    <WorkspaceAvatar
      v-if="current"
      class="workspace-avatar"
      :name="current.name"
      :avatar-url="current.avatar_url"
      :avatar-svg="current.avatar_svg"
    />
    <Briefcase v-else class="workspace-icon" aria-hidden="true" />
    <span class="workspace-name">{{ current?.name || t('desktop_tabs.workspaces') }}</span>
    <ChevronDown class="chevron" :class="{ 'is-rotated': isOpen }" aria-hidden="true" />
  </button>

  <Teleport to="body">
    <Transition name="desktop-menu-pop">
      <div
        v-if="isOpen"
        :id="menuId"
        ref="panel"
        class="desktop-titlebar-popover workspace-popover"
        role="dialog"
        :aria-label="t('desktop_tabs.switch_workspace')"
        :style="panelStyle"
        @keydown="onPanelKeydown"
      >
        <div class="desktop-popover-header">
          <span class="desktop-popover-title">{{ t('desktop_tabs.switch_workspace') }}</span>
          <span v-if="items.length" class="desktop-popover-count">
            {{ t('desktop_tabs.workspace_count', { count: items.length }) }}
          </span>
        </div>

        <div v-if="showSearch" class="workspace-popover-search">
          <div class="workspace-popover-search-box">
            <Search class="workspace-popover-search-icon" aria-hidden="true" />
            <input
              ref="searchInput"
              v-model="searchQuery"
              type="text"
              class="workspace-popover-search-input"
              :aria-label="t('desktop_tabs.search_workspaces')"
              :placeholder="t('desktop_tabs.search_workspaces')"
            />
            <button
              v-if="searchQuery"
              type="button"
              class="workspace-popover-search-clear"
              :aria-label="t('workspaces.filters.search_clear')"
              @click="searchQuery = ''; searchInput?.focus()"
            >
              <X aria-hidden="true" />
            </button>
          </div>
        </div>

        <div ref="listEl" class="workspace-popover-list" role="listbox" :aria-label="t('desktop_tabs.workspaces')">
          <div v-if="loading && !items.length" class="desktop-popover-state">
            <span>{{ t('workspaces.loading') }}</span>
          </div>
          <div v-else-if="failed && !items.length" class="desktop-popover-state">
            <span>{{ t('desktop_tabs.workspace_load_failed') }}</span>
            <button type="button" class="desktop-popover-retry" @click="fetchWorkspacesList">
              {{ t('common.refresh') }}
            </button>
          </div>
          <div v-else-if="!items.length" class="desktop-popover-state">
            <Briefcase class="desktop-popover-state-icon" aria-hidden="true" />
            <span>{{ t('workspaces.no_workspaces') }}</span>
          </div>
          <div v-else-if="!filteredWorkspaces.length" class="desktop-popover-state">
            <Search class="desktop-popover-state-icon" aria-hidden="true" />
            <span>{{ t('desktop_tabs.workspace_empty_search') }}</span>
          </div>
          <template v-else>
            <button
              v-for="item in filteredWorkspaces"
              :key="item.id"
              type="button"
              role="option"
              data-menu-item
              class="workspace-popover-item"
              :class="{ 'is-current': item.id === workspaceId }"
              :aria-selected="item.id === workspaceId"
              :title="item.name"
              @click="selectItem(item.id)"
            >
              <WorkspaceAvatar
                class="workspace-popover-avatar"
                :name="item.name"
                :avatar-url="item.avatar_url"
                :avatar-svg="item.avatar_svg"
              />
              <span class="workspace-popover-main">
                <span class="workspace-popover-name">{{ item.name }}</span>
                <span v-if="workspaceMeta(item)" class="workspace-popover-meta">{{ workspaceMeta(item) }}</span>
              </span>
              <span class="workspace-popover-trailing">
                <template v-if="item.id === workspaceId">
                  <span class="workspace-popover-current-tag">{{ t('desktop_tabs.current_workspace') }}</span>
                  <Check class="workspace-popover-check" aria-hidden="true" />
                </template>
                <ChevronRight v-else class="workspace-popover-go" aria-hidden="true" />
              </span>
            </button>
          </template>
        </div>

        <div class="desktop-popover-footer">
          <button type="button" data-menu-item class="desktop-popover-footer-btn" @click="selectItem('')">
            <span class="desktop-popover-footer-icon">
              <Briefcase aria-hidden="true" />
            </span>
            <span class="desktop-popover-footer-text">
              <span class="desktop-popover-footer-label">{{ t('workspaces.title') }}</span>
              <span class="desktop-popover-footer-desc">{{ t('desktop_tabs.all_workspaces_desc') }}</span>
            </span>
            <ArrowRight class="desktop-popover-footer-arrow" aria-hidden="true" />
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.workspace-picker {
  min-width: 0;
  max-width: clamp(120px, 16vw, 220px);
  display: flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  padding: 0 8px 0 6px;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 8px;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease, box-shadow 140ms ease;
}

.workspace-picker:hover {
  background: #ffffff;
  border-color: #e2e8f0;
  color: #0f172a;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}

.workspace-picker.is-open {
  background: #ffffff;
  border-color: #93c5fd;
  color: #0369a1;
  box-shadow: 0 1px 3px rgba(14, 165, 233, 0.14);
}

.workspace-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-avatar {
  width: 21px;
  height: 21px;
  border-radius: 6px;
  font-size: 9px;
  flex: none;
}

.workspace-icon {
  width: 15px;
  height: 15px;
  flex: none;
  color: #475569;
}

.chevron {
  width: 12px;
  height: 12px;
  flex: none;
  color: #64748b;
  transition: transform 160ms ease, color 140ms ease;
}

.workspace-picker.is-open .chevron {
  color: #0284c7;
}

.chevron.is-rotated {
  transform: rotate(180deg);
}

@media (prefers-reduced-motion: reduce) {
  .workspace-picker,
  .chevron {
    transition: none;
  }
}
</style>
