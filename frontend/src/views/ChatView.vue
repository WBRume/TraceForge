<script setup lang="ts">
import { proxyRefs, ref, watch } from 'vue'
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
  GitFork,
  Upload,
} from 'lucide-vue-next'
import NewTaskModal from '@/components/NewTaskModal.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import DocReviewWorkbench from '@/components/doc-review/DocReviewWorkbench.vue'
import SuperpowersDocsPanel from '@/components/chat/SuperpowersDocsPanel.vue'
import ChatExecutionInput from '@/components/chat/ChatExecutionInput.vue'
import PreInputPanel from '@/components/chat/PreInputPanel.vue'
import ChatCliWorkbench from '@/components/chat/terminal/ChatCliWorkbench.vue'
import TaskSkillsDrawer from '@/components/chat/TaskSkillsDrawer.vue'
import ContextWindowDrawer from '@/components/chat/context-window/ContextWindowDrawer.vue'
import ApplyPatchDrawer from '@/components/local-agent/ApplyPatchDrawer.vue'
import TaskCloseoutPanel from '@/components/chat/task-closeout/TaskCloseoutPanel.vue'
import ChatMessageBubble from '@/components/chat/ChatMessageBubble.vue'
import TaskProvisionProgressModal from '@/components/TaskProvisionProgressModal.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import { useChatViewModel } from '@/composables/useChatViewModel'
import { useDiagnosisDocs, type DiagnosisDocItem } from '@/composables/useDiagnosisDocs'

const rawVm = useChatViewModel()
const vm = proxyRefs(rawVm)
const showApplyPatchDrawer = ref(false)
const preInputMode = ref(false)
const chatInputRef = ref<any>(null)

const handleStartPreInput = (payload: {
  main_text: string
  mentioned_user_ids: string[]
  edit_permission: 'ALL' | 'MENTIONED' | 'EXPERTS' | 'NONE'
  wait_seconds: number
}) => {
  const ok = rawVm.startPreInput(payload)
  if (ok) {
    preInputMode.value = false
    vm.chatInput = ''
    chatInputRef.value?.resetPreInputForm?.()
  }
}

// 问题定位任务：诊断文档 / 代码路径抽屉数据（复用 spec 抽屉三段式容器）
const diagDocsModel = useDiagnosisDocs({
  wsId: () => String(rawVm.route.params.wsId || ''),
  taskId: () => String(rawVm.currentTask?.value?.id || ''),
})
const diagDocs = proxyRefs(diagDocsModel)

const handleDiagnosisDocSelect = (event: Event) => {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length === 0) return
  for (const file of files) {
    void diagDocs.uploadDoc(file)
  }
  input.value = ''
}

const diagDocMeta = (doc: DiagnosisDocItem) => {
  const parts: string[] = []
  if (doc.source_ext) parts.push(doc.source_ext)
  if (doc.created_at) parts.push(new Date(doc.created_at).toLocaleString())
  return parts.join(' · ')
}

// 打开诊断抽屉时加载文档与代码路径
watch(
  () => [rawVm.isDiagnosisTask.value, vm.specDrawerLevel],
  () => {
    if (rawVm.isDiagnosisTask.value && vm.specDrawerLevel > 0) {
      void diagDocs.loadDocs()
      void diagDocs.loadCodePath()
    }
  },
)

