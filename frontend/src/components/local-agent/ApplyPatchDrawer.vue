<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { AlertTriangle, FileText, GitPullRequest, Loader2, RefreshCw, Settings, GitBranch, ArrowUpRight, Zap, Info, Copy } from 'lucide-vue-next'
import AppSideDrawer from '@/components/AppSideDrawer.vue'
import { applyProposalPatch, type ApplyPatchProgress } from '@/composables/local-agent/useLocalAgentApplyPatch'
import { useLocalAgentStore } from '@/stores/localAgent'
import type { AgentTask } from '@/types/agent'
import { formatApiError } from '@/utils/error'

const props = defineProps<{
  show: boolean
  task: Record<string, any> | null
  workspace: Record<string, any> | null
}>()

const emit = defineEmits<{
  close: []
}>()

const router = useRouter()
const { t } = useI18n()
const localAgent = useLocalAgentStore()
const {
  electronAvailable,
  proposal,
  proposalFiles,
  patchText,
  proposalLoading,
  proposalGenerating,
  patchLoading,
  repoMapping,
} = storeToRefs(localAgent)

const applyRunning = ref(false)
const applyEvents = ref<ApplyPatchProgress[]>([])
const generationAttempted = ref(false)
const generationError = ref('')
const drawerLevel = ref(1)
const selectedFilePath = ref<string | null>(null)

const agentTask = computed<AgentTask | null>(() => {
  if (!props.task?.id) return null
  return {
    id: String(props.task.id),
    workspace_id: String(props.task.workspace_id || props.workspace?.id || ''),
    creator_id: String(props.task.creator_id || ''),
    name: String(props.task.name || t('chat.change_apply_untitled_task')),
    description: props.task.description || null,
    git_repo_url: props.task.git_repo_url || props.workspace?.git_repo_url || null,
    status: String(props.task.status || ''),
    current_phase: props.task.current_phase || null,
    error_message: props.task.error_message || null,
    created_at: String(props.task.created_at || new Date().toISOString()),
    updated_at: props.task.updated_at || null,
    latest_change_proposal_id: props.task.latest_change_proposal_id || null,
  }
})

const workspaceId = computed(() => String(props.workspace?.id || agentTask.value?.workspace_id || ''))
const repoConfigured = computed(() => Boolean(repoMapping.value?.localPath))
const canApply = computed(() => (
  electronAvailable.value
  && Boolean(agentTask.value)
  && Boolean(proposal.value)
  && Boolean(patchText.value.trim())
  && repoConfigured.value
  && !applyRunning.value
  && !proposalGenerating.value
))

const proposalStatusText = computed(() => {
  if (proposalGenerating.value) return t('chat.change_apply_status_generating')
  if (proposalLoading.value) return t('chat.change_apply_status_loading')
  if (!proposal.value) return t('chat.change_apply_status_empty')
  return t('chat.change_apply_status_ready', {
    version: proposal.value.patch_set_no,
    status: proposal.value.status,
  })
})

const generateProposal = async () => {
  if (!agentTask.value || !workspaceId.value || proposalGenerating.value) return
  generationAttempted.value = true
  generationError.value = ''
  try {
    await localAgent.generateChangeProposal(agentTask.value, props.workspace)
    ElMessage.success(t('chat.change_apply_generate_success'))
  } catch (error) {
    const message = formatApiError(error, t('chat.change_apply_generate_failed'))
    generationError.value = message
    await localAgent.loadLatestProposal(agentTask.value)
    if (proposal.value) {
      ElMessage.warning(t('chat.change_apply_generate_fallback', { message }))
      return
    }
    ElMessage.error(message)
  }
}

const hydrate = async () => {
  if (!props.show) return
  applyEvents.value = []
  generationAttempted.value = false
  generationError.value = ''
  await localAgent.loadLocalConfig()
  if (agentTask.value) {
    // Load latest existing proposal if any, but don't auto-generate
    await localAgent.setTaskContext(agentTask.value, props.workspace, { loadLatest: true })
  }
}

