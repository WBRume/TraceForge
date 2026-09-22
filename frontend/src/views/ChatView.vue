<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { proxyRefs } from 'vue'
import { ChevronDown, Loader2 } from 'lucide-vue-next'
import NewTaskModal from '@/components/task-create/NewTaskModal.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import ChatExecutionInput from '@/components/chat/ChatExecutionInput.vue'
import PreInputPanel from '@/components/chat/PreInputPanel.vue'
import ChatCliWorkbench from '@/components/chat/terminal/ChatCliWorkbench.vue'
import ApplyPatchDrawer from '@/components/local-agent/ApplyPatchDrawer.vue'
import TaskCloseoutPanel from '@/components/chat/task-closeout/TaskCloseoutPanel.vue'
import TaskSessionShareDialog from '@/components/chat/TaskSessionShareDialog.vue'
import ShareSuggestionPanel from '@/components/chat/ShareSuggestionPanel.vue'
import TaskSkillsDrawer from '@/components/chat/TaskSkillsDrawer.vue'
import ContextWindowDrawer from '@/components/chat/context-window/ContextWindowDrawer.vue'
import TaskSidebar from '@/components/chat/sections/TaskSidebar.vue'
import SessionHeader from '@/components/chat/sections/SessionHeader.vue'
import SpecBootstrapTip from '@/components/chat/sections/SpecBootstrapTip.vue'
import PinnedCardsArea from '@/components/chat/sections/PinnedCardsArea.vue'
import ChatHistoryPanel from '@/components/chat/sections/ChatHistoryPanel.vue'
import VerificationActions from '@/components/chat/sections/VerificationActions.vue'
import InitializeTaskModal from '@/components/chat/sections/InitializeTaskModal.vue'
import StartTaskModal from '@/components/chat/sections/StartTaskModal.vue'
import SpecSidebar from '@/components/chat/sections/spec/SpecSidebar.vue'
import { useChatViewModel } from '@/composables/chat/useChatViewModel'
import { useShareFlows } from '@/composables/chat/share/useShareFlows'
import { useDiagnosisPlaybook } from '@/composables/chat/diagnosis/useDiagnosisPlaybook'
import DiagnosisSopLayout from '@/components/chat/diagnosis-playbook/DiagnosisSopLayout.vue'
import { useGuideSession } from '@/composables/chat/diagnosis/useGuideSession'

/**
 * 任务会话工作台（路由级组合面）：三栏布局装配 + 弹窗宿主。
 * 各区块的状态与编排分布在 components/chat/sections/* 与
 * composables/chat/* 域模块中；本组件只做装配、局部装配态（抽屉开关、
 * 撤销确认流）与跨区块事件桥接。
 */
const rawVm = useChatViewModel()
const vm = proxyRefs(rawVm)
const playbook = proxyRefs(useDiagnosisPlaybook({
  workspaceId: () => String(rawVm.route.params.wsId || ''),
  taskId: () => String(rawVm.currentTask.value?.id || ''),
  enabled: () => rawVm.currentTask.value?.task_type === 'DIAGNOSIS' && Boolean(rawVm.currentTask.value?.task_meta_json?.playbook_run_id),
  eligible: () => rawVm.currentTask.value?.task_type === 'DIAGNOSIS',
}))
const guideSession = proxyRefs(useGuideSession({
  workspaceId: () => String(rawVm.route.params.wsId || ''), taskId: () => String(rawVm.currentTask.value?.id || ''),
  enabled: () => Boolean(rawVm.currentTask.value?.task_meta_json?.diagnosis_playbook_guide),
  sessionGeneration: () => Number(rawVm.currentTask.value?.session_generation || 0),
}))
rawVm.registerPlaybookEvent((type, payload) => { playbook.onEvent(type, payload); guideSession.onEvent(type, payload) })
const sopEnabled = computed(() => Boolean(vm.currentTask?.task_meta_json?.diagnosis_playbook_guide || vm.currentTask?.task_meta_json?.playbook_run_id))
// SOP 三栏较挤，任务列表默认收起；用户选择持久化，跨任务与会话保持
const SOP_TASKLIST_KEY = 'sdd_sop_tasklist_expanded'
const showSopTasks = ref(localStorage.getItem(SOP_TASKLIST_KEY) === '1')
const toggleSopTasks = () => {
  showSopTasks.value = !showSopTasks.value
  localStorage.setItem(SOP_TASKLIST_KEY, showSopTasks.value ? '1' : '0')
}

// 快捷键 [ 切换任务列表；输入控件聚焦时不劫持按键
const handleGlobalKeydown = (event: KeyboardEvent) => {
  if (event.key !== '[' || !sopEnabled.value) return
  const target = event.target as HTMLElement | null
  if (target?.closest('input, textarea, select, [contenteditable="true"]')) return
  event.preventDefault()
  toggleSopTasks()
}
onMounted(() => window.addEventListener('keydown', handleGlobalKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleGlobalKeydown))
const investigate = (text: string) => {
  if (vm.isChatLocked || vm.engineRunning) return
  if (vm.chatInput?.trim()) { vm.chatInput += '\n\n' + text; return }
  vm.chatInput = text
  void vm.sendChat()
}