// 切换任务会话时退出协作预输入模式
watch(
  () => vm.currentTask?.id,
  () => {
    preInputMode.value = false
  },
)

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
          <div class="sidebar-filter-item">
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
          </div>
          <div class="sidebar-filter-item">
            <span class="sidebar-filter-label">{{ $t('chat.session_type_label') }}</span>
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
              <span
                class="task-type-tag"
                :class="task.task_type === 'DIAGNOSIS' ? 'is-diagnosis' : 'is-development'"
              >
                {{ task.task_type === 'DIAGNOSIS' ? $t('task_types.diagnosis') : $t('task_types.development') }}
              </span>
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
          <h2 :title="vm.currentTask.name">{{ vm.currentTask.name }}</h2>
          <span class="badge" :class="vm.currentTask.status.toLowerCase()">{{ vm.currentTask.status }}</span>
          <Loader2 v-if="vm.engineRunning" class="w-4 h-4 spin text-primary" />
        </div>
        <div class="header-actions">
          <button
            v-if="vm.isStartActionVisible"
            class="btn-primary start-btn"
            :disabled="!vm.canClickStartAction"
            :title="vm.isTaskProvisioning ? $t('chat.task_provisioning_hint') : ''"
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
            :class="{ active: vm.isSpecPanelOpen }"
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

      <!-- 快捷操作行：研发态任务显示快捷验证按钮；问题定位任务显示一键总结问题案例（样式与位置保持一致） -->
      <div
        v-if="vm.messages.length > 0 && !vm.isChatLocked && (vm.isDiagnosisTask || !vm.engineRunning)"
        class="verification-actions"
      >
        <template v-if="!vm.hidePatchWorkflows">
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
        </template>
        <template v-else>
          <button
            class="btn-micro"
            :disabled="vm.engineRunning || vm.diagnosisSummarizing || vm.isDiagnosisAdopted"
            :title="vm.isDiagnosisAdopted ? $t('diagnosis.case_already_adopted_no_summary') : $t('diagnosis.summarize_case_button')"
            @click="vm.generateDiagnosisSummary"
          >
            <Loader2 v-if="vm.diagnosisSummarizing" class="w-3 h-3 spin" />
            <Sparkles v-else class="w-3 h-3" />
            {{ vm.isDiagnosisAdopted ? $t('diagnosis.case_adopted_label') : vm.diagnosisSummarizing ? $t('diagnosis.summarizing') : $t('diagnosis.summarize_case_button') }}
          </button>
        </template>
      </div>

      <!-- 问题定位结果已改为会话内 AI 气泡卡片（DiagnosisResultCard），此处不再渲染独立面板 -->

      <!-- 协作预输入：收集窗口进行中时显示在输入框上方 -->
      <PreInputPanel
        v-if="vm.activePreInput && vm.preInputIsCollecting"
        :vm="vm"
      />

      <!-- Input Area：统一输入卡（普通发送 / 协作预输入模式丝滑切换）
           收集窗口进行中只保留协作编辑框，普通输入框不再显示 -->
      <ChatExecutionInput
        v-if="!vm.preInputIsCollecting"
        ref="chatInputRef"
        v-model="vm.chatInput"
        v-model:pre-input-mode="preInputMode"
        :disabled="vm.isChatLocked || vm.sendingChat"
        :running="vm.engineRunning"
        :can-interrupt="vm.canTemporarilyInterrupt"
        :interrupting="vm.interruptingTask"
        :placeholder="vm.chatInputPlaceholder"
        :send-title="$t('chat.send_message')"
        :interrupt-title="$t('chat.temporary_interrupt_desc')"
        :can-start-pre-input="!vm.activePreInput"
        :search-members="vm.searchPreInputMembers"
        @submit="vm.sendChat"
        @interrupt="vm.interruptCurrentRun"
        @start-pre-input="handleStartPreInput"
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
      v-if="vm.currentTask && (vm.isSpecDrawerAvailable || vm.isDiagnosisTask)"
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
        <!-- 问题定位任务：诊断文档 / 代码路径 -->
        <div v-if="vm.isDiagnosisTask" class="spec-tabbar">
          <button
            class="tab-item"
            :class="{ active: vm.specDrawerTab === 'diag_docs' }"
            @click="vm.specDrawerTab = 'diag_docs'"
          >
            <FileText :size="14" />
            <span>{{ $t('diagnosis.docs_tab') }}</span>
          </button>
          <button
            class="tab-item"
            :class="{ active: vm.specDrawerTab === 'diag_code' }"
            @click="vm.specDrawerTab = 'diag_code'"
          >
            <GitFork :size="14" />
            <span>{{ $t('diagnosis.code_path_tab') }}</span>
          </button>
        </div>
        <!-- 研发态任务：需求文档 / 计划文档 -->
        <div v-else class="spec-tabbar">
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
          <!-- 问题定位：诊断文档面板 -->
          <div
            v-if="vm.isDiagnosisTask"
            class="spec-tab-panel"
            v-show="vm.specDrawerTab === 'diag_docs'"
          >
            <div class="diag-panel">
              <header class="diag-panel-header">
                <div class="diag-panel-title-group">
                  <div class="diag-panel-title-line">
                    <div class="diag-panel-title-icon">
                      <FileText :size="18" :stroke-width="2.5" />
                    </div>
                    <span>{{ $t('diagnosis.docs_drawer_title') }}</span>
                  </div>
                  <p class="diag-panel-subtitle">{{ $t('diagnosis.docs_upload_hint') }}</p>
                </div>
                <div class="diag-panel-actions">
                  <input
                    id="diag-panel-file"
                    type="file"
                    class="diag-hidden-input"
                    multiple
                    accept=".md,.markdown,.txt,.log,.json,.csv,.pdf,.doc,.docx"
                    @change="handleDiagnosisDocSelect"
                  />
                  <label for="diag-panel-file" class="btn-ghost diag-upload-btn" :class="{ disabled: diagDocs.uploading }">
                    <Loader2 v-if="diagDocs.uploading" class="w-4 h-4 diag-spin" />
                    <Upload v-else class="w-4 h-4" />
                    <span>{{ $t('diagnosis.upload_docs') }}</span>
                  </label>
                </div>
              </header>

              <div class="diag-body">
                <aside class="diag-doc-list-pane">
                  <div v-if="diagDocs.docsLoading" class="diag-state">
                    <Loader2 class="w-4 h-4 diag-spin" />
                    <span>{{ $t('common.loading') }}</span>
                  </div>
                  <div v-else-if="diagDocs.docs.length === 0" class="diag-state">{{ $t('diagnosis.docs_empty') }}</div>
                  <div v-else class="diag-doc-list">
                    <button
                      v-for="doc in diagDocs.docs"
                      :key="doc.id"
                      type="button"
                      class="diag-doc-item"
                      :class="{ active: diagDocs.activeDoc?.id === doc.id }"
                      @click="diagDocs.selectDoc(doc)"
                    >
                      <div class="diag-doc-icon-container blue">
                        <FileText :size="14" :stroke-width="2.5" />
                      </div>
                      <div class="diag-doc-body">
                        <span class="diag-doc-name">{{ doc.name.split('/').pop() }}</span>
                        <span class="diag-doc-meta">{{ diagDocMeta(doc) }}</span>
                      </div>
                    </button>
                  </div>
                </aside>

                <section class="diag-doc-preview-pane">
                  <div v-if="diagDocs.activeDocLoading" class="diag-state diag-preview-state">
                    <Loader2 class="w-4 h-4 diag-spin" />
                    <span>{{ $t('common.loading') }}</span>
                  </div>
                  <div v-else-if="diagDocs.activeDoc" class="diag-doc-preview">
                    <div class="diag-preview-title">
                      <div class="diag-doc-icon-container blue">
                        <FileText :size="14" :stroke-width="2.5" />
                      </div>
                      <span>{{ diagDocs.activeDoc.name.split('/').pop() }}</span>
                    </div>
                    <pre v-if="diagDocs.activeDoc.content_text" class="diag-preview-content">{{ diagDocs.activeDoc.content_text }}</pre>
                    <div v-else class="diag-state diag-preview-state">{{ $t('diagnosis.docs_preview_empty') }}</div>
                  </div>
                  <div v-else class="diag-state diag-preview-state">
                    <FileText class="w-10 h-10 opacity-10" />
                    <span>{{ $t('diagnosis.docs_empty') }}</span>
                  </div>
                </section>
              </div>
            </div>
          </div>

          <!-- 问题定位：代码路径面板 -->
          <div
            v-if="vm.isDiagnosisTask"
            class="spec-tab-panel"
            v-show="vm.specDrawerTab === 'diag_code'"
          >
            <div class="diag-panel">
              <header class="diag-panel-header">
                <div class="diag-panel-title-group">
                  <div class="diag-panel-title-line">
                    <div class="diag-panel-title-icon amber">
                      <GitFork :size="18" :stroke-width="2.5" />
                    </div>
                    <span>{{ $t('diagnosis.code_path_tab') }}</span>
                  </div>
                  <p class="diag-panel-subtitle">{{ $t('diagnosis.code_path_label') }}</p>
                </div>
              </header>

              <div class="diag-body diag-body-stack">
                <section class="diag-section">
                  <h4 class="diag-section-label">{{ $t('diagnosis.code_path_label') }}</h4>
                  <pre v-if="diagDocs.codePath" class="diag-code-path">{{ diagDocs.codePath }}</pre>
                  <div v-else-if="diagDocs.reposLoading" class="diag-state">
                    <Loader2 class="w-4 h-4 diag-spin" />
                    <span>{{ $t('common.loading') }}</span>
                  </div>
                  <div v-else class="diag-state">{{ $t('diagnosis.code_path_empty') }}</div>
                </section>

                <section class="diag-section">
                  <h4 class="diag-section-label">{{ $t('diagnosis.repo_list_label') }}</h4>
                  <div v-if="diagDocs.reposLoading" class="diag-state">
                    <Loader2 class="w-4 h-4 diag-spin" />
                    <span>{{ $t('common.loading') }}</span>
                  </div>
                  <div v-else-if="diagDocs.repos.length === 0" class="diag-state">{{ $t('diagnosis.repo_list_empty') }}</div>
                  <div v-else class="diag-repo-list">
                    <div v-for="repo in diagDocs.repos" :key="repo.id || repo.repo_name" class="diag-repo-item">
                      <div class="diag-doc-icon-container blue">
                        <GitFork :size="14" :stroke-width="2.5" />
                      </div>
                      <div class="diag-repo-body">
                        <div class="diag-repo-name">
                          {{ repo.repo_name }}
                          <span v-if="repo.state" class="diag-repo-state">{{ repo.state }}</span>
                        </div>
                        <div class="diag-repo-meta">
                          {{ [repo.branch_name, repo.repo_url].filter(Boolean).join(' · ') }}
                        </div>
                      </div>
                    </div>
                  </div>
                </section>
              </div>
            </div>
          </div>

          <!-- 研发态：需求文档 -->
          <div
            v-if="!vm.isDiagnosisTask && vm.currentTaskHasSpec"
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
          <!-- 研发态：计划文档 -->
          <div
            v-if="!vm.isDiagnosisTask"
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

    <!-- ─── Modals and Drawers ─── -->
    <TaskProvisionProgressModal
      :show="vm.taskProvisionVisible"
      :job-id="vm.taskProvisionJobId"
      :task-id="vm.taskProvisionTaskId"
      :workspace-id="String(vm.route.params.wsId || '')"
      @close="vm.closeTaskProvision"
      @open-session="vm.openTaskSession(vm.taskProvisionTaskId)"
    />

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

