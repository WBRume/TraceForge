<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { CheckCircle2, FolderOpen, GitBranch, Info, Save, ChevronRight, XCircle } from 'lucide-vue-next'
import { useLocalAgentStore } from '@/stores/localAgent'
import { remoteUrlsMatch } from '@/composables/local-agent/localAgentUtils'

type WorkspaceLike = {
  id?: string
  name?: string | null
  git_repo_url?: string | null
}

const props = defineProps<{
  show: boolean
  workspace: WorkspaceLike | null
}>()

const emit = defineEmits<{
  close: []
  skip: []
  saved: []
}>()

const localAgent = useLocalAgentStore()
const { t } = useI18n()
const {
  electronAvailable,
  repoPath,
  repoRemoteUrl,
  repoStatus,
  repoMapping,
  expectedRemoteUrl,
} = storeToRefs(localAgent)

const canChooseRepo = computed(() => electronAvailable.value && Boolean(expectedRemoteUrl.value))
const canSave = computed(() => canChooseRepo.value && Boolean(repoPath.value))
const validatingRepo = shallowRef(false)

const isSuccessStatus = computed(() => {
  return repoStatus.value?.startsWith('Clean')
})

const isErrorStatus = computed(() => {
  return repoStatus.value && !repoStatus.value.startsWith('Clean')
})

const hydrate = async () => {
  if (!props.show) return
  await localAgent.loadLocalConfig()
  await localAgent.setWorkspaceContext(props.workspace)
}

const saveRepo = async () => {
  await localAgent.saveRepoMapping(null)
  if (repoMapping.value?.localPath) {
    emit('saved')
  }
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

watch(
  () => [props.show, props.workspace?.id, props.workspace?.git_repo_url],
  (shown) => {
    if (shown[0]) void hydrate()
  },
  { immediate: true },
)
</script>

<template>
  <div
    v-if="show"
    class="repo-setup-overlay animate-fade-in"
    @pointerdown.self="emit('close')"
  >
    <section class="repo-setup-dialog glass-panel animate-pop-in" role="dialog" aria-modal="true">
      <!-- Header -->
      <header class="dialog-header">
        <div class="icon-wrapper">
          <GitBranch class="w-6 h-6" />
        </div>
        <div>
          <h2 class="title-gradient-small">配置本地仓库映射</h2>
          <p class="subtitle">{{ workspace?.name || '当前工作区' }} 需要关联本机仓库路径，以启用本地开发与代码应用能力。</p>
        </div>
      </header>

      <!-- Warnings -->
      <div v-if="!electronAvailable" class="warning-box mt-4">
        <Info class="w-4 h-4 flex-shrink-0" />
        <span>当前是 Web 调试模式，本地仓库映射只在 Electron 客户端可用。</span>
      </div>

      <div v-else-if="!expectedRemoteUrl" class="warning-box mt-4">
        <Info class="w-4 h-4 flex-shrink-0" />
        <span>当前工作区没有配置 Git 仓库地址，暂时无法绑定本地仓库。</span>
      </div>

      <!-- Main Interactive Area -->
      <div v-if="canChooseRepo" class="interaction-area mt-6">
        
        <!-- Step 1: Selection Prompt (Shown when no path is selected) -->
        <div v-if="!repoPath" class="selection-prompt" @click="localAgent.chooseRepo">
          <div class="prompt-icon pulse-animation">
            <FolderOpen class="w-10 h-10" />
          </div>
          <h3 class="mt-4 font-bold text-lg text-primary-900">选择本机仓库目录</h3>
          <p class="text-sm text-muted mt-2 text-center max-w-sm">点击选择本机已经 clone 好的代码目录。系统将自动验证 remote.origin.url 是否匹配。</p>
          
          <div class="interactive-tip mt-6">
            <Info class="w-4 h-4" />
            <span>您可以先跳过，之后进入“设置”中配置。</span>
          </div>
        </div>

        <!-- Step 2: Selected Details & Status (Shown after selection) -->
        <div v-else class="repo-details">
          <div class="detail-card">
            <div class="field-row">
              <span class="field-label">目标源</span>
              <span class="field-value badge-light truncate" :title="expectedRemoteUrl || ''">{{ expectedRemoteUrl }}</span>
            </div>
            
            <div class="connector flex justify-center py-2 text-slate-300">
              <ChevronRight class="w-5 h-5 rotate-90" />
            </div>

            <div class="field-row">
              <span class="field-label">本机目录</span>
              <div class="field-value-group">
                <span class="field-value badge-primary flex-1 truncate" :title="repoPath">{{ repoPath }}</span>
                <button class="btn-icon" @click="localAgent.chooseRepo" title="重新选择">
                  <FolderOpen class="w-4 h-4" />
                </button>
              </div>
            </div>

            <div v-if="repoRemoteUrl" class="field-row mt-3 border-t border-slate-100 pt-3">
              <span class="field-label">检测到源</span>
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
        </div>
      </div>

      <!-- Footer Actions -->
      <footer class="dialog-actions mt-8">
        <button class="btn-ghost" type="button" @click="emit('skip')">暂不配置</button>
        <div class="flex gap-3" v-if="repoPath">
          <el-tooltip :content="t('settings.local_dev.validate_tooltip')" placement="top">
            <span class="tooltip-button-wrap">
              <button
                class="btn-secondary action-button"
                type="button"
                :disabled="!canSave || validatingRepo"
                @click="validateRepoWithFeedback"
              >
                <CheckCircle2 class="w-4 h-4" />
                {{ validatingRepo ? t('settings.local_dev.validating_repo') : t('settings.local_dev.revalidate_repo') }}
              </button>
            </span>
          </el-tooltip>
          <button class="btn-primary action-button" type="button" :disabled="!canSave" @click="saveRepo">
            <Save class="w-4 h-4" /> 保存映射
          </button>
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
/* Base Overlay & Dialog */
.repo-setup-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(8px);
}