// ── 视图装配态 ──
const showApplyPatchDrawer = ref(false)
const preInputMode = ref(false)
const chatInputRef = ref<any>(null)

// ── 任务会话分享：弹窗 + 待采纳输入面板 ──
const {
  sessionShares,
  shareSuggestions,
  showShareDialog,
  justCreatedShare,
  suggestionPanelOpen,
  adoptingSuggestion,
  openShareDialog,
  handleCreateShare,
  handleRevokeShare,
  closeShareDialog,
  handleAdoptSuggestion,
  confirmAdoptAppend,
  confirmAdoptReplace,
  cancelAdoptChoice,
  handleEditSuggestion,
  handleDismissSuggestion,
} = useShareFlows({
  getWorkspaceId: () => String(rawVm.route.params.wsId || ''),
  getTaskId: () => String(rawVm.currentTask.value?.id || ''),
  getChatDraft: () => String(rawVm.chatInput.value || ''),
  setChatDraft: (content) => { rawVm.chatInput.value = content },
})

// 分享建议 WS nudge → 建议域刷新（事件驱动，替代定时轮询）
rawVm.registerShareSuggestionNudge(() => {
  shareSuggestions.handleSuggestionNudge()
})

// ── 撤销确认流：先确认，再交给消息动作域执行 ──
const pendingUndoMessage = ref<Record<string, any> | null>(null)

const handleUndoRequest = (message: Record<string, any>) => {
  if (rawVm.isUndoing.value || !rawVm.canUndoMessage(message)) return
  pendingUndoMessage.value = message
}

const cancelUndoConfirmation = () => {
  if (rawVm.isUndoing.value) return
  pendingUndoMessage.value = null
}

const confirmUndoMessage = async () => {
  const message = pendingUndoMessage.value
  if (!message || rawVm.isUndoing.value) return
  // Close the confirmation layer before the async provider/worktree restore starts.
  // The chat-main busy overlay then becomes visible immediately.
  pendingUndoMessage.value = null
  try {
    await rawVm.undoMessage(message)
  } catch {
    // undoMessage owns user-facing error handling; keep this callback rejection-free.
  }
}

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