/* ─── 问题定位：诊断文档 / 代码路径面板（spec 抽屉三段式容器内） ─── */
.diag-panel {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.4);
  backdrop-filter: var(--glass-blur);
  border: 1px solid rgba(14, 165, 233, 0.1);
  border-radius: var(--radius-xl);
  overflow: hidden;
  box-shadow: var(--shadow-lg);
}

.diag-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(14, 165, 233, 0.08);
  background: rgba(255, 255, 255, 0.6);
  flex-shrink: 0;
}

.diag-panel-title-group {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.diag-panel-title-line {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--color-text-title);
  font-family: var(--font-heading);
  font-size: 1.0625rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.diag-panel-title-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}

.diag-panel-title-icon.amber {
  background: #fffbeb;
  color: #d97706;
}

.diag-panel-subtitle {
  margin: 2px 0 0 42px;
  font-size: 0.72rem;
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diag-panel-actions {
  flex-shrink: 0;
}

.diag-hidden-input {
  display: none;
}

.diag-upload-btn {
  cursor: pointer;
  font-size: 0.78rem;
}

.diag-state {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 4px;
  color: var(--color-text-muted);
  font-size: 0.8rem;
}

.diag-body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

.diag-body-stack {
  flex-direction: column;
  overflow-y: auto;
  padding: 18px 20px;
  gap: 18px;
}

.diag-doc-list-pane {
  width: 280px;
  min-width: 230px;
  border-right: 1px solid rgba(14, 165, 233, 0.08);
  overflow-y: auto;
  padding: 12px;
  background: rgba(255, 255, 255, 0.25);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.diag-doc-preview-pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px 18px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.25);
}

