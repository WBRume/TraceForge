<script setup lang="ts">
import { proxyRefs, ref } from 'vue'
import {
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Database,
  TestTube,
  OctagonPause,
  RotateCcw,
  DollarSign,
  Clock,
  XCircle,
  Brain,
  Wrench,
  ChevronDown,
  Download,
  Loader2,
  Play,
  Plus,
  CheckCircle2,
  AlertCircle,
  BarChart3,
  FileText,
  GitPullRequest,
  FolderGit2,
} from 'lucide-vue-next'
import NewTaskModal from '@/components/NewTaskModal.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import DocReviewWorkbench from '@/components/doc-review/DocReviewWorkbench.vue'
import SuperpowersDocsPanel from '@/components/chat/SuperpowersDocsPanel.vue'
import ChatExecutionInput from '@/components/chat/ChatExecutionInput.vue'
import ChatCliWorkbench from '@/components/chat/terminal/ChatCliWorkbench.vue'
import TaskSkillsDrawer from '@/components/chat/TaskSkillsDrawer.vue'
import ContextWindowDrawer from '@/components/chat/context-window/ContextWindowDrawer.vue'
import ApplyPatchDrawer from '@/components/local-agent/ApplyPatchDrawer.vue'
import TaskCloseoutPanel from '@/components/chat/task-closeout/TaskCloseoutPanel.vue'
import ChatMessageBubble from '@/components/chat/ChatMessageBubble.vue'
import DiagnosisDocsDrawer from '@/components/chat/DiagnosisDocsDrawer.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import { useChatViewModel } from '@/composables/useChatViewModel'

const rawVm = useChatViewModel()
const vm = proxyRefs(rawVm)
const showApplyPatchDrawer = ref(false)

const statusMessageText = (message: unknown): string => (
  String(message || '').replace(/\s*\(model:\s*[^)]*\)\s*$/i, '').trim()
)