// 切换任务会话时退出协作预输入模式，并撤销中的确认层
watch(
  () => vm.currentTask?.id,
  () => {
    preInputMode.value = false
    pendingUndoMessage.value = null
  },
)
</script>
<template>
  <div class="chat-layout">
    <!-- Left Sidebar: Task List（SOP 模式下可折叠，宽位动画由 .is-collapsed 驱动） -->
    <TaskSidebar
      :class="{ 'is-collapsed': sopEnabled && !showSopTasks }"
      :aria-hidden="sopEnabled && !showSopTasks ? 'true' : undefined"
      :vm="vm"
      :list-container-ref="rawVm.taskListContainer"
    />

    <!-- Center: Chat + Pinned Cards -->
    <section
      class="chat-main"
      :class="{ 'is-session-busy': vm.isUndoing }"
      :aria-busy="vm.isUndoing"
      v-if="vm.currentTask"
    >
      <SessionHeader
        :vm="vm"
        :show-tasklist-toggle="sopEnabled"
        :tasklist-visible="showSopTasks"
        @toggle-tasklist="toggleSopTasks"
        @share="openShareDialog"
        @open-apply-patch="showApplyPatchDrawer = true"
      />

      <div
        v-if="vm.isUndoing"
        class="session-operation-overlay"
        role="status"
        aria-live="polite"
        aria-busy="true"
      >
        <div class="session-operation-card">
          <svg class="session-operation-progress-ring" viewBox="0 0 48 48" aria-hidden="true">
            <circle class="session-operation-progress-track" cx="24" cy="24" r="18" pathLength="100" />
            <circle class="session-operation-progress-path" cx="24" cy="24" r="18" pathLength="100" />
          </svg>
          <span class="session-operation-copy">{{ $t('chat.undo.in_progress') }}</span>
        </div>
      </div>

      <SpecBootstrapTip :vm="vm" />

      <template v-if="vm.chatWorkbenchMode === 'platform'">
      <DiagnosisSopLayout :enabled="sopEnabled" :guide="guideSession.state" :run="playbook.run as any"
        :busy="guideSession.busy || playbook.busy || vm.isChatLocked" :running="vm.engineRunning" :error="guideSession.error || playbook.error"
        :tail="playbook.tail" :can-continue="playbook.canContinue" :agent-text="playbook.agentText"
        @guide-command="guideSession.command" @command="playbook.command" @investigate="investigate"
        @retry="() => { guideSession.reload(); playbook.reload() }">
      <!-- ─ 置顶富文本卡片区（独立，不随对话滚动） ─ -->
      <PinnedCardsArea
        :show-thinking="vm.showThinking"
        :thinking-content="vm.thinkingContent"
        :thinking-expanded="vm.thinkingExpanded"
        :engine-running="vm.engineRunning"
        :hitl-cards="vm.activeHitlCards"
        @update:thinking-expanded="vm.thinkingExpanded = $event"
        @submit-hitl="vm.submitHitl"
      />

      <!-- ─ 对话气泡区（仅自然语言） ─ -->
      <ChatHistoryPanel
        :vm="vm"
        :container-ref="rawVm.chatContainer"
        @undo-request="handleUndoRequest"
      />

      <!-- 快捷操作行 -->
      <VerificationActions :vm="vm" />

      <!-- 协作预输入：收集窗口进行中时显示在输入框上方 -->
      <PreInputPanel
        v-if="vm.activePreInput && vm.preInputIsCollecting"
        :vm="vm"
      />

      <!-- 分享邀请输入：发起人收到的待采纳输入（入口 + 面板） -->
      <template v-if="vm.currentTask && vm.canShareTaskSession && shareSuggestions.pendingCount.value > 0">
        <button
          v-if="!suggestionPanelOpen"
          type="button"
          class="btn-micro suggestion-entry-btn"
          @click="suggestionPanelOpen = true"
        >
          <span class="suggestion-entry-dot"></span>
          {{ $t('share.suggestions_entry', { count: shareSuggestions.pendingCount.value }) }}
          <ChevronDown class="w-3 h-3" />
        </button>
        <ShareSuggestionPanel
          v-else
          :suggestions="shareSuggestions.suggestions.value"
          :pending-count="shareSuggestions.pendingCount.value"
          :loading="shareSuggestions.loading.value"
          :acting-ids="shareSuggestions.actingIds.value"
          :has-draft="Boolean(vm.chatInput && vm.chatInput.trim())"
          @close="suggestionPanelOpen = false"
          @edit="handleEditSuggestion"
          @copy="shareSuggestions.copySuggestion"
          @adopt="handleAdoptSuggestion"
          @dismiss="handleDismissSuggestion"
        />
      </template>

      <!-- Input Area：统一输入卡（普通发送 / 协作预输入模式丝滑切换）
           收集窗口进行中只保留协作编辑框，普通输入框不再显示 -->
      <ChatExecutionInput
        v-if="!vm.preInputIsCollecting"
        ref="chatInputRef"
        v-model="vm.chatInput"
        v-model:pre-input-mode="preInputMode"
        :disabled="vm.isChatLocked || vm.sendingChat || Boolean(playbook.run && !['COMPLETED', 'CANCELLED'].includes(playbook.run.state))"
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
      </DiagnosisSopLayout>
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

    <!-- Right: Spec / Diagnosis Drawer -->
    <SpecSidebar v-if="!sopEnabled" :vm="vm" />

    <!-- ─── Modals and Drawers ─── -->
    <!-- 任务准备进度由全局浮窗 ProvisionFloatingWidget（App.vue 挂载）负责 -->

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

    <!-- 任务会话分享弹窗 -->
    <TaskSessionShareDialog
      :show="showShareDialog"
      :task-id="String(vm.currentTask?.id || '')"
      :task-name="vm.currentTask?.name || ''"
      :shares="sessionShares.shares.value"
      :loading="sessionShares.sharesLoading.value"
      :creating="sessionShares.creating.value"
      :revoking-ids="sessionShares.revokingIds.value"
      :can-share="vm.canShareTaskSession"
      :just-created="justCreatedShare"
      @close="closeShareDialog"
      @create="handleCreateShare"
      @revoke="handleRevokeShare"
    />

    <!-- 采纳输入：已有草稿时选择追加或替换（取消不改变建议状态） -->
    <ConfirmActionModal
      :show="Boolean(adoptingSuggestion)"
      :title="$t('share.adopt_choice_title')"
      :message="$t('share.adopt_choice_message')"
      :description="$t('share.adopt_choice_description')"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('share.adopt_choice_append')"
      tone="primary"
      @cancel="cancelAdoptChoice"
      @confirm="confirmAdoptAppend"
    >
      <template #content>
        <div class="modal-actions" style="margin-top: 12px;">
          <button class="btn-secondary" @click="confirmAdoptReplace">
            {{ $t('share.adopt_choice_replace') }}
          </button>
        </div>
      </template>
    </ConfirmActionModal>

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

    <StartTaskModal :vm="vm" />

    <InitializeTaskModal :vm="vm" />

    <ConfirmActionModal
      :show="Boolean(pendingUndoMessage)"
      :title="$t('chat.undo.confirm_title')"
      :message="$t('chat.undo.confirm_message')"
      :description="$t('chat.undo.confirm_description')"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('chat.undo.confirm_action')"
      tone="danger"
      :loading="vm.isUndoing"
      @cancel="cancelUndoConfirmation"
      @confirm="confirmUndoMessage"
    />

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
      @refresh-skills="vm.loadTaskRuntimeSkills({ force: true, hydrateEditor: vm.showTaskSkillsDrawer })"
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