.diag-preview-state {
  flex: 1;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
}

.diag-doc-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.diag-doc-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  width: 100%;
  transition: all var(--transition-fast);
}

.diag-doc-item:hover {
  border-color: rgba(14, 165, 233, 0.45);
  background: var(--color-primary-50);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.diag-doc-item.active {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.diag-doc-icon-container {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  flex-shrink: 0;
}

.diag-doc-icon-container.blue {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}

.diag-doc-icon-container.amber {
  background: #fffbeb;
  color: #d97706;
}

.diag-doc-body {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.diag-doc-name {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-title);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diag-doc-meta {
  font-size: 0.68rem;
  color: var(--color-text-muted);
}

.diag-doc-preview {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: var(--radius-lg);
  background: #ffffff;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.diag-preview-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--color-text-title);
  background: rgba(255, 255, 255, 0.6);
}

.diag-preview-content {
  flex: 1;
  margin: 0;
  padding: 14px 16px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  line-height: 1.65;
  color: var(--color-text-body);
}

.diag-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.diag-section-label {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.diag-code-path {
  margin: 0;
  padding: 12px 14px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: var(--radius-lg);
  background: #ffffff;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--color-text-body);
  overflow: auto;
  word-break: break-all;
  box-shadow: var(--shadow-sm);
}

.diag-repo-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.diag-repo-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  background: #ffffff;
  box-shadow: var(--shadow-sm);
}

.diag-repo-body {
  min-width: 0;
  flex: 1;
}

.diag-repo-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-title);
}

.diag-repo-state {
  padding: 0 6px;
  border-radius: 999px;
  font-size: 0.62rem;
  font-weight: 700;
  color: var(--color-text-muted);
  background: var(--color-bg-base);
}

.diag-repo-meta {
  margin-top: 2px;
  font-size: 0.68rem;
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diag-spin {
  animation: diag-spin 1s linear infinite;
}

@keyframes diag-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
