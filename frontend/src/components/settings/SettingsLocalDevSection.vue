<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { CheckCircle2, FolderOpen, GitBranch, Save, Unlink, ChevronRight, XCircle, Info } from 'lucide-vue-next'
import { useWorkspaceStore } from '@/stores/workspace'
import { useLocalAgentStore } from '@/stores/localAgent'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import { remoteUrlsMatch } from '@/composables/local-agent/localAgentUtils'

const wsStore = useWorkspaceStore()
const localAgent = useLocalAgentStore()
const { t } = useI18n()
const {
  electronAvailable,
  repoPath,
  repoRemoteUrl,
  repoStatus,
  repoMapping,
  workspaceId,
  expectedRemoteUrl,
} = storeToRefs(localAgent)

const modeLabel = computed(() => (
  electronAvailable.value
    ? t('settings.local_dev.mode_electron')
    : t('settings.local_dev.mode_web')
))
const canUseLocalFeatures = computed(() => electronAvailable.value && Boolean(expectedRemoteUrl.value))
const canRemoveRepoMapping = computed(() => electronAvailable.value && Boolean(repoMapping.value?.localPath))
const showRemoveRepoConfirm = ref(false)
const removingRepo = ref(false)
const validatingRepo = shallowRef(false)

const isSuccessStatus = computed(() => {
  return repoStatus.value?.startsWith('Clean')
})

const isErrorStatus = computed(() => {
  return repoStatus.value && !repoStatus.value.startsWith('Clean')
})

const hydrate = async () => {
  await localAgent.loadLocalConfig()
  await localAgent.syncCurrentAuthToConfig()
  await localAgent.setWorkspaceContext(wsStore.currentWorkspace)
}

const saveRepo = async () => {
  await localAgent.saveRepoMapping(null)
}

const validateRepoWithFeedback = async () => {
  if (!repoPath.value) {
    ElMessage.warning(t('settings.local_dev.validate_select_repo_first'))
    return
  }
  validatingRepo.value = true
  try {
    await localAgent.validateRepo()
    if (!repoRemoteUrl.value) {
      ElMessage.error(repoStatus.value || t('settings.local_dev.validate_not_git'))
      return
    }
    if (!repoStatus.value.startsWith('Clean')) {
      ElMessage.warning(t('settings.local_dev.validate_dirty'))
      return
    }
    if (expectedRemoteUrl.value && !remoteUrlsMatch(repoRemoteUrl.value, expectedRemoteUrl.value)) {
      ElMessage.error(t('settings.local_dev.validate_remote_mismatch'))
      return
    }
    ElMessage.success(t('settings.local_dev.validate_success'))
  } catch {
    ElMessage.error(t('settings.local_dev.validate_failed'))
  } finally {
    validatingRepo.value = false
  }
}

const removeRepo = async () => {
  showRemoveRepoConfirm.value = true
}

const closeRemoveRepoConfirm = () => {
  if (removingRepo.value) return
  showRemoveRepoConfirm.value = false
}

const confirmRemoveRepo = async () => {
  removingRepo.value = true
  try {
    const desktop = localAgent.desktop
    if (!desktop?.config?.removeRepoMapping || !workspaceId.value || !expectedRemoteUrl.value) {
      ElMessage.error(t('settings.local_dev.remove_unavailable'))
      return
    }
    await desktop.config.removeRepoMapping({
      workspaceId: workspaceId.value,
      remoteUrl: expectedRemoteUrl.value,
    })
    await localAgent.loadRepoMapping()
    ElMessage.success(t('settings.local_dev.remove_success'))
    await hydrate()
    showRemoveRepoConfirm.value = false
  } finally {
    removingRepo.value = false
  }
}

watch(
  () => [wsStore.currentWorkspace?.id, wsStore.currentWorkspace?.git_repo_url],
  () => {
    void hydrate()
  },
  { immediate: true },
)
</script>