.repo-setup-dialog {
  width: min(600px, 100%);
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 16px;
  padding: 2rem;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(12px);
  box-shadow: 0 24px 80px rgba(15, 23, 42, 0.15), inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

/* Typography & Layout Utilities */
.title-gradient-small {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 800;
  background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  color: #64748b;
  font-size: 0.9rem;
  margin-top: 0.5rem;
  line-height: 1.5;
}

/* Header */
.dialog-header {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
}

.icon-wrapper {
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.1), rgba(59, 130, 246, 0.1));
  padding: 0.75rem;
  border-radius: 12px;
  color: #0ea5e9;
  border: 1px solid rgba(14, 165, 233, 0.2);
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
  padding: 3rem 2rem;
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  background: #f8fafc;
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
  background: #f8fafc;
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
  width: 90px;
  flex-shrink: 0;
}

.field-value-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
  min-width: 0;
}

.badge-light {
  background: #f1f5f9;
  color: #334155;
  padding: 0.35rem 0.6rem;
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.75rem;
  border: 1px solid #e2e8f0;
}

.badge-primary {
  background: #eff6ff;
  color: #1d4ed8;
  padding: 0.35rem 0.6rem;
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.75rem;
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
  margin-top: 1rem;
  padding: 1rem;
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

/* Common Text/Flex Utilities */
.text-muted { color: #64748b; }
.text-primary-900 { color: #0f172a; }
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mt-2 { margin-top: 0.5rem; }
.mt-3 { margin-top: 0.75rem; }
.mt-4 { margin-top: 1rem; }
.mt-6 { margin-top: 1.5rem; }
.mt-8 { margin-top: 2rem; }
.py-2 { padding-top: 0.5rem; padding-bottom: 0.5rem; }
.pt-3 { padding-top: 0.75rem; }
.flex { display: flex; }
.items-center { align-items: center; }
.justify-center { justify-content: center; }
.justify-between { justify-content: space-between; }
.gap-2 { gap: 0.5rem; }
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

/* Existing Buttons logic based on WorkspaceView.vue style */
.btn-ghost {
  background: none;
  border: none;
  color: #64748b;
  font-weight: 600;
  cursor: pointer;
  padding: 0.5rem 1rem;
  transition: color 0.2s;
  border-radius: 6px;
}

.btn-ghost:hover {
  color: #0ea5e9;
  background: rgba(15, 23, 42, 0.04);
}

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
  background: #f8fafc;
  color: #334155;
  border: 1px solid #cbd5e1;
  padding: 0.6rem 1.25rem;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s;
}

.btn-secondary:hover:not(:disabled) {
  background: #f1f5f9;
  border-color: #94a3b8;
  color: #0f172a;
}

.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Animations */
@keyframes popIn {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-pop-in {
  animation: popIn 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.animate-fade-in {
  animation: fadeIn 0.3s ease both;
}
</style>
