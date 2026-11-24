<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Briefcase, Check, ChevronDown } from '@/components/icons'
import WorkspaceAvatar from '@/components/workspace/WorkspaceAvatar.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useDesktopTitleMenu } from './useDesktopTitleMenu'

const props = defineProps<{ workspaceId: string }>()
const emit = defineEmits<{ select: [id: string] }>()
const workspace = useWorkspaceStore()
const { t } = useI18n()
const { setVisible } = useDesktopTitleMenu()
const loading = shallowRef(false)
const failed = shallowRef(false)
const current = computed(() => workspace.currentWorkspace?.id === props.workspaceId
  ? workspace.currentWorkspace : workspace.workspaces.find(item => item.id === props.workspaceId))

async function load(open: boolean) {
  setVisible(open)
  if (!open || loading.value) return
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
</script>

<template>
  <el-dropdown ref="dropdown" trigger="click" placement="bottom-start" :show-arrow="false"
    popper-class="desktop-titlebar-menu desktop-workspace-menu" max-height="min(384px, calc(100dvh - 64px))"
    @visible-change="load" @command="emit('select', String($event))">
    <button ref="trigger" class="workspace-picker" type="button" :aria-label="t('desktop_tabs.switch_workspace')"
      :title="current?.name || t('desktop_tabs.switch_workspace')">
      <WorkspaceAvatar v-if="current" class="workspace-avatar" :name="current.name" :avatar-url="current.avatar_url" :avatar-svg="current.avatar_svg" />
      <Briefcase v-else class="workspace-icon" aria-hidden="true" />
      <span class="workspace-name">{{ current?.name || t('desktop_tabs.workspaces') }}</span>
      <ChevronDown class="chevron" aria-hidden="true" />
    </button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="" class="workspace-overview">
          <div class="desktop-menu-row">
            <span class="desktop-menu-row-icon"><Briefcase aria-hidden="true" /></span>
            <span class="desktop-menu-row-label">{{ t('workspaces.title') }}</span>
          </div>
        </el-dropdown-item>
        <template v-if="workspace.workspaces.length">
          <el-dropdown-item v-for="(item, index) in workspace.workspaces" :key="item.id" :command="item.id"
            :divided="index === 0" :class="{ 'is-current': item.id === workspaceId }"
            :aria-current="item.id === workspaceId ? 'true' : undefined" :title="item.name">
            <div class="desktop-menu-row">
              <WorkspaceAvatar class="workspace-row-avatar" :name="item.name" :avatar-url="item.avatar_url" :avatar-svg="item.avatar_svg" />
              <span class="desktop-menu-row-label">{{ item.name }}</span>
              <Check v-if="item.id === workspaceId" class="desktop-menu-row-check" aria-hidden="true" />
            </div>
          </el-dropdown-item>
        </template>
        <el-dropdown-item v-else-if="loading" disabled divided>{{ t('workspaces.loading') }}</el-dropdown-item>
        <el-dropdown-item v-else-if="failed" disabled divided>{{ t('desktop_tabs.workspace_load_failed') }}</el-dropdown-item>
        <el-dropdown-item v-else disabled divided>{{ t('workspaces.no_workspaces') }}</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.workspace-picker {
  min-width: 0;
  max-width: clamp(112px, 15vw, 206px);
  display: flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  padding: 0 8px;
  border: 0;
  background: transparent;
  border-radius: 6px;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
  transition: background-color 140ms ease;
}
.workspace-picker:hover, .workspace-picker[aria-expanded='true'] { background: #dfe8f3; }
.workspace-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-avatar { width: 21px; height: 21px; border-radius: 5px; font-size: 9px; flex: none; }
.desktop-menu-row > .workspace-row-avatar { width: 28px; height: 28px; border-radius: 6px; font-size: 10px; }
.workspace-icon, .chevron { width: 15px; height: 15px; flex: none; }
.chevron { width: 12px; height: 12px; color: #64748b; }
</style>