<template>
  <div class="local-dev-settings">
    <!-- Only Repo Mapping Area is kept -->
    <section class="settings-card glass-panel animate-pop-in">
      <div class="section-title-row">
        <div class="flex items-start gap-4">
          <div class="icon-wrapper">
             <GitBranch class="w-6 h-6" />
          </div>
          <div>
            <h2 class="title-gradient-small">{{ t('settings.local_dev.repo_mapping_title') }}</h2>
            <p class="subtitle">{{ t('settings.local_dev.repo_mapping_desc') }}</p>
          </div>
        </div>
        <!-- Status badge moved here since environment card is gone -->
        <span class="mode-pill" :class="{ active: electronAvailable }">{{ modeLabel }}</span>
      </div>

      <div v-if="!expectedRemoteUrl" class="warning-box mt-4">
        <Info class="w-4 h-4 flex-shrink-0" />
        <span>{{ t('settings.local_dev.no_workspace_remote') }}</span>
      </div>

      <div v-else-if="canUseLocalFeatures" class="interaction-area mt-6">
        
        <!-- Step 1: Selection Prompt -->
        <div v-if="!repoPath" class="selection-prompt" @click="localAgent.chooseRepo">
          <div class="prompt-icon pulse-animation">
            <FolderOpen class="w-10 h-10" />
          </div>
          <h3 class="mt-4 font-bold text-lg text-primary-900">{{ t('settings.local_dev.choose_repo') }}</h3>
          <p class="text-sm text-muted mt-2 text-center max-w-sm">{{ t('settings.local_dev.choose_repo_hint') }}</p>
          
          <div class="interactive-tip mt-6">
            <Info class="w-4 h-4" />
            <span>{{ t('settings.local_dev.choose_repo_tip') }}</span>
          </div>
        </div>

        <!-- Step 2: Selected Details & Status -->
        <div v-else class="repo-details">
          <div class="detail-card">
            <div class="field-row">
              <span class="field-label">{{ t('settings.local_dev.expected_remote') }}</span>
              <span class="field-value badge-light truncate" :title="expectedRemoteUrl || ''">{{ expectedRemoteUrl }}</span>
            </div>
            
            <div class="connector flex justify-center py-2 text-slate-300">
              <ChevronRight class="w-5 h-5 rotate-90" />
            </div>

            <div class="field-row">
              <span class="field-label">{{ t('settings.local_dev.local_path') }}</span>
              <div class="field-value-group">
                <span class="field-value badge-primary flex-1 truncate" :title="repoPath">{{ repoPath }}</span>
                <button class="btn-icon" @click="localAgent.chooseRepo" :title="t('settings.local_dev.choose_repo')">
                  <FolderOpen class="w-4 h-4" />
                </button>
              </div>
            </div>

            <div v-if="repoRemoteUrl" class="field-row mt-3 border-t border-slate-100 pt-3">
              <span class="field-label">{{ t('settings.local_dev.detected_remote') }}</span>
              <span class="field-value badge-light truncate" :title="repoRemoteUrl">{{ repoRemoteUrl }}</span>
            </div>
          </div>

          <!-- Status Message -->
          <div v-if="repoStatus" class="status-banner" :class="{ 'status-success': isSuccessStatus, 'status-error': isErrorStatus, 'status-info': !isSuccessStatus && !isErrorStatus }">
            <CheckCircle2 v-if="isSuccessStatus" class="w-5 h-5 flex-shrink-0" />
            <XCircle v-else-if="isErrorStatus" class="w-5 h-5 flex-shrink-0" />
            <Info v-else class="w-5 h-5 flex-shrink-0" />
            <span class="font-medium break-all">{{ repoStatus }}</span>
          </div>

          <!-- Actions Footer -->
          <div class="dialog-actions mt-6">
            <button class="btn-secondary danger action-button" type="button" :disabled="!canRemoveRepoMapping" @click="removeRepo">
              <Unlink class="w-4 h-4" />
              {{ t('settings.local_dev.remove_mapping') }}
            </button>
            <div class="flex gap-3">
              <el-tooltip :content="t('settings.local_dev.validate_tooltip')" placement="top">
                <span class="tooltip-button-wrap">
                  <button
                    class="btn-secondary action-button"
                    type="button"
                    :disabled="!canUseLocalFeatures || validatingRepo"
                    @click="validateRepoWithFeedback"
                  >
                    <CheckCircle2 class="w-4 h-4" />
                    {{ validatingRepo ? t('settings.local_dev.validating_repo') : t('settings.local_dev.validate_repo') }}
                  </button>
                </span>
              </el-tooltip>
              <button class="btn-primary action-button" type="button" :disabled="!canUseLocalFeatures" @click="saveRepo">
                <Save class="w-4 h-4" />
                {{ t('settings.local_dev.save_mapping') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <ConfirmActionModal
      :show="showRemoveRepoConfirm"
      :title="t('settings.local_dev.remove_confirm_title')"
      :message="t('settings.local_dev.remove_confirm_message')"
      :description="t('settings.local_dev.remove_confirm_description')"
      :emphasis-label="t('settings.local_dev.current_local_path')"
      :emphasis-value="repoPath || t('settings.local_dev.repo_not_selected')"
      :cancel-text="t('settings.local_dev.keep_mapping')"
      :confirm-text="t('settings.local_dev.remove_mapping')"
      tone="danger"
      :loading="removingRepo"
      @cancel="closeRemoveRepoConfirm"
      @confirm="confirmRemoveRepo"
    />
  </div>
</template>

<style scoped>
/* Base Overlay & Card */
.local-dev-settings {
  display: flex;
  flex-direction: column;
  padding-bottom: 2rem;
}

.settings-card {
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 16px;
  padding: 1.75rem;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(12px);
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.05), inset 0 1px 0 rgba(255, 255, 255, 0.6);
  transition: all 0.3s ease;
}

.settings-card:hover {
  box-shadow: 0 8px 30px rgba(15, 23, 42, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.8);
}

/* Typography & Layout Utilities */
.title-gradient-small {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 800;
  background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  color: #64748b;
  font-size: 0.9rem;
  margin-top: 0.4rem;
  line-height: 1.5;
}

/* Header */
.section-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.icon-wrapper {
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.1), rgba(59, 130, 246, 0.1));
  padding: 0.65rem;
  border-radius: 12px;
  color: #0ea5e9;
  border: 1px solid rgba(14, 165, 233, 0.2);
}