const refreshProposal = async () => {
  if (!agentTask.value) return
  await generateProposal()
}

const goToLocalSettings = () => {
  if (workspaceId.value) {
    router.push(`/ws/${workspaceId.value}/settings`)
  }
  emit('close')
}

const handleApply = async () => {
  if (!localAgent.desktop || !agentTask.value || !proposal.value) return
  if (!repoMapping.value?.localPath) {
    ElMessage.warning(t('chat.change_apply_repo_missing_message'))
    return
  }

  await ElMessageBox.confirm(
    t('chat.change_apply_confirm_message', {
      taskId: agentTask.value.id,
      patchSetNo: proposal.value.patch_set_no,
    }),
    t('chat.change_apply_confirm_title'),
    {
      type: 'warning',
      confirmButtonText: t('chat.change_apply_confirm_button'),
      cancelButtonText: t('common.cancel'),
    },
  )

  applyRunning.value = true
  applyEvents.value = []
  try {
    const result = await applyProposalPatch({
      desktop: localAgent.desktop,
      task: agentTask.value,
      proposal: proposal.value,
      repoPath: repoMapping.value.localPath,
      patchText: patchText.value,
      onProgress: (event) => {
        applyEvents.value.push(event)
      },
    })
    await localAgent.loadLatestProposal()
    ElMessage[result.status === 'applied' ? 'success' : 'warning'](
      result.status === 'applied' ? t('chat.change_apply_applied_success') : t('chat.change_apply_conflict_uploaded'),
    )
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error)
    applyEvents.value.push({ step: 'error', detail: message, level: 'error' })
    ElMessage.error(message)
  } finally {
    applyRunning.value = false
  }
}

const displayPatch = computed(() => {
  if (!patchText.value) return ''
  
  // If a specific file is selected, extract its hunk
  if (selectedFilePath.value) {
    const escapedPath = selectedFilePath.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    // Regex to match from 'diff --git a/path' to the next 'diff --git' or end of string
    const regex = new RegExp(`diff --git a/${escapedPath} b/${escapedPath}[\\s\\S]*?(?=diff --git|$)`)
    const match = patchText.value.match(regex)
    return match ? match[0] : t('chat.change_apply_no_diff')
  }

  // If no file selected, show the whole thing but with truncation safety
  const lines = patchText.value.split('\n')
  const MAX_LINES = 3000
  if (lines.length > MAX_LINES) {
    return `${lines.slice(0, MAX_LINES).join('\n')}\n\n... ${t('chat.change_apply_truncated', { lines: lines.length })}`
  }
  
  return patchText.value
})

const highlightedLines = computed(() => {
  const text = displayPatch.value
  if (!text) return []
  
  return text.split('\n').map(line => {
    let type = 'plain'
    if (line.startsWith('+') && !line.startsWith('+++')) type = 'add'
    else if (line.startsWith('-') && !line.startsWith('---')) type = 'del'
    else if (line.startsWith('@@')) type = 'hunk'
    else if (line.startsWith('diff --git')) type = 'header'
    else if (line.startsWith('index ') || line.startsWith('new file mode ') || line.startsWith('deleted file mode ')) type = 'header'
    else if (line.startsWith('--- ') || line.startsWith('+++ ')) type = 'file'
    
    return { text: line || ' ', type }
  })
})

const formatApplyStep = (step: string) => {
  const stepLabels: Record<string, string> = {
    'validate-repo': t('chat.change_apply_step_validate_repo'),
    fetch: t('chat.change_apply_step_fetch'),
    'checkout-base': t('chat.change_apply_step_checkout_base'),
    pull: t('chat.change_apply_step_pull'),
    'create-branch': t('chat.change_apply_step_create_branch'),
    apply: t('chat.change_apply_step_apply'),
    done: t('chat.change_apply_step_done'),
    conflict: t('chat.change_apply_step_conflict'),
    error: t('common.error'),
  }
  return stepLabels[step] || step
}

