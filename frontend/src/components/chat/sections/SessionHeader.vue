<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Play,
  Wrench,
  FolderGit2,
  RotateCcw,
  CheckCircle2,
  XCircle,
  GitPullRequest,
  FileText,
  PanelLeftClose,
  PanelLeftOpen,
} from '@/components/icons'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import ChatMoreActionsMenu from '@/components/chat/ChatMoreActionsMenu.vue'
import TaskPinButton from '@/components/floating/TaskPinButton.vue'
import CollaborationEntry from '@/components/collaboration/CollaborationEntry.vue'
import TaskStatusIcon from '@/components/chat/TaskStatusIcon.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'
import { normalizeTaskStatus, taskStatusKey } from '@/utils/taskStatus'

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
  /** 工具栏是否已随滚动自动收起（状态由视图装配层持有） */
  collapsed?: boolean
}>()

const emit = defineEmits<{
  (event: 'share'): void
  (event: 'task-details'): void
  (event: 'open-apply-patch'): void
  (event: 'toggle-tasklist'): void
  (event: 'link-requirement'): void
}>()

const { t } = useI18n()
const workspaceStore = useWorkspaceStore()

// 工具栏悬浮在会话区之上，其高度决定内容首屏的让位距离。
// 窄容器下工具栏会折行，因此用 ResizeObserver 同步真实高度，避免写死像素。
// 自动收起只切换工具栏显隐，不改让位距离，保证回看历史时滚动位置稳定。
const headerEl = ref<HTMLElement | null>(null)
let headerObserver: ResizeObserver | null = null
let headerHost: HTMLElement | null = null

const syncHeaderHeight = () => {
  if (!headerEl.value || !headerHost) return
  headerHost.style.setProperty('--chat-header-height', `${Math.ceil(headerEl.value.getBoundingClientRect().height)}px`)
}

onMounted(() => {
  headerHost = headerEl.value?.parentElement ?? null
  if (!headerHost || !headerEl.value || typeof ResizeObserver === 'undefined') return
  headerObserver = new ResizeObserver(syncHeaderHeight)
  headerObserver.observe(headerEl.value)
  syncHeaderHeight()
})

onBeforeUnmount(() => {
  headerObserver?.disconnect()
  headerObserver = null
  headerHost?.style.removeProperty('--chat-header-height')
  headerHost = null
})
</script>

<template>
  <header
    ref="headerEl"
    class="chat-header glass-panel"
    :class="{ 'is-collapsed': props.collapsed }"
    :inert="props.collapsed || undefined"
    :aria-hidden="props.collapsed ? 'true' : undefined"
    data-testid="chat-header"
  >
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
      <TaskPinButton :task-id="props.vm.currentTask.id" :task-name="props.vm.currentTask.name" :workspace-id="String(props.vm.route.params.wsId || '')" :workspace-name="workspaceStore.currentWorkspace?.name || ''" />
      <span class="task-status-indicator" data-testid="session-task-status" role="status"
        :title="t(taskStatusKey(props.vm.currentTask.status))"
        :aria-label="t(taskStatusKey(props.vm.currentTask.status))"
        :data-status="normalizeTaskStatus(props.vm.currentTask.status)">
        <TaskStatusIcon :status="props.vm.currentTask.status" :size="20" />
      </span>
      <span
        v-if="props.vm.isLocalTask"
        class="badge local-resource-badge"
        :class="`is-${props.vm.localResourceStatus}`"
        role="status"
        :title="props.vm.localResourceBlocked ? '恢复在线后才能发送、撤回或操作本地资源' : '本地资源服务已连接'"
      >
        <span class="resource-status-dot"></span>
        {{ props.vm.localResourceLabel }}
      </span>
    </div>
    <div class="header-actions">
      <button
        v-if="props.vm.isStartActionVisible"
        class="start-task-btn start-btn"
        :class="{ 'is-disabled': !props.vm.canClickStartAction, 'is-ready': props.vm.canClickStartAction }"
        :disabled="!props.vm.canClickStartAction"
        :title="props.vm.isTaskProvisioning ? t('chat.task_provisioning_hint') : ''"
        data-testid="start-task-btn"
        @click="props.vm.handleStartClick"
      >
        <Play class="btn-play-icon" aria-hidden="true" />
        <span class="btn-label">{{ t('chat.engine_start') }}</span>
      </button>

      <div class="action-divider"></div>

      <button
        v-if="props.vm.isDiagnosisTask && props.vm.currentTask.status === 'COMPLETED' && props.vm.canManageTaskStatus"
        class="btn-micro"
        @click="emit('link-requirement')"
      >
        <FileText class="w-4 h-4" /> {{ t('task_rail.link_requirement') }}
      </button>

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
      <button class="icon-btn danger" :disabled="props.vm.isTerminalStatus || !props.vm.canCloseTask"
        @click="props.vm.handleInterruptClick"
        :title="t(props.vm.isTaskProvisioning ? 'provisioning.cancel_confirm_title' : 'chat.mark_failed_confirm')">
        <XCircle class="w-4 h-4" />
      </button>
      <button class="icon-btn success" :disabled="props.vm.isTaskProvisioning || props.vm.isTerminalStatus || !props.vm.canCloseTask" @click="props.vm.handleCompleteClick" :title="t('chat.complete_task')">
        <CheckCircle2 class="w-4 h-4" />
      </button>

      <CollaborationEntry v-if="props.vm.collaboration?.supported.value" :controller="props.vm.collaboration" @open="emit('open-apply-patch')" />
      <button class="btn-micro" v-else-if="!props.vm.hidePatchWorkflows" :disabled="!props.vm.currentTask" @click="emit('open-apply-patch')">
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
        show-attribution
        :attribution-active="props.vm.contextWindowDrawerOpen"
        @export="props.vm.handleExport"
        @open-attribution="props.vm.openContextWindowDrawer"
        @share="emit('share')"
        @task-details="emit('task-details')"
      />
    </div>
  </header>