const statusModelText = (card: any): string => {
  const explicit = String(card?.model || '').trim()
  if (explicit) return explicit
  const match = String(card?.message || '').match(/\(model:\s*([^)]+)\)/i)
  return match?.[1]?.trim() || ''
}
</script>
<template>
  <div class="chat-layout">
    <!-- Left Sidebar: Task List -->
    <aside class="task-sidebar glass-panel">
      <div class="sidebar-header">
        <div class="sidebar-title-row">
          <h3>{{ $t('chat.terminal') }}</h3>
          <button class="new-session-btn" :disabled="!vm.canCreateTask" @click="vm.openNewTaskModal" :title="$t('dashboard.new_task')">
            <Plus class="w-4 h-4" />
          </button>
        </div>
        <div class="sidebar-filter-row">
          <span class="sidebar-filter-label">{{ $t('chat.session_filter_label') }}</span>
          <BaseSelect
            v-model="vm.taskStatusFilter"
            :options="[
              { label: $t('chat.session_filter_all'), value: 'ALL' },
              { label: $t('chat.session_filter_success'), value: 'DONE' },
              { label: $t('chat.session_filter_failed'), value: 'FAILED' },
            ]"
            size="sm"
            class="task-filter-select"
            @update:modelValue="vm.applyTaskStatusFilter"
          />
          <BaseSelect
            v-model="vm.taskTypeFilter"
            :options="[
              { label: $t('chat.session_type_all'), value: 'ALL' },
              { label: $t('task_types.development'), value: 'DEVELOPMENT' },
              { label: $t('task_types.diagnosis'), value: 'DIAGNOSIS' },
            ]"
            size="sm"
            class="task-filter-select"
            @update:modelValue="vm.applyTaskTypeFilter"
          />
        </div>
      </div>
      <div class="task-list" :ref="rawVm.taskListContainer" @scroll="vm.handleTaskListScroll">
        <div
          v-for="task in vm.tasks"
          :key="task.id"
          class="task-item group"
          :class="{ active: vm.currentTask?.id === task.id }"
          @click="vm.selectTask(task)"
        >
          <div class="task-item-content">
            <div class="task-name-row">
              <div class="task-name">{{ task.name }}</div>
              <div class="task-status">
                <span class="status-dot" :class="task.status.toLowerCase()"></span>
                {{ task.status }}
              </div>
            </div>
            <div class="task-meta" v-if="task.creator_name || task.created_at">
              <span v-if="task.creator_name" class="task-creator">{{ task.creator_name }}</span>
              <span v-if="task.created_at" class="task-date">{{ vm.formatTime(task.created_at) }}</span>
            </div>
          </div>
          <DeleteActionButton
            mode="icon"
            class="delete-btn"
            :title="$t('common.delete')"
            :disabled="!vm.canDeleteTask"
            @click.stop="vm.handleDeleteTask(task)"
          />
        </div>
        <div v-if="vm.taskListLoading && vm.tasks.length === 0" class="empty-hint">
          {{ $t('common.loading') }}
        </div>
        <div v-else-if="vm.tasks.length === 0" class="empty-hint">
          {{ $t('chat.empty_hint') }}
        </div>
        <div v-if="vm.taskListLoadingMore" class="task-list-footer">
          <Loader2 class="w-4 h-4 spin" />
          <span>{{ $t('common.loading') }}</span>
        </div>
        <div v-else-if="vm.taskListHasMore" class="task-list-footer task-list-footer-hint">
          {{ $t('chat.session_scroll_load_more') }}
        </div>
      </div>
    </aside>

    <!-- Center: Chat + Pinned Cards -->
    <section class="chat-main" v-if="vm.currentTask">
      <!-- Header -->
      <header class="chat-header glass-panel">
        <div class="header-left">
          <h2>{{ vm.currentTask.name }}</h2>
          <span class="badge" :class="vm.currentTask.status.toLowerCase()">{{ vm.currentTask.status }}</span>
          <Loader2 v-if="vm.engineRunning" class="w-4 h-4 spin text-primary" />
        </div>
        <div class="header-actions">
          <button
            v-if="vm.isStartActionVisible"
            class="btn-primary start-btn"
            :disabled="!vm.canClickStartAction"
            @click="vm.handleStartClick"
          >
            <Play class="w-4 h-4" /> {{ $t('chat.engine_start') }}
          </button>

          <div class="action-divider"></div>

          <button class="btn-micro" :disabled="!vm.currentTask" @click="vm.openTaskSkillsDrawer">
            <Wrench class="w-4 h-4" />
            {{ $t('chat.task_skills_button', { count: vm.taskRuntimeSkillCount }) }}
          </button>

          <button
            v-if="vm.isDiagnosisTask"
            class="btn-micro"
            :class="{ active: vm.diagnosisDocsDrawerOpen }"
            :disabled="!vm.currentTask"
            @click="vm.toggleDiagnosisDocsDrawer"
          >
            <FolderGit2 class="w-4 h-4" />
            {{ $t('diagnosis.docs_drawer_button') }}
          </button>

          <button class="icon-btn" :disabled="!vm.canInitializeAction" @click="vm.handleInitialize" :title="$t('chat.initialize')">
            <RotateCcw class="w-4 h-4" />
          </button>
          <button class="icon-btn danger" :disabled="vm.isTerminalStatus || !vm.canManageTaskStatus" @click="vm.handleInterruptClick" :title="$t('chat.mark_failed_confirm')">
            <OctagonPause class="w-4 h-4" />
          </button>
          <button class="icon-btn success" :disabled="vm.isTerminalStatus || !vm.canManageTaskStatus" @click="vm.handleCompleteClick" :title="$t('chat.complete_task')">
            <CheckCircle2 class="w-4 h-4" />
          </button>

          <button class="icon-btn" :disabled="!vm.canExportTask" @click="vm.handleExport" title="Export Session">
            <Download class="w-4 h-4" />
          </button>
          <button class="btn-micro" v-if="!vm.hidePatchWorkflows" :disabled="!vm.currentTask" @click="showApplyPatchDrawer = true">
            <GitPullRequest class="w-4 h-4" />
            {{ $t('chat.change_apply_button') }}
          </button>
          <div class="mode-toggle">
            <button
              class="mode-toggle-btn"
              :class="{ active: vm.chatWorkbenchMode === 'platform' }"
              @click="vm.setChatWorkbenchMode('platform')"
            >
              {{ $t('chat.mode_platform') }}
            </button>
            <button
              class="mode-toggle-btn"
              :class="{ active: vm.chatWorkbenchMode === 'cli' }"
              @click="vm.setChatWorkbenchMode('cli')"
            >
              {{ $t('chat.mode_cli') }}
            </button>
          </div>
          <button
            v-if="vm.chatWorkbenchMode === 'platform'"
            class="icon-btn"
            :class="{ active: vm.contextWindowDrawerOpen }"
            @click="vm.openContextWindowDrawer"
            :title="$t('chat.context_window_button')"
          >
            <BarChart3 class="w-4 h-4" />
          </button>
          <button
            v-if="vm.showSpecEntryButton"
            class="icon-btn"
            :class="{ active: vm.isSpecPanelOpen && vm.isSpecDrawerAvailable }"
            @click="vm.handleSpecEntryClick"
            :title="vm.isTaskPreStart ? $t('chat.spec_open_workspace') : $t('chat.spec_toggle_drawer')"
          >
            <FileText class="w-4 h-4" />
          </button>
          <DeleteActionButton
            mode="icon"
            :title="$t('common.delete')"
            :disabled="!vm.canDeleteTask"
            @click="vm.handleDeleteTask(vm.currentTask)"
          />
        </div>
      </header>

      <div v-if="vm.isTaskPreStart && vm.currentTaskHasSpec" class="prestart-doc-tip glass-panel">
        <p>{{ $t('chat.spec_prestart_hint') }}</p>
        <div v-if="vm.specBootstrapLoading" class="bootstrap-status">
          <span>{{ $t('chat.spec_bootstrap_loading') }}</span>
        </div>
        <div v-else-if="vm.specBootstrap" class="bootstrap-status">
          <div class="bootstrap-status-main">
            <Loader2 v-if="vm.isSpecBootstrapActive" class="w-4 h-4 spin text-primary" />
            <span>{{ vm.bootstrapStatusText(vm.specBootstrap.status) }} · {{ vm.specBootstrap.progress }}%</span>
          </div>
          <p v-if="vm.specBootstrap.message" class="bootstrap-status-message">{{ vm.specBootstrap.message }}</p>
          <p v-if="vm.specBootstrap.error_message" class="bootstrap-status-error">{{ vm.specBootstrap.error_message }}</p>
        </div>
        <div v-else class="bootstrap-status">
          <span>{{ $t('chat.spec_bootstrap_not_initialized') }}</span>
        </div>
        <button class="btn-secondary" @click="vm.openSpecWorkspace">
          {{ $t('chat.spec_open_workspace') }}
        </button>
      </div>

      <template v-if="vm.chatWorkbenchMode === 'platform'">
      <!-- �?置顶富文本卡片区 (独立，不随对话滚�? -->
      <div class="pinned-cards-area" v-if="vm.activeHitlCards.length > 0 || vm.statusCards.length > 0 || vm.showThinking || vm.resultsSummary.visible">

        <!-- AI 思考面�?-->
        <div v-if="vm.showThinking && vm.thinkingContent" class="pinned-card thinking-card">
          <div
            class="card-header thinking-header"
            role="button"
            :aria-expanded="vm.thinkingExpanded"
            @click="vm.thinkingExpanded = !vm.thinkingExpanded"
          >
          <div class="header-title flex items-center gap-2">
            <Brain class="w-4 h-4" />
            <span>{{ $t('chat.thinking') }}</span>
          </div>
            <ChevronDown class="w-4 h-4 toggle-icon transition-transform" :class="{'rotate-180': vm.thinkingExpanded}" />
          </div>
          <div v-show="vm.thinkingExpanded" class="card-body thinking-body fixed-height">
            <pre>{{ vm.thinkingContent }}</pre>
          </div>
        </div>

        <!-- 运行状态与任务状态分布 -->
        <div
          v-if="vm.statusCards.length > 0 || vm.resultsSummary.visible"
          class="pinned-card run-summary-card"
          :class="{ 'is-error': vm.statusCards.some(card => card.status === 'FAILED') }"
        >
          <div class="run-summary-header">
            <div class="run-status-stack">
              <div v-if="vm.statusCards.length > 0" class="run-status-list">
                <div v-for="card in vm.statusCards" :key="card.id" class="run-status-item">
                  <CheckCircle2 v-if="card.status === 'COMPLETED'" class="w-4 h-4 text-success" />
                  <XCircle v-else-if="card.status === 'FAILED'" class="w-4 h-4 text-error" />
                  <Loader2 v-else class="w-4 h-4 spin text-primary" />
                  <span class="run-status-text">{{ statusMessageText(card.message) }}</span>
                  <span v-if="statusModelText(card)" class="run-model-pill">{{ statusModelText(card) }}</span>
                </div>
              </div>
              <div v-else class="run-status-item">
                <CheckCircle2 class="w-4 h-4 text-success" />
                <span class="run-status-text">{{ $t('dashboard.status_dist') }}</span>
              </div>
            </div>
            <div class="run-summary-meta">
              <span v-if="vm.resultsSummary.visible" class="run-metric">
                <Clock class="w-3 h-3" /> {{ (vm.resultsSummary.totalDurationMs / 1000).toFixed(1) }}s
              </span>
              <span v-if="vm.resultsSummary.visible" class="run-metric">
                <DollarSign class="w-3 h-3" /> ${{ vm.resultsSummary.totalCostUsd.toFixed(4) }}
              </span>
              <Transition name="run-summary-toggle-motion">
                <button
                  v-if="vm.resultsSummary.visible"
                  class="run-summary-toggle"
                  type="button"
                  :title="$t('dashboard.status_dist')"
                  @click="vm.resultsSummary.expanded = !vm.resultsSummary.expanded"
                >
                  <ChevronDown class="w-4 h-4 transition-transform inline" :class="{'rotate-180': vm.resultsSummary.expanded}" />
                </button>
              </Transition>
            </div>
          </div>
          <div v-show="vm.resultsSummary.expanded" class="card-body flex flex-col gap-2 mt-2 border-t pt-2 border-gray-100">
            <div v-for="(step, idx) in vm.resultsSummary.history" :key="step.id" class="text-xs text-slate-500 flex justify-between items-center bg-gray-50 p-1.5 rounded">
              <span class="flex items-center gap-1">
                <CheckCircle2 v-if="step.success" class="w-3 h-3 text-green-500" />
                <XCircle v-else class="w-3 h-3 text-red-500" />
                {{ $t('chat.stage_step', { index: idx + 1, timestamp: step.timestamp }) }}
              </span>
              <span class="flex gap-2">
                <span v-if="step.duration_ms"><Clock class="w-3 h-3 inline"/> {{ (step.duration_ms / 1000).toFixed(1) }}s</span>
                <span v-if="step.cost_usd"><DollarSign class="w-3 h-3 inline"/> ${{ step.cost_usd.toFixed(4) }}</span>
              </span>
            </div>
          </div>
        </div>

        <!-- HITL 交互卡片 -->
        <div v-for="card in vm.activeHitlCards" :key="card.id" class="pinned-card hitl-card">
          <div class="card-header hitl-header">
            <AlertCircle class="w-5 h-5 text-amber" />
            <h4>{{ $t('chat.interrupt_confirm') }}</h4>
          </div>
          <div class="card-body">
            <p class="hitl-prompt">{{ card.prompt }}</p>
            <div v-if="card.context" class="context-box">
              <code>{{ card.context }}</code>
            </div>
          </div>
          <div class="hitl-actions">
            <template v-if="card.hitl_type === 'boolean'">
              <button class="btn-success" @click="vm.submitHitl(card.id, 'y')">{{ $t('common.confirm') }} (Y)</button>
              <button class="btn-danger" @click="vm.submitHitl(card.id, 'n')">{{ $t('common.cancel') }} (N)</button>
            </template>
            <template v-else>
              <input
                type="text"
                v-model="card.tempInput"
                placeholder="..."
                class="input-field hitl-input"
                @keyup.enter="vm.submitHitl(card.id, card.tempInput)"
              >
              <button class="btn-primary" @click="vm.submitHitl(card.id, card.tempInput)">{{ $t('common.confirm') }}</button>
            </template>
          </div>
        </div>
      </div>

      <!-- �?对话气泡�?(仅自然语言) -->
      <div class="chat-history" :ref="rawVm.chatContainer" @scroll="vm.handleChatScroll">
        <div v-if="vm.loadingMore" class="loading-more-hint">
          <Loader2 class="w-4 h-4 spin" />
          <span>{{ $t('common.loading') }}</span>
        </div>
        <div v-else-if="vm.hasMore" class="load-more-hint" @click="vm.loadOlderMessages">
          �?{{ $t('common.load_more') }}
        </div>
        <template v-for="msg in vm.messages" :key="msg.id">
          <!-- 会话分隔线：每次初始化产�?-->
          <div
            v-if="msg.message_type === 'init_reason'"
            class="session-separator"
            :class="{ 'is-highlighted': vm.highlightedMessageId === msg.id }"
            :data-message-id="msg.id"
          >
            <div class="separator-line"></div>
            <div class="separator-content">
              <span class="separator-time">{{ vm.formatTime(msg.created_at) }}</span>
              <span v-if="msg.content" class="separator-reason">{{ msg.content }}</span>
            </div>
            <div class="separator-line"></div>
          </div>
          <!-- 普通消息气泡 -->
          <ChatMessageBubble
            v-else
            :msg="msg"
            :vm="vm"
          />
        </template>

        <div v-if="vm.messages.length === 0" class="chat-empty-hint">
          <p>{{ $t('chat.empty_hint') }}</p>
        </div>
      </div>

      <!-- Verification Quick Actions -->
      <div v-if="!vm.hidePatchWorkflows && !vm.engineRunning && vm.messages.length > 0 && !vm.isChatLocked" class="verification-actions">
        <span class="verify-label">{{ $t('portal.architecture') }}:</span>
        <button class="btn-micro" @click="vm.sendVerification('ui')" title="Playwright UI">
          <TestTube class="w-3" /> UI
        </button>
        <button class="btn-micro" @click="vm.sendVerification('api')" title="Postman API">
          <Database class="w-3" /> API
        </button>
        <button class="btn-micro" @click="vm.sendVerification('e2e')" :title="$t('chat.verification_e2e_title')">
          <Sparkles class="w-3" /> E2E
        </button>
      </div>

      <!-- 问题定位结果已改为会话内 AI 气泡卡片（DiagnosisResultCard），此处不再渲染独立面板 -->

      <!-- Input Area -->
      <ChatExecutionInput
        v-model="vm.chatInput"
        :disabled="vm.isChatLocked || vm.sendingChat"
        :running="vm.engineRunning"
        :can-interrupt="vm.canTemporarilyInterrupt"
        :interrupting="vm.interruptingTask"
        :placeholder="vm.chatInputPlaceholder"
        :send-title="$t('chat.send_message')"
        :interrupt-title="$t('chat.temporary_interrupt_desc')"
        @submit="vm.sendChat"
        @interrupt="vm.interruptCurrentRun"
      />
      </template>
      <template v-else>
        <div class="cli-shell-wrapper">
          <ChatCliWorkbench :vm="vm" />
        </div>
      </template>
    </section>

    <!-- Empty State -->
    <section class="chat-main empty-state" v-else>
      <Loader2 class="w-8 h-8 spin text-primary-light" />
      <p class="empty-text">{{ $t('chat.empty_hint') }}</p>
    </section>

    <aside
      v-if="vm.isSpecDrawerAvailable"
      class="spec-sidebar glass-panel"
      :class="{
        'is-open': vm.isSpecPanelOpen,
        'level-1': vm.specDrawerLevel === 1,
        'level-2': vm.specDrawerLevel === 2,
        'level-3': vm.specDrawerLevel === 3,
      }"
    >
      <!-- Simplified Side Handles -->
      <div class="spec-side-handles">
        <div class="side-handle-group">
          <button
            class="side-handle-btn"
            :disabled="vm.specDrawerLevel === 3"
            @click="vm.handleExpandDrawer"
            :title="$t('common.expand')"
          >
            <ChevronLeft :size="20" />
          </button>
          
          <div class="handle-divider"></div>

          <button
            class="side-handle-btn"
            @click="vm.handleCollapseDrawer"
            :title="vm.specDrawerLevel === 1 ? $t('common.close') : $t('common.collapse')"
          >
            <ChevronRight :size="20" />
          </button>
        </div>
      </div>

      <div class="spec-body" v-show="vm.isSpecPanelOpen && vm.currentTask">
        <div class="spec-tabbar">
          <button 
            class="tab-item" 
            :class="{ active: vm.specDrawerTab === 'spec_doc' }"
            @click="vm.specDrawerTab = 'spec_doc'"
          >
            <div v-show="vm.specDrawerTab === 'spec_doc' && vm.currentTaskHasSpec" class="pulse-dot-inline"></div>
            <FileText :size="14" />
            <span>{{ $t('chat.spec_drawer_tab_requirement') }}</span>
          </button>
          <button 
            class="tab-item" 
            :class="{ active: vm.specDrawerTab === 'superpowers_docs' }"
            @click="vm.specDrawerTab = 'superpowers_docs'"
          >
            <div v-show="vm.specDrawerTab === 'superpowers_docs'" class="pulse-dot-inline"></div>
            <Brain :size="14" />
            <span>{{ $t('chat.spec_drawer_tab_superpowers') }}</span>
          </button>
        </div>
        <!-- Legacy tabbar removed as it's now in the side handles -->
        <div class="spec-tab-panels">
          <div
            v-if="vm.currentTaskHasSpec"
            class="spec-tab-panel"
            v-show="vm.specDrawerTab === 'spec_doc'"
          >
            <DocReviewWorkbench
              :ws-id="String(vm.route.params.wsId || '')"
              :task-id="vm.currentTask.id"
              :initial-asset-id="vm.activeInitialSpecAssetId || undefined"
              :readonly="true"
              compact
            />
          </div>
          <div
            class="spec-tab-panel"
            v-show="vm.specDrawerTab === 'superpowers_docs'"
          >
            <SuperpowersDocsPanel
              :ws-id="String(vm.route.params.wsId || '')"
              :task-id="vm.currentTask.id"
              :readonly="!vm.canEditSuperpowersDocs"
            />
          </div>
        </div>
      </div>
      <div class="spec-empty" v-show="vm.isSpecPanelOpen && !vm.currentTask">
        {{ $t('chat.spec_drawer_empty') }}
      </div>
    </aside>

    <!-- 问题定位任务：诊断文档/代码路径抽屉（替代需求文档抽屉） -->
    <DiagnosisDocsDrawer
      v-if="vm.isDiagnosisTask && vm.currentTask"
      :open="vm.diagnosisDocsDrawerOpen"
      :ws-id="String(vm.route.params.wsId || '')"
      :task-id="vm.currentTask.id"
      @close="vm.closeDiagnosisDocsDrawer"
    />

    <!-- ─── Modals and Drawers ─── -->
    <NewTaskModal 
      :show="vm.showTaskModal" 
      :wsId="(vm.route.params.wsId as string)" 
      @close="vm.showTaskModal = false" 
      @created="vm.onTaskCreated" 
    />

    <ApplyPatchDrawer
      :show="showApplyPatchDrawer"
      :task="vm.currentTask"
      :workspace="vm.currentWorkspace"
      @close="showApplyPatchDrawer = false"
    />

    <TaskCloseoutPanel
      v-if="vm.currentTask && vm.closeoutMode"
      :show="Boolean(vm.closeoutMode)"
      :mode="vm.closeoutMode"
      :workspace-id="String(vm.route.params.wsId || '')"
      :task-id="vm.currentTask.id"
      :task-name="vm.currentTask.name"
      @close="vm.closeTaskCloseout"
      @success="vm.handleTaskCloseoutSuccess"
    />


    <ConfirmActionModal
      :show="vm.showStartConfirm"
      :title="$t('chat.start_confirm_title')"
      :message="$t('chat.start_confirm_message')"
      :description="$t('chat.start_confirm_description')"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('chat.engine_start')"
      tone="primary"
      :loading="vm.startingTask"
      @cancel="vm.showStartConfirm = false"
      @confirm="vm.startTask"
    />

    <!-- Initialize Reason Modal -->
    <div
      v-if="vm.showInitReasonModal"
      class="modal-overlay"
      @pointerdown.self="vm.showInitReasonModal = false"
    >
      <div class="modal glass-panel" style="border-top: 4px solid var(--color-primary-500);">
        <div class="modal-header">
          <RotateCcw class="w-6 h-6" style="color: var(--color-primary-600);" />
          <span>{{ $t('chat.init_reason_title') }}</span>
        </div>
        <div class="modal-form">
          <div class="form-group">
            <label>{{ $t('chat.init_reason_label') }}</label>
            <input
              type="text"
              v-model="vm.initReason"
              :placeholder="$t('chat.init_reason_placeholder')"
              class="input-field"
              @keyup.enter="vm.confirmInitialize"
            />
          </div>
          <div class="form-group">
            <label>{{ $t('chat.task_skills_init_label') }}</label>
            <div class="init-skill-list">
              <div v-if="vm.initSkillOptionsLoading" class="init-skill-state">{{ $t('common.loading') }}</div>
              <div v-else-if="vm.initSkillOptions.length === 0" class="init-skill-state">
                {{ $t('chat.task_skills_empty') }}
              </div>
              <label v-else v-for="skill in vm.initSkillOptions" :key="skill.id" class="init-skill-item">
                <input v-model="vm.initSelectedSkillIds" type="checkbox" :value="skill.id" />
                <span class="init-skill-name">{{ skill.name }}</span>
                <span class="init-skill-meta">{{ skill.dimension }}</span>
              </label>
            </div>
            <div v-if="vm.deletedRuntimeSkillNamesForInitialize.length > 0" class="init-skill-deleted-warning">
              {{ $t('chat.task_skills_deleted_runtime_warning', {
                names: vm.deletedRuntimeSkillNamesForInitialize.join(', ')
              }) }}
            </div>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn-secondary" @click="vm.showInitReasonModal = false">{{ $t('common.cancel') }}</button>
          <button
            class="btn-primary"
            :disabled="vm.initSkillOptionsLoading || vm.taskRuntimeSkillsLoading"
            @click="vm.confirmInitialize"
          >
            {{ $t('chat.init_reason_confirm') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Deleted Runtime Skill Confirmation Modal -->
    <div
      v-if="vm.showDeletedRuntimeSkillConfirm"
      class="modal-overlay"
      @pointerdown.self="vm.cancelDeletedRuntimeSkillConfirm"
    >
      <div class="modal glass-panel warning-modal">
        <div class="modal-header warning">
          <AlertCircle class="w-6 h-6" />
          <span>{{ $t('chat.task_skills_deleted_runtime_confirm_title') }}</span>
        </div>
        <p class="delete-desc">
          {{ $t('chat.task_skills_deleted_runtime_confirm_desc', {
            names: vm.deletedRuntimeSkillNamesForInitialize.join(', ')
          }) }}
        </p>
        <div class="modal-actions">
          <button class="btn-secondary" @click="vm.cancelDeletedRuntimeSkillConfirm">
            {{ $t('common.cancel') }}
          </button>
          <button class="btn-secondary" @click="vm.confirmInitializeWithDeletedRuntimeSkillDecision(false)">
            {{ $t('chat.task_skills_deleted_runtime_discard') }}
          </button>
          <button class="btn-primary" @click="vm.confirmInitializeWithDeletedRuntimeSkillDecision(true)">
            {{ $t('chat.task_skills_deleted_runtime_keep') }}
          </button>
        </div>
      </div>
    </div>

    <TaskSkillsDrawer
      :show="vm.showTaskSkillsDrawer"
      :loading="vm.taskRuntimeSkillsLoading"
      :skills="vm.taskRuntimeSkills"
      :selected-skill-id="vm.runtimeActiveSkillId"
      :can-edit="vm.canEditTaskRuntimeSkills"
      :file-tree="vm.runtimeFileTree"
      :file-tree-loading="vm.runtimeFileTreeLoading"
      :active-file-path="vm.runtimeActiveFilePath"
      :active-file-content="vm.runtimeActiveFileContent"
      :active-file-loading="vm.runtimeActiveFileLoading"
      :active-file-saving="vm.runtimeActiveFileSaving"
      :active-file-binary="vm.runtimeActiveFileBinary"
      :active-file-dirty="vm.runtimeActiveFileDirty"
      :trace-events="vm.runtimeTraceEvents"
      :trace-loading="vm.runtimeTraceLoading"
      @close="vm.closeTaskSkillsDrawer"
      @refresh-skills="vm.loadTaskRuntimeSkills({ hydrateEditor: vm.showTaskSkillsDrawer })"
      @refresh-trace="vm.loadTaskRuntimeTrace()"
      @select-skill="vm.selectRuntimeSkill"
      @refresh-tree="vm.loadRuntimeSkillFileTree(vm.runtimeActiveSkillId, { keepCurrentFile: true })"
      @select-file="vm.selectRuntimeSkillFile"
      @save-file="vm.saveRuntimeSkillFileContent"
      @update-file-content="vm.updateRuntimeSkillFileContent"
    />

    <ContextWindowDrawer
      :show="vm.contextWindowDrawerOpen"
      :level="vm.contextWindowDrawerLevel"
      :loading="vm.contextWindowLoading"
      :error="vm.contextWindowError"
      :data="vm.contextWindowData"
      :selected-category="vm.contextWindowSelectedCategory"
      :segments-loading="vm.contextWindowSegmentsLoading"
      @close="vm.closeContextWindowDrawer"
      @refresh="vm.refreshContextWindow"
      @select-category="vm.selectContextWindowCategory"
      @locate="vm.locateContextWindowReference"
      @update:level="vm.updateContextWindowDrawerLevel"
    />

    <ConfirmActionModal
      :show="vm.showDeleteTaskConfirm"
      :title="$t('common.delete')"
      :message="$t('dashboard.delete_confirm', { name: vm.taskToDelete?.name || '' })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.delete')"
      tone="danger"
      :loading="vm.deletingTask"
      @cancel="vm.closeDeleteTaskConfirm"
      @confirm="vm.confirmDeleteTask"
    />
  </div>
</template>

<style scoped src="@/styles/chat-view/chat-view-layout.css"></style>
<style scoped src="@/styles/chat-view/chat-view-pinned-history.css"></style>
<style scoped src="@/styles/chat-view/chat-view-spec.css"></style>
<style scoped src="@/styles/chat-view/chat-view-modal-buttons.css"></style>
<style scoped>
.session-separator.is-highlighted {
  animation: context-reference-pulse 1.3s ease-in-out 2;
}
@keyframes context-reference-pulse {
  0% { filter: drop-shadow(0 0 0 rgba(14, 165, 233, 0)); }
  45% { filter: drop-shadow(0 0 12px rgba(14, 165, 233, 0.45)); }
  100% { filter: drop-shadow(0 0 0 rgba(14, 165, 233, 0)); }
}
</style>