const copyPatch = async () => {
  if (!patchText.value) return
  try {
    await navigator.clipboard.writeText(patchText.value)
    ElMessage.success(t('chat.change_apply_copy_success'))
  } catch (err) {
    ElMessage.error(t('chat.change_apply_copy_failed'))
  }
}

const handleFileClick = (path: string) => {
  if (selectedFilePath.value === path) {
    selectedFilePath.value = null // Toggle off
  } else {
    selectedFilePath.value = path
  }
}

watch(
  () => [props.show, props.task?.id],
  () => {
    if (props.show) {
      selectedFilePath.value = null
      void hydrate()
    }
  },
  { immediate: true },
)

// Auto-select the first file when proposal files are loaded
watch(
  () => proposalFiles.value,
  (newFiles) => {
    if (props.show && newFiles && newFiles.length > 0 && !selectedFilePath.value) {
      selectedFilePath.value = newFiles[0].file_path
    }
  }
)
</script>

<template>
  <AppSideDrawer
    :show="show"
    :title="$t('chat.change_apply_drawer_title')"
    v-model:level="drawerLevel"
    resizable
    hide-close
    @close="emit('close')"
  >
    <template #icon>
      <GitPullRequest class="w-4 h-4" />
    </template>
    <template #actions>
      <button class="btn-secondary drawer-action-button" type="button" :disabled="proposalGenerating || proposalLoading" @click="refreshProposal">
        <Loader2 v-if="proposalGenerating" class="w-4 h-4 spin" />
        <RefreshCw v-else class="w-4 h-4" />
        {{ proposalGenerating ? $t('chat.change_apply_syncing') : (proposal ? $t('chat.change_apply_resync') : $t('chat.change_apply_sync_now')) }}
      </button>
    </template>

    <section class="apply-patch-drawer">
      <!-- Top Bar: Task & Status Context -->
      <div class="drawer-top-bar glass-panel">
        <div class="task-context-brief">
          <div class="icon-container-sm blue">
            <Zap :size="12" :stroke-width="3" />
          </div>
          <div class="context-text">
            <span>{{ $t('chat.change_apply_current_task') }}</span>
            <strong>{{ task?.name || $t('chat.change_apply_untitled_task') }}</strong>
          </div>
        </div>
        
        <div class="proposal-status-brief">
          <div class="status-indicator" :class="{ loading: proposalGenerating || proposalLoading }">
             <div class="pulse-dot" v-if="proposalGenerating"></div>
             <strong>{{ proposalStatusText }}</strong>
          </div>
          <p v-if="proposal" class="base-info">
            <GitBranch :size="12" class="mr-1" />
            {{ $t('chat.change_apply_base_label') }}: {{ proposal.base_branch }} · <code class="sha">{{ proposal.base_commit_sha.slice(0, 7) }}</code>
          </p>
        </div>
      </div>

      <!-- Warning Boxes (Global) -->
      <div v-if="!electronAvailable" class="warning-box glass-panel error">
        <div class="icon-container amber">
          <AlertTriangle :size="16" :stroke-width="2.5" />
        </div>
        <span>{{ $t('chat.change_apply_web_disabled') }}</span>
      </div>

      <div v-else-if="!repoConfigured" class="warning-box repo-missing glass-panel amber">
        <div class="icon-container amber">
          <AlertTriangle :size="20" :stroke-width="2.5" />
        </div>
        <div class="warning-content">
          <strong>{{ $t('chat.change_apply_repo_missing_title') }}</strong>
          <p>{{ $t('chat.change_apply_repo_missing_desc') }}</p>
        </div>
        <button class="btn-primary drawer-action-button" type="button" @click="goToLocalSettings">
          <div class="icon-container-sm white-ghost">
            <Settings :size="14" :stroke-width="2.5" />
          </div>
          {{ $t('chat.change_apply_go_settings') }}
        </button>
      </div>

      <!-- Main Workspace: Split into Sidebar and Content -->
      <div v-if="proposal && !proposalGenerating && !proposalLoading" class="proposal-workspace">
        <aside class="proposal-sidebar">
          <!-- Meta Stats -->
          <div class="proposal-meta">
            <div class="meta-card glass-panel">
              <div class="meta-icon blue">
                <FileText :size="14" :stroke-width="2.5" />
              </div>
              <div class="meta-data">
                <span>{{ $t('chat.change_apply_files_label') }}</span>
                <strong>{{ proposal.changed_files_count }}</strong>
              </div>
            </div>
            <div class="meta-card glass-panel">
              <div class="meta-icon green">
                <ArrowUpRight :size="14" :stroke-width="2.5" />
              </div>
              <div class="meta-data">
                <span>{{ $t('chat.change_apply_insertions_label') }}</span>
                <strong class="text-green">+{{ proposal.insertions }}</strong>
              </div>
            </div>
            <div class="meta-card glass-panel">
              <div class="meta-icon red">
                <AlertTriangle :size="14" :stroke-width="2.5" />
              </div>
              <div class="meta-data">
                <span>{{ $t('chat.change_apply_deletions_label') }}</span>
                <strong class="text-red">-{{ proposal.deletions }}</strong>
              </div>
            </div>
          </div>

          <!-- File List -->
          <div class="file-list-container glass-panel">
            <div class="list-header">
              <FileText :size="12" />
              <span>{{ $t('chat.change_apply_changed_files') }}</span>
            </div>
            <div class="file-list-scroll custom-scrollbar">
              <div 
                v-for="file in proposalFiles" 
                :key="file.id" 
                class="file-row"
                :class="{ active: selectedFilePath === file.file_path }"
                @click="handleFileClick(file.file_path)"
              >
                <span class="file-path" :title="file.file_path">{{ file.file_path.split('/').pop() }}</span>
                <div class="file-stats-brief">
                  <span class="add">+{{ file.insertions }}</span>
                  <span class="del">-{{ file.deletions }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Notes -->
          <div v-if="proposal.summary || proposal.risk_notes" class="proposal-notes glass-panel">
            <div v-if="proposal.summary" class="note-item">
              <div class="note-label"><Info :size="10" /> <span>{{ $t('chat.change_apply_summary') }}</span></div>
              <p>{{ proposal.summary }}</p>
            </div>
            <div v-if="proposal.risk_notes" class="note-item risk">
              <div class="note-label"><AlertTriangle :size="10" /> <span>{{ $t('chat.change_apply_risk') }}</span></div>
              <p>{{ proposal.risk_notes }}</p>
            </div>
          </div>
        </aside>

        <!-- Main Content: Patch Preview -->
        <main class="patch-viewer glass-panel">
          <div class="viewer-header">
            <div class="header-left">
              <GitPullRequest :size="14" />
              <span>{{ $t('chat.change_apply_patch_preview') }}</span>
            </div>
            <div class="header-right">
              <button class="copy-patch-btn" :title="$t('chat.change_apply_copy_patch')" @click="copyPatch">
                <Copy :size="12" />
                <span>{{ $t('chat.change_apply_copy') }}</span>
              </button>
              <span class="branch-tag">{{ proposal.cloud_task_branch }}</span>
            </div>
          </div>
          <div class="patch-content-container custom-scrollbar">
            <div v-if="patchLoading" class="patch-loading-state">
              <Loader2 class="w-4 h-4 spin" />
              <span>{{ $t('chat.change_apply_patch_loading') }}</span>
            </div>
            <div v-else class="diff-lines">
              <div v-for="(line, idx) in highlightedLines" :key="idx" :class="['diff-line', line.type]">
                <span class="line-number">{{ idx + 1 }}</span>
                <span class="line-content">{{ line.text }}</span>
              </div>
            </div>
          </div>
        </main>
      </div>

      <!-- Queue/Loading/Empty States -->
      <div v-else class="drawer-centered-content">
        <div v-if="proposalGenerating" class="queue-state">
          <Loader2 class="w-5 h-5 spin" />
          <span>{{ $t('chat.change_apply_queue_hint') }}</span>
        </div>

        <div v-else-if="proposalLoading" class="loading-state">
          <Loader2 class="w-5 h-5 spin" />
          <span>{{ $t('chat.change_apply_loading_proposal') }}</span>
        </div>

        <div v-else-if="!proposal" class="empty-state">
          <div class="empty-icon-container">
             <GitPullRequest :size="32" :stroke-width="1.5" />
          </div>
          <strong>{{ generationAttempted ? $t('chat.change_apply_empty_after_attempt') : $t('chat.change_apply_empty_waiting') }}</strong>
          <p>{{ generationError || $t('chat.change_apply_empty_hint') }}</p>
        </div>
      </div>

      <!-- Events & Footer -->
      <div v-if="applyEvents.length" class="apply-events glass-panel">
        <div v-for="event in applyEvents" :key="`${event.step}-${event.detail}`" class="apply-event" :class="event.level || 'info'">
          <strong>{{ formatApplyStep(event.step) }}</strong>
          <span>{{ event.detail }}</span>
        </div>
      </div>

      <footer class="drawer-actions">
        <button class="btn-primary drawer-action-button" type="button" :disabled="!canApply" @click="handleApply">
          <Loader2 v-if="applyRunning" class="w-4 h-4 spin" />
          <GitPullRequest v-else class="w-4 h-4" />
          {{ applyRunning ? $t('chat.change_apply_running') : $t('chat.change_apply_apply_button') }}
        </button>
      </footer>
    </section>
  </AppSideDrawer>
</template>

<style scoped>
.apply-patch-drawer {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: rgba(248, 250, 252, 0.4);
  font-family: var(--font-body);
}

/* ─── Shared Components ─── */
.icon-container, .icon-container-sm {
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  flex-shrink: 0;
}

.icon-container { width: 32px; height: 32px; }
.icon-container-sm { width: 24px; height: 24px; border-radius: 6px; }

.icon-container.blue { background: rgba(14, 165, 233, 0.1); color: #0ea5e9; }
.icon-container.amber { background: rgba(245, 158, 11, 0.1); color: #f59e0b; }
.icon-container.green { background: rgba(16, 185, 129, 0.1); color: #10b981; }
.icon-container.red { background: rgba(244, 63, 94, 0.1); color: #f43f5e; }
.icon-container.purple { background: rgba(139, 92, 246, 0.1); color: #8b5cf6; }
.icon-container-sm.blue { background: rgba(14, 165, 233, 0.1); color: #0ea5e9; }
.icon-container-sm.amber { background: rgba(245, 158, 11, 0.1); color: #f59e0b; }
.icon-container-sm.white-ghost { background: rgba(255, 255, 255, 0.2); color: white; }

/* ─── Top Bar ─── */
.drawer-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  margin: 1.25rem 1.5rem 0;
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(14, 165, 233, 0.1);
  border-radius: 12px;
}

.task-context-brief {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.context-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.context-text span {
  font-size: 0.65rem;
  font-weight: 800;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.context-text strong {
  font-size: 0.875rem;
  font-weight: 700;
  color: var(--color-text-title);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.proposal-status-brief {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-indicator strong {
  font-size: 0.8125rem;
  color: var(--color-text-title);
}

.pulse-dot {
  width: 6px;
  height: 6px;
  background: var(--color-primary-500);
  border-radius: 50%;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { transform: scale(1); opacity: 1; }
  100% { transform: scale(2.5); opacity: 0; }
}

.base-info {
  margin: 2px 0 0;
  font-size: 0.7rem;
  color: var(--color-text-muted);
  display: flex;
  align-items: center;
}

.sha {
  font-family: var(--font-mono);
  background: rgba(148, 163, 184, 0.1);
  padding: 0 4px;
  border-radius: 3px;
  margin-left: 3px;
}

/* ─── Warnings ─── */
.warning-box {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0.875rem 1.25rem;
  margin: 1rem 1.5rem 0;
  border-radius: 12px;
  font-weight: 500;
  font-size: 0.8125rem;
}

.warning-box.error { background: rgba(244, 63, 94, 0.05); border: 1px solid rgba(244, 63, 94, 0.15); color: #b91c1c; }
.warning-box.amber { background: rgba(245, 158, 11, 0.05); border: 1px solid rgba(245, 158, 11, 0.15); color: #92400e; }

.warning-content { flex: 1; }
.warning-content p { margin: 2px 0 0; font-size: 0.75rem; opacity: 0.8; }

/* ─── Main Workspace ─── */
.proposal-workspace {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 1.25rem;
  padding: 1.25rem 1.5rem;
}

.proposal-sidebar {
  width: 280px;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  flex-shrink: 0;
}

.proposal-meta {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.meta-card {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #ffffff;
  border: 1px solid rgba(14, 165, 233, 0.08);
  border-radius: 10px;
}

.meta-icon {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.meta-icon.blue { background: rgba(14, 165, 233, 0.1); color: #0ea5e9; }
.meta-icon.green { background: rgba(16, 185, 129, 0.1); color: #10b981; }
.meta-icon.red { background: rgba(244, 63, 94, 0.1); color: #f43f5e; }
.meta-icon.purple { background: rgba(139, 92, 246, 0.1); color: #8b5cf6; }

.meta-data span {
  display: block;
  font-size: 0.6rem;
  font-weight: 800;
  color: var(--color-text-muted);
  text-transform: uppercase;
}

.meta-data strong {
  display: block;
  font-size: 0.9375rem;
  font-weight: 700;
  color: var(--color-text-title);
}

.file-list-container {
  flex: 1;
  min-height: 0;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgba(14, 165, 233, 0.08);
}

.list-header {
  padding: 10px 14px;
  background: rgba(248, 250, 252, 0.8);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.65rem;
  font-weight: 800;
  color: var(--color-text-muted);
  letter-spacing: 0.05em;
}

.file-list-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.file-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.03);
  transition: all 0.2s;
}

.file-row:hover {
  background: rgba(14, 165, 233, 0.04);
}

.file-row.active {
  background: rgba(14, 165, 233, 0.08);
  border-right: 3px solid #0ea5e9;
}

.file-path {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-text-body);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-stats-brief {
  display: flex;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 0.65rem;
  font-weight: 700;
}

.file-stats-brief .add { color: #059669; }
.file-stats-brief .del { color: #dc2626; }

.proposal-notes {
  padding: 12px;
  background: #ffffff;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  border: 1px solid rgba(14, 165, 233, 0.08);
}

.note-item { display: flex; flex-direction: column; gap: 4px; }
.note-label { display: flex; align-items: center; gap: 5px; font-size: 0.6rem; font-weight: 800; color: var(--color-text-muted); text-transform: uppercase; }
.note-item.risk .note-label { color: #b45309; }
.note-item p { margin: 0; font-size: 0.75rem; line-height: 1.5; color: var(--color-text-body); }

/* ─── Patch Viewer ─── */
.patch-viewer {
  flex: 1;
  min-width: 0;
  background: #0f172a;
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--shadow-lg);
}

.viewer-header {
  padding: 10px 18px;
  background: rgba(30, 41, 59, 0.8);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left { display: flex; align-items: center; gap: 10px; color: #94a3b8; font-size: 0.7rem; font-weight: 800; letter-spacing: 0.05em; }
.branch-tag { background: rgba(14, 165, 233, 0.15); color: #38bdf8; font-family: var(--font-mono); font-size: 0.65rem; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(56, 189, 248, 0.2); }

.patch-content-container {
  flex: 1;
  overflow: auto;
  background: #0f172a;
}

.patch-loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 2rem;
  color: #94a3b8;
  font-size: 0.875rem;
}

.diff-lines {
  padding: 1rem 0;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  line-height: 1.5;
  counter-reset: line;
}

.diff-line {
  display: flex;
  white-space: pre;
  min-width: fit-content;
}

.diff-line:hover {
  background: rgba(255, 255, 255, 0.03);
}

.line-number {
  width: 45px;
  padding: 0 10px;
  text-align: right;
  color: #475569;
  user-select: none;
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  margin-right: 12px;
  font-size: 0.7rem;
}

.line-content {
  flex: 1;
  padding-right: 1.5rem;
}

/* Diff Types */
.diff-line.add { background: rgba(16, 185, 129, 0.1); }
.diff-line.add .line-content { color: #10b981; }
.diff-line.add .line-number { color: rgba(16, 185, 129, 0.5); }

.diff-line.del { background: rgba(244, 63, 94, 0.1); }
.diff-line.del .line-content { color: #f43f5e; }
.diff-line.del .line-number { color: rgba(244, 63, 94, 0.5); }

.diff-line.hunk { background: rgba(14, 165, 233, 0.05); }
.diff-line.hunk .line-content { color: #7dd3fc; opacity: 0.8; font-weight: 600; }

.diff-line.header { font-weight: 700; color: #94a3b8; border-bottom: 1px solid rgba(255, 255, 255, 0.05); background: rgba(255, 255, 255, 0.02); }
.diff-line.file { font-weight: 700; color: #e2e8f0; }

.copy-patch-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  color: #94a3b8;
  font-size: 0.7rem;
  font-weight: 600;
  transition: all 0.2s;
  margin-right: 8px;
}

.copy-patch-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
  border-color: rgba(255, 255, 255, 0.2);
}

.copy-patch-btn:active {
  transform: scale(0.95);
}

/* ─── Empty States ─── */
.drawer-centered-content {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
}

.queue-state, .loading-state, .empty-state {
  max-width: 500px;
  text-align: center;
  padding: 3rem 2rem;
  background: #ffffff;
  border-radius: 20px;
  border: 1px dashed rgba(148, 163, 184, 0.2);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1.25rem;
  color: var(--color-text-muted);
}

.empty-icon-container {
  width: 64px;
  height: 64px;
  background: rgba(14, 165, 233, 0.05);
  color: #0ea5e9;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 0.5rem;
}

.empty-state strong { color: var(--color-text-title); font-size: 1.125rem; }
.empty-state p { font-size: 0.875rem; line-height: 1.6; }

/* ─── Events ─── */
.apply-events {
  margin: 0 1.5rem 1rem;
  padding: 1rem;
  background: #ffffff;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.apply-event { display: flex; gap: 10px; border-left: 3px solid #94a3b8; padding-left: 10px; font-size: 0.8125rem; }
.apply-event.success { border-left-color: #10b981; }
.apply-event.error { border-left-color: #f43f5e; }
.apply-event.warning { border-left-color: #f59e0b; }
.apply-event strong { min-width: 100px; }

/* ─── Footer ─── */
.drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 1.25rem 1.5rem;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(10px);
  border-top: 1px solid rgba(148, 163, 184, 0.15);
}

.drawer-action-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 32px;
  padding: 0 12px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.8125rem;
}

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1400px) {
  .proposal-sidebar { width: 240px; }
}

@media (max-width: 1024px) {
  .proposal-workspace { flex-direction: column; overflow-y: auto; }
  .proposal-sidebar { width: 100%; flex-direction: row; flex-wrap: wrap; }
  .meta-card { flex: 1; }
  .file-list-container { max-height: 200px; width: 100%; }
  .patch-viewer { min-height: 400px; }
}
</style>
