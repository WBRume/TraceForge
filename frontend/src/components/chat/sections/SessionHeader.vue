<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
  Play,
  Wrench,
  FolderGit2,
  RotateCcw,
  OctagonPause,
  CheckCircle2,
  GitPullRequest,
  FileText,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-vue-next'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import ChatMoreActionsMenu from '@/components/chat/ChatMoreActionsMenu.vue'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'

/**
 * 会话头部动作域：引擎启停、初始化、技能/文档抽屉入口、补丁工作流、
 * 平台/CLI 工作台切换与更多操作菜单。
 * 分享入口与补丁抽屉属于视图级装配（弹窗宿主在 ChatView），以事件冒泡。
 * SOP 模式下标题左侧提供任务列表折叠钮（状态由视图装配层持有）。
 */
const props = defineProps<{
  vm: ChatViewVm
  showTasklistToggle?: boolean
  tasklistVisible?: boolean
}>()

const emit = defineEmits<{
  (event: 'share'): void
  (event: 'open-apply-patch'): void
  (event: 'toggle-tasklist'): void
}>()

const { t } = useI18n()
</script>

<template>
  <header class="chat-header glass-panel">
    <div class="header-left">
      <button
        v-if="props.showTasklistToggle"
        type="button"
        class="icon-btn tasklist-toggle-btn"
        :title="props.tasklistVisible ? t('chat.tasklist_collapse') : t('chat.tasklist_expand')"
        :aria-label="props.tasklistVisible ? t('chat.tasklist_collapse') : t('chat.tasklist_expand')"
        :aria-expanded="props.tasklistVisible ? 'true' : 'false'"
        @click="emit('toggle-tasklist')"
      >
        <PanelLeftClose v-if="props.tasklistVisible" class="w-4 h-4" />
        <PanelLeftOpen v-else class="w-4 h-4" />
      </button>
      <h2 :title="props.vm.currentTask.name">{{ props.vm.currentTask.name }}</h2>
      <span class="badge" :class="props.vm.currentTask.status.toLowerCase()">{{ props.vm.currentTask.status }}</span>
    </div>
    <div class="header-actions">
      <button
        v-if="props.vm.isStartActionVisible"
        class="btn-primary start-btn"
        :disabled="!props.vm.canClickStartAction"
        :title="props.vm.isTaskProvisioning ? t('chat.task_provisioning_hint') : ''"
        @click="props.vm.handleStartClick"
      >
        <Play class="w-4 h-4" /> {{ t('chat.engine_start') }}
      </button>

      <div class="action-divider"></div>

      <button class="btn-micro" :disabled="!props.vm.currentTask" @click="props.vm.openTaskSkillsDrawer">
        <Wrench class="w-4 h-4" />
        {{ t('chat.task_skills_button', { count: props.vm.taskRuntimeSkillCount }) }}
      </button>

      <button
        v-if="props.vm.isDiagnosisTask"
        class="btn-micro"
        :class="{ active: props.vm.isSpecPanelOpen }"
        :disabled="!props.vm.currentTask"
        @click="props.vm.toggleDiagnosisDocsDrawer"
      >
        <FolderGit2 class="w-4 h-4" />
        {{ t('diagnosis.docs_drawer_button') }}
      </button>

      <button class="icon-btn" :disabled="!props.vm.canInitializeAction" @click="props.vm.handleInitialize" :title="t('chat.initialize')">
        <RotateCcw class="w-4 h-4" />
      </button>
      <button class="icon-btn danger" :disabled="props.vm.isTerminalStatus || !props.vm.canManageTaskStatus" @click="props.vm.handleInterruptClick" :title="t('chat.mark_failed_confirm')">
        <OctagonPause class="w-4 h-4" />
      </button>
      <button class="icon-btn success" :disabled="props.vm.isTerminalStatus || !props.vm.canManageTaskStatus" @click="props.vm.handleCompleteClick" :title="t('chat.complete_task')">
        <CheckCircle2 class="w-4 h-4" />
      </button>

      <button class="btn-micro" v-if="!props.vm.hidePatchWorkflows" :disabled="!props.vm.currentTask" @click="emit('open-apply-patch')">
        <GitPullRequest class="w-4 h-4" />
        {{ t('chat.change_apply_button') }}
      </button>
      <div class="mode-toggle">
        <button
          class="mode-toggle-btn"
          :class="{ active: props.vm.chatWorkbenchMode === 'platform' }"
          @click="props.vm.setChatWorkbenchMode('platform')"
        >
          {{ t('chat.mode_platform') }}
        </button>
        <button
          class="mode-toggle-btn"
          :class="{ active: props.vm.chatWorkbenchMode === 'cli' }"
          @click="props.vm.setChatWorkbenchMode('cli')"
        >
          {{ t('chat.mode_cli') }}
        </button>
      </div>
      <button
        v-if="props.vm.showSpecEntryButton"
        class="icon-btn"
        :class="{ active: props.vm.isSpecPanelOpen && props.vm.isSpecDrawerAvailable }"
        @click="props.vm.handleSpecEntryClick"
        :title="props.vm.isTaskPreStart ? t('chat.spec_open_workspace') : t('chat.spec_toggle_drawer')"
      >
        <FileText class="w-4 h-4" />
      </button>
      <DeleteActionButton
        mode="icon"
        :title="t('common.delete')"
        :disabled="!props.vm.canDeleteTask"
        @click="props.vm.handleDeleteTask(props.vm.currentTask)"
      />
      <ChatMoreActionsMenu
        :can-export="props.vm.canExportTask"
        :can-share="props.vm.canShareTaskSession"
        :show-attribution="props.vm.chatWorkbenchMode === 'platform'"
        :attribution-active="props.vm.contextWindowDrawerOpen"
        @export="props.vm.handleExport"
        @open-attribution="props.vm.openContextWindowDrawer"
        @share="emit('share')"
      />
    </div>
  </header>