/* Mode Pill */
.mode-pill {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  padding: 0.35rem 0.75rem;
  color: #64748b;
  font-size: 0.8rem;
  font-weight: 700;
  white-space: nowrap;
  background: #f8fafc;
}

.mode-pill.active {
  border-color: rgba(16, 185, 129, 0.4);
  color: #047857;
  background: #ecfdf5;
}

/* Warnings */
.warning-box {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  background: #fff7ed;
  color: #9a3412;
  font-size: 0.875rem;
  font-weight: 500;
  line-height: 1.5;
}

/* Selection Prompt (State 1) */
.selection-prompt {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2.5rem 2rem;
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.6);
  cursor: pointer;
  transition: all 0.3s ease;
}

.selection-prompt:hover {
  border-color: #0ea5e9;
  background: #f0f9ff;
  transform: translateY(-2px);
  box-shadow: 0 10px 25px -5px rgba(14, 165, 233, 0.1);
}

.selection-prompt:hover .prompt-icon {
  color: #0ea5e9;
  transform: scale(1.05);
}

.prompt-icon {
  color: #94a3b8;
  transition: all 0.3s ease;
}

.interactive-tip {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: rgba(15, 23, 42, 0.04);
  border-radius: 20px;
  color: #64748b;
  font-size: 0.75rem;
}

/* Repo Details (State 2) */
.detail-card {
  background: rgba(248, 250, 252, 0.6);
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 1.25rem;
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.02);
}

.field-row {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.field-label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #64748b;
  width: 100px;
  flex-shrink: 0;
}

.field-value-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
  min-width: 0; /* for truncate */
}

.badge-light {
  background: #ffffff;
  color: #334155;
  padding: 0.4rem 0.6rem;
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.8rem;
  border: 1px solid #e2e8f0;
}

.badge-primary {
  background: #eff6ff;
  color: #1d4ed8;
  padding: 0.4rem 0.6rem;
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.8rem;
  border: 1px solid #bfdbfe;
}

.btn-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.4rem;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: #f8fafc;
  border-color: #0ea5e9;
  color: #0ea5e9;
}

/* Status Banner */
.status-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 1.25rem;
  padding: 1rem 1.25rem;
  border-radius: 8px;
  font-size: 0.875rem;
  animation: slideDown 0.3s ease-out;
}

.status-success {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #15803d;
}

.status-error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
}

.status-info {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
}

/* Footer Actions */
.dialog-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 1.5rem;
  margin-top: 1.5rem;
  border-top: 1px solid rgba(0,0,0,0.05);
}

.action-button {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.tooltip-button-wrap {
  display: inline-flex;
}

/* Buttons */
.btn-primary {
  background: linear-gradient(135deg, #0ea5e9, #3b82f6);
  color: white;
  border: none;
  padding: 0.6rem 1.25rem;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3);
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(14, 165, 233, 0.4);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

.btn-secondary {
  background: #ffffff;
  color: #334155;
  border: 1px solid #cbd5e1;
  padding: 0.6rem 1.25rem;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s;
}

.btn-secondary:hover:not(:disabled) {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}

.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary.danger {
  color: #ef4444;
  border-color: #fca5a5;
  background: #fef2f2;
}

.btn-secondary.danger:hover:not(:disabled) {
  background: #fee2e2;
  border-color: #f87171;
  color: #dc2626;
}

/* Common Text/Flex Utilities */
.text-muted { color: #64748b; }
.text-primary-900 { color: #0f172a; }
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mt-2 { margin-top: 0.5rem; }
.mt-3 { margin-top: 0.75rem; }
.mt-4 { margin-top: 1rem; }
.mt-6 { margin-top: 1.5rem; }
.py-2 { padding-top: 0.5rem; padding-bottom: 0.5rem; }
.pt-3 { padding-top: 0.75rem; }
.flex { display: flex; }
.items-start { align-items: flex-start; }
.items-center { align-items: center; }
.justify-center { justify-content: center; }
.justify-between { justify-content: space-between; }
.gap-3 { gap: 0.75rem; }
.gap-4 { gap: 1rem; }
.flex-1 { flex: 1; }
.font-medium { font-weight: 500; }
.font-bold { font-weight: 700; }
.text-sm { font-size: 0.875rem; }
.text-lg { font-size: 1.125rem; }
.max-w-sm { max-width: 24rem; }
.text-center { text-align: center; }
.flex-shrink-0 { flex-shrink: 0; }
.break-all { word-break: break-all; }

/* Animations */
@keyframes popIn {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-pop-in {
  animation: popIn 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}
</style>