</template>

<style scoped>
.chat-header {
  position: absolute;
  /* 顶距由聊天区变量统一提供，内容让位据此计算工具栏真实底边 */
  top: var(--chat-header-top, 10px);
  left: 14px;
  right: 14px;
  min-height: 54px;
  min-width: 0;
  padding: var(--space-2) var(--space-4);
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  border-radius: 14px;
  border: 1px solid rgba(203, 213, 225, 0.5);
  /* 磨玻璃：更透的冷白底 + 轻渐变高光，滚动内容透出时保留模糊与饱和度 */
  background-color: var(--chat-header-glass, rgba(241, 245, 249, 0.38));
  background-image: linear-gradient(180deg, rgba(255, 255, 255, 0.24), rgba(255, 255, 255, 0.04));
  backdrop-filter: blur(22px) saturate(1.8);
  -webkit-backdrop-filter: blur(22px) saturate(1.8);
  box-shadow:
    0 12px 32px -22px rgba(15, 23, 42, 0.42),
    0 1px 2px rgba(15, 23, 42, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.45);
  z-index: 30;
  flex-shrink: 0;
  transform-origin: top center;
  transition:
    transform 0.34s cubic-bezier(0.22, 1, 0.36, 1),
    opacity 0.22s ease,
    background-color 0.2s ease,
    box-shadow 0.24s ease;
  will-change: transform, opacity;
}
.chat-header:hover {
  background-color: var(--chat-header-glass-hover, rgba(248, 250, 252, 0.52));
  box-shadow:
    0 16px 36px -24px rgba(15, 23, 42, 0.45),
    0 1px 2px rgba(15, 23, 42, 0.05),
    inset 0 1px 0 rgba(255, 255, 255, 0.55);
}
/* 自动收起：向上回看历史时整条工具栏滑出圆角工作区 */
.chat-header.is-collapsed {
  transform: translateY(calc(-100% - 18px));
  opacity: 0;
  pointer-events: none;
}
/* 不支持背景滤镜时退化为高不透明度底色，保证工具栏文字可读 */
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .chat-header {
    background-color: rgba(248, 250, 252, 0.96);
    background-image: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .chat-header {
    transition: none;
  }
}
.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1 1 280px;
  min-width: 0;
  overflow: hidden;
}
.tasklist-toggle-btn {
  flex: 0 0 auto;
}
.header-left h2 {
  margin: 0;
  flex: 0 1 auto;
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 1.125rem;
}
.header-left > :not(h2) {
  flex: 0 0 auto;
}

.task-status-indicator {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
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

.badge.local-resource-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px 2px 7px;
  border-radius: 9999px;
  font-size: 0.72rem;
  font-weight: 500;
  letter-spacing: 0.01em;
  border: 1px solid transparent;
  transition: all var(--transition-fast, 150ms ease);
}

.resource-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.badge.local-resource-badge.is-online {
  background-color: #ecfdf5;
  color: #047857;
  border-color: rgba(16, 185, 129, 0.28);
}

.badge.local-resource-badge.is-online .resource-status-dot {
  background-color: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
}

.badge.local-resource-badge.is-offline {
  background-color: #fef2f2;
  color: #b91c1c;
  border-color: rgba(239, 68, 68, 0.28);
}

.badge.local-resource-badge.is-offline .resource-status-dot {
  background-color: #ef4444;
  box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.18);
}

.badge.local-resource-badge.is-checking {
  background-color: #fffbeb;
  color: #b45309;
  border-color: rgba(245, 158, 11, 0.28);
}

.badge.local-resource-badge.is-checking .resource-status-dot {
  background-color: #f59e0b;
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.18);
  animation: resource-dot-pulse 1.4s ease-in-out infinite;
}

