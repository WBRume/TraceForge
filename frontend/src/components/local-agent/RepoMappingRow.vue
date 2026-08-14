<!-- Single repository local-path mapping row (shared by settings and setup dialog). -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { CheckCircle2, FolderOpen, Unlink, XCircle, Info, Save } from 'lucide-vue-next'
import { useLocalAgentStore } from '@/stores/localAgent'

const props = defineProps<{
  remoteUrl: string
  repoName: string
}>()

const emit = defineEmits<{
  (e: 'changed'): void
}>()

const { t } = useI18n()
const localAgent = useLocalAgentStore()
const { electronAvailable } = storeToRefs(localAgent)

const localPath = ref('')
const validating = ref(false)
const saving = ref(false)

const statusText = computed(() => localAgent.statusFor(props.remoteUrl))
const mapping = computed(() => localAgent.mappingFor(props.remoteUrl))

const isBound = computed(() => Boolean(mapping.value?.localPath))
const isSuccessStatus = computed(() => statusText.value.startsWith('Clean'))
const isErrorStatus = computed(() => Boolean(statusText.value) && !statusText.value.startsWith('Clean'))

const hydrate = () => {
  localPath.value = mapping.value?.localPath || ''
}

const chooseLocal = async () => {
  if (!localAgent.desktop) return
  const result = await localAgent.desktop.git.selectDirectory()
  if (result.canceled || !result.path) return
  localPath.value = result.path
  await localAgent.validateRemote(props.remoteUrl, result.path)
}

const validateWithFeedback = async () => {
  if (!localPath.value) {
    ElMessage.warning(t('settings.local_dev.validate_select_repo_first'))
    return
  }
  validating.value = true
  try {
    await localAgent.validateRemote(props.remoteUrl, localPath.value)
    const status = localAgent.statusFor(props.remoteUrl)
    if (!status) {
      ElMessage.error(t('settings.local_dev.validate_not_git'))
      return
    }
    if (!status.startsWith('Clean')) {
      ElMessage.warning(t('settings.local_dev.validate_dirty'))
      return
    }
    ElMessage.success(t('settings.local_dev.validate_success'))
  } catch {
    ElMessage.error(t('settings.local_dev.validate_failed'))
  } finally {
    validating.value = false
  }
}

const saveMapping = async () => {
  if (!localPath.value) return
  saving.value = true
  try {
    const ok = await localAgent.saveMappingFor(props.remoteUrl, localPath.value)
    if (ok) {
      emit('changed')
    }
  } finally {
    saving.value = false
  }
}

const removeMapping = async () => {
  await localAgent.removeMappingFor(props.remoteUrl)
  localPath.value = ''
  emit('changed')
}

watch(
  () => [props.remoteUrl, mapping.value?.localPath],
  () => {
    hydrate()
  },
  { immediate: true },
)
</script>

<template>
  <div class="repo-row">
    <div class="repo-row-head">
      <div class="repo-row-title">
        <span class="repo-row-name">{{ repoName }}</span>
        <span class="repo-row-remote truncate" :title="remoteUrl">{{ remoteUrl }}</span>
      </div>
      <span class="repo-row-state" :class="{ bound: isBound, unbound: !isBound }">
        {{ isBound ? $t('settings.local_dev.repo_bound') : $t('settings.local_dev.repo_unbound') }}
      </span>
    </div>

    <div class="repo-row-body">
      <div class="repo-row-path">
        <input
          v-model="localPath"
          type="text"
          class="mgmt-input"
          readonly
          :placeholder="$t('settings.local_dev.choose_repo_hint')"
          @click="chooseLocal"
        />
        <button class="btn-icon" type="button" :title="$t('settings.local_dev.choose_repo')" @click="chooseLocal">
          <FolderOpen class="w-4 h-4" />
        </button>
      </div>

      <div v-if="statusText" class="repo-row-status" :class="{ success: isSuccessStatus, error: isErrorStatus }">
        <CheckCircle2 v-if="isSuccessStatus" class="w-4 h-4 flex-shrink-0" />
        <XCircle v-else-if="isErrorStatus" class="w-4 h-4 flex-shrink-0" />
        <Info v-else class="w-4 h-4 flex-shrink-0" />
        <span class="break-all">{{ statusText }}</span>
      </div>

      <div class="repo-row-actions">
        <button
          class="btn-secondary action-button"
          type="button"
          :disabled="!electronAvailable || !localPath || validating"
          @click="validateWithFeedback"
        >
          <CheckCircle2 class="w-4 h-4" />
          {{ validating ? t('settings.local_dev.validating_repo') : t('settings.local_dev.validate_repo') }}
        </button>
        <button
          class="btn-primary action-button"
          type="button"
          :disabled="!electronAvailable || !localPath || saving"
          @click="saveMapping"
        >
          <Save class="w-4 h-4" />
          {{ saving ? t('common.saving') : t('settings.local_dev.save_mapping') }}
        </button>
        <button
          v-if="isBound"
          class="btn-secondary danger action-button"
          type="button"
          :disabled="!electronAvailable"
          @click="removeMapping"
        >
          <Unlink class="w-4 h-4" />
          {{ t('settings.local_dev.remove_mapping') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.repo-row {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 0.9rem 1rem;
  background: rgba(248, 250, 252, 0.6);
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.repo-row-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}

.repo-row-title {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.repo-row-name {
  font-weight: 700;
  font-size: 0.9rem;
  color: #0f172a;
}

.repo-row-remote {
  font-size: 0.72rem;
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.repo-row-state {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.1rem 0.55rem;
  border-radius: 999px;
  white-space: nowrap;
}

.repo-row-state.bound {
  color: #15803d;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
}

.repo-row-state.unbound {
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.repo-row-body {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.repo-row-path {
  display: flex;
  gap: 0.5rem;
}

.repo-row-path .mgmt-input {
  flex: 1;
  cursor: pointer;
}

.repo-row-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.78rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
}

.repo-row-status.success {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #15803d;
}

.repo-row-status.error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
}

.repo-row-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.action-button {
  display: flex;
  align-items: center;
  gap: 0.45rem;
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
}

.btn-icon:hover {
  background: #f8fafc;
  border-color: #0ea5e9;
  color: #0ea5e9;
}

.btn-secondary.danger {
  color: #ef4444;
  border-color: #fca5a5;
  background: #fef2f2;
}

.truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.break-all {
  word-break: break-all;
}
</style>