</template>

<style scoped>
.chat-header {
  height: 60px;
  min-width: 0;
  padding: 0 var(--space-6);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-4);
  border-radius: 0;
  border: none;
  border-bottom: 1px solid rgba(0,0,0,0.05);
  background-color: rgba(255,255,255,0.8);
  backdrop-filter: blur(12px);
  z-index: 10;
  flex-shrink: 0;
}
.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
}
.tasklist-toggle-btn {
  flex: 0 0 auto;
}
.header-left h2 {
  margin: 0;
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 1.125rem;
}
.header-left > :not(h2) {
  flex: 0 0 auto;
}

.badge {
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 12px;
  background-color: #E2E8F0;
  color: #475569;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.badge.coding, .badge.running { background-color: var(--color-primary-100); color: var(--color-primary-900); }
.badge.done { background-color: #D1FAE5; color: #065F46; }
.badge.failed { background-color: #FEE2E2; color: #991B1B; }
.badge.interrupted { background-color: #FEF3C7; color: #92400E; }

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 1 auto;
  min-width: 0;
  overflow-x: auto;
}
.header-actions > * {
  flex: 0 0 auto;
}
.header-actions button {
  white-space: nowrap;
}
.mode-toggle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: 10px;
  background: rgba(148, 163, 184, 0.16);
}
.mode-toggle-btn {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 0.75rem;
  cursor: pointer;
}
.mode-toggle-btn.active {
  background: #ffffff;
  color: var(--color-primary-700);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
}
.action-divider {
  width: 1px;
  height: 20px;
  background: rgba(0,0,0,0.1);
  margin: 0 var(--space-1);
}

.icon-btn {
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--radius-md);
  transition: all 0.2s;
  display: flex;
  align-items: center;
}
.icon-btn:hover { background-color: rgba(0,0,0,0.05); }
.icon-btn.active { color: var(--color-primary-600); background-color: var(--color-primary-50); }
.icon-btn.danger { color: var(--color-accent-rose); }
.icon-btn.danger:hover { background-color: rgba(239,68,68,0.05); }
.icon-btn.success { color: var(--color-accent-emerald); }
.icon-btn.success:hover { background-color: rgba(16,185,129,0.05); }
.icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  pointer-events: none;
}

.start-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  font-size: 0.875rem;
}

@container chat-main (max-width: 900px) {
  .chat-header {
    height: auto;
    min-height: 60px;
    padding-top: var(--space-2);
    padding-bottom: var(--space-2);
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-2);
  }

  .header-left {
    width: 100%;
    flex: 0 0 auto;
    min-height: 28px;
  }

  .header-actions {
    width: 100%;
    flex: 0 0 auto;
    overflow-x: auto;
    overflow-y: hidden;
    padding-bottom: 2px;
    scrollbar-width: thin;
  }
}
</style>