@keyframes resource-dot-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 0 auto;
  min-width: 0;
  max-width: 100%;
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
  padding: 3px;
  border-radius: 9999px;
  background: rgba(148, 163, 184, 0.16);
}
.mode-toggle-btn {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  border-radius: 9999px;
  padding: 4px 12px;
  font-size: 0.75rem;
  cursor: pointer;
  box-shadow: 0 0 0 rgba(15, 23, 42, 0);
  transition:
    background-color 0.18s ease,
    color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s cubic-bezier(0.22, 1, 0.36, 1);
}
.mode-toggle-btn:hover {
  color: var(--color-text-body);
  transform: translateY(-1px);
}
.mode-toggle-btn.active {
  background: #ffffff;
  color: var(--color-primary-700);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
}
.mode-toggle-btn.active:hover {
  color: var(--color-primary-700);
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.3), 0 1px 2px rgba(15, 23, 42, 0.08);
}
.mode-toggle-btn:active {
  transform: translateY(0);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.1);
}
.mode-toggle-btn:focus-visible {
  outline: 2px solid var(--color-primary-400, #38bdf8);
  outline-offset: 1px;
}
@media (prefers-reduced-motion: reduce) {
  .mode-toggle-btn { transition: none; }
  .mode-toggle-btn:hover,
  .mode-toggle-btn:active { transform: none; }
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
  border-radius: 9999px;
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

/* ─── 启动任务主动作按钮（与顶栏胶囊完全对齐的白底天蓝微质感设计） ─── */
.start-task-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 4px 14px 4px 12px;
  border-radius: 9999px;
  background: #ffffff;
  color: #0284c7;
  border: 1px solid #7dd3fc;
  box-shadow: 0 1px 2px rgba(14, 165, 233, 0.08), 0 1px 2px rgba(0, 0, 0, 0.03);
  font-family: inherit;
  font-size: 0.75rem;
  font-weight: 600;
  line-height: 1.5;
  cursor: pointer;
  white-space: nowrap;
  user-select: none;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 1;
}

/* 就绪待启动：边缘环绕流光动效（Border Beam），提示用户点击此处开始任务 */
.start-task-btn.is-ready:not(:disabled) {
  overflow: hidden;
  border-color: transparent;
  box-shadow:
    0 1px 3px rgba(14, 165, 233, 0.18),
    0 0 0 1px rgba(14, 165, 233, 0.25);
}

.start-task-btn.is-ready:not(:disabled)::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 320%;
  height: 700%;
  background: conic-gradient(
    transparent 0deg,
    rgba(14, 165, 233, 0.12) 60deg,
    #38bdf8 120deg,
    #ffffff 150deg,
    #0284c7 170deg,
    transparent 230deg
  );
  transform: translate(-50%, -50%) rotate(0deg);
  animation: start-beam-rotate 3.2s linear infinite;
  z-index: -2;
}

.start-task-btn.is-ready:not(:disabled)::after {
  content: '';
  position: absolute;
  inset: 1.5px;
  border-radius: 9999px;
  background: #ffffff;
  z-index: -1;
  transition: background 0.2s ease;
}

@keyframes start-beam-rotate {
  from { transform: translate(-50%, -50%) rotate(0deg); }
  to { transform: translate(-50%, -50%) rotate(360deg); }
}

.start-task-btn .btn-play-icon {
  width: 12px;
  height: 12px;
  fill: currentColor;
  stroke: currentColor;
  stroke-width: 1;
  flex-shrink: 0;
  margin-left: 1px;
  transition: transform 0.2s ease;
  z-index: 1;
}

.start-task-btn .btn-label {
  display: inline-block;
  line-height: 1.5;
  z-index: 1;
}

.start-task-btn:hover:not(:disabled) {
  color: #0369a1;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.25), 0 0 0 1px #0284c7;
  transform: translateY(-0.5px);
}

.start-task-btn.is-ready:hover:not(:disabled)::after {
  background: #f0f9ff;
}

.start-task-btn:hover:not(:disabled) .btn-play-icon {
  transform: scale(1.08);
}

.start-task-btn:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: inset 0 1px 2px rgba(14, 165, 233, 0.12);
}

.start-task-btn.is-ready:active:not(:disabled)::after {
  background: #e0f2fe;
}

/* 禁用态（环境准备中或无权限） */
.start-task-btn:disabled,
.start-task-btn.is-disabled {
  background: rgba(248, 250, 252, 0.8);
  color: #94a3b8;
  border-color: #e2e8f0;
  box-shadow: none;
  transform: none;
  cursor: not-allowed;
  pointer-events: auto;
  overflow: visible;
}

.start-task-btn:disabled::before,
.start-task-btn:disabled::after,
.start-task-btn.is-disabled::before,
.start-task-btn.is-disabled::after {
  display: none;
}

.start-task-btn:disabled .btn-play-icon,
.start-task-btn.is-disabled .btn-play-icon {
  fill: #94a3b8;
  stroke: #94a3b8;
  transform: none;
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
