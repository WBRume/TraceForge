<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Github, Loader2, X } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import BaseSelect from '@/components/BaseSelect.vue'
import { waitForSkillImportJob } from '@/composables/skills/skillGithubImportJob'

const props = defineProps<{
  show: boolean
  workspaces: Array<{ id: string; name?: string | null }>
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'success', newSkillId: string): void
}>()

const router = useRouter()
const { t } = useI18n()

const loading = ref(false)
const repoUrl = ref('')
const skillName = ref('')
const dimension = ref<'WORKSPACE' | 'GLOBAL'>('WORKSPACE')
const targetWorkspaceId = ref('')
const description = ref('')
const followOfficialSource = ref(false)
const errors = ref({
  repoUrl: false,
  skillName: false,
  targetWorkspace: false,
})

watch(() => props.show, (isVisible) => {
  if (isVisible) {
    repoUrl.value = ''
    skillName.value = ''
    dimension.value = 'WORKSPACE'
    targetWorkspaceId.value = props.workspaces[0]?.id || ''
    description.value = ''
    followOfficialSource.value = false
    errors.value = { repoUrl: false, skillName: false, targetWorkspace: false }
  }
})

watch(() => props.workspaces, (workspaces) => {
  if (targetWorkspaceId.value && workspaces.some((item) => item.id === targetWorkspaceId.value)) return
  targetWorkspaceId.value = workspaces[0]?.id || ''
})

const close = () => {
  if (loading.value) return
  emit('close')
}

const dimensionOptions = computed(() => [
  { value: 'GLOBAL', label: t('skills.editor.dimension_global', 'Global') },
  { value: 'WORKSPACE', label: t('skills.editor.dimension_workspace', 'Workspace') },
])

const workspaceOptions = computed(() => (
  props.workspaces.map((workspace) => ({
    value: String(workspace.id || ''),
    label: String(workspace.name || workspace.id || ''),
  })).filter((item) => item.value)
))

const submit = async () => {
  if (loading.value) return
  
  errors.value.repoUrl = !repoUrl.value.trim()
  errors.value.skillName = !skillName.value.trim()
  errors.value.targetWorkspace = dimension.value === 'WORKSPACE' && !targetWorkspaceId.value
  
  if (errors.value.repoUrl || errors.value.skillName || errors.value.targetWorkspace) return
  
  loading.value = true
  try {
    const contextWorkspaceId = dimension.value === 'WORKSPACE' ? targetWorkspaceId.value : ''
    const res = await api.post('/skills/import/github', {
      dimension: dimension.value,
      workspace_id: dimension.value === 'WORKSPACE' ? targetWorkspaceId.value : null,
      repo_url: repoUrl.value.trim(),
      skill_name: skillName.value.trim(),
      description: description.value.trim() || null,
      follow_official_source: followOfficialSource.value,
    }, {
      params: contextWorkspaceId ? { workspace_id: contextWorkspaceId } : {},
    })

    const legacySkillId = String(res.data?.id || '').trim()
    const jobId = String(res.data?.job_id || '').trim()
    if (legacySkillId) {
      ElMessage.success(t('skills.editor.import_success', 'Imported successfully'))
      emit('success', legacySkillId)
      await router.push({
        name: 'skillsEdit',
        params: { skillId: legacySkillId },
        query: {
          ...(dimension.value === 'WORKSPACE' && targetWorkspaceId.value ? { wsId: targetWorkspaceId.value } : {}),
          ...(followOfficialSource.value ? { readonly: '1' } : {}),
        },
      })
      loading.value = false
      emit('close')
      return
    }

    if (!jobId) {
      throw new Error(t('skills.editor.import_job_missing', 'Skill import job was not created'))
    }

    ElMessage.info(t('skills.editor.import_queued', 'Skill import queued'))
    const result = await waitForSkillImportJob(jobId)
    if (result.state === 'failed') {
      throw new Error(result.message)
    }
    if (result.state === 'timeout') {
      ElMessage.info(t('skills.editor.import_still_running', 'Import is still running in the background. Opening queue status.'))
      loading.value = false
      emit('close')
      await router.push({ name: 'opsQueueDetail', params: { source: 'provision', jobId } })
      return
    }

    ElMessage.success(t('skills.editor.import_success', 'Imported successfully'))
    emit('success', result.skillId)
    await router.push({
      name: 'skillsEdit',
      params: { skillId: result.skillId },
      query: {
        ...(dimension.value === 'WORKSPACE' && targetWorkspaceId.value ? { wsId: targetWorkspaceId.value } : {}),
        ...(followOfficialSource.value ? { readonly: '1' } : {}),
      },
    })
    loading.value = false
    emit('close')
  } catch (e: any) {
    ElMessage.error(formatApiError(e, t('skills.editor.import_failed', 'Import failed'), t))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div v-if="show" class="modal-overlay" @mousedown.self="close">
    <div class="modal glass-panel">
      <div class="modal-header">
        <div class="header-title">
          <Github class="w-5 h-5 text-primary" />
          <h3>{{ $t('skills.list.new_skill_github') }}</h3>
        </div>
        <button class="close-btn" @click="close" :disabled="loading">
          <X class="w-5 h-5" />
        </button>
      </div>

      <div class="modal-body">
        <div class="form-group-row">
          <div class="form-group flex-1">
            <label>{{ $t('skills.editor.dimension') }} <span class="required">*</span></label>
            <BaseSelect
              v-model="dimension"
              :options="dimensionOptions"
              :disabled="loading"
            />
          </div>
          <div class="form-group flex-1" :class="{ 'has-error': errors.skillName }">
            <label>{{ $t('skills.editor.github_skill_name') }} <span class="required">*</span></label>
            <input
              v-model="skillName"
              type="text"
              class="form-input"
              :placeholder="$t('skills.editor.github_skill_name_placeholder')"
              :disabled="loading"
              @focus="errors.skillName = false"
            />
            <span v-if="errors.skillName" class="error-msg">{{ $t('common.required_field', 'This field is required') }}</span>
          </div>
        </div>

        <div v-if="dimension === 'WORKSPACE'" class="form-group" :class="{ 'has-error': errors.targetWorkspace }">
          <label>{{ $t('skills.editor.target_workspace') }} <span class="required">*</span></label>
          <BaseSelect
            v-model="targetWorkspaceId"
            :options="workspaceOptions"
            :disabled="loading"
          />
          <span v-if="errors.targetWorkspace" class="error-msg">{{ $t('common.required_field', 'This field is required') }}</span>
        </div>

        <div class="form-group" :class="{ 'has-error': errors.repoUrl }">
          <label>{{ $t('skills.editor.github_repo_url') }} <span class="required">*</span></label>
          <input
            v-model="repoUrl"
            type="text"
            class="form-input"
            :placeholder="$t('skills.editor.github_repo_url_placeholder')"
            :disabled="loading"
            @focus="errors.repoUrl = false"
          />
          <span v-if="errors.repoUrl" class="error-msg">{{ $t('common.required_field', 'This field is required') }}</span>
        </div>

        <div class="form-group">
          <label>{{ $t('skills.editor.description') }}</label>
          <input
            v-model="description"
            type="text"
            class="form-input"
            :placeholder="$t('skills.editor.description_placeholder')"
            :disabled="loading"
          />
        </div>

        <div class="import-hint">
          <p>{{ $t('skills.editor.github_import_hint') }}</p>
        </div>

        <label class="follow-source-option">
          <input
            v-model="followOfficialSource"
            type="checkbox"
            :disabled="loading"
          />
          <span class="follow-source-copy">
            <strong>{{ $t('skills.editor.follow_official_source') }}</strong>
            <small>{{ $t('skills.editor.follow_official_source_hint') }}</small>
          </span>
        </label>
      </div>

      <div class="modal-footer">
        <button class="btn-secondary" @click="close" :disabled="loading">
          {{ $t('common.cancel') }}
        </button>
        <button class="btn-primary" @click="submit" :disabled="loading">
          <Loader2 v-if="loading" class="w-4 h-4 spin" />
          <span>{{ loading ? $t('skills.editor.importing', 'Importing...') : $t('skills.editor.import_from_github', 'Import') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  width: 90%;
  max-width: 480px;
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #e2e8f0;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid #f1f5f9;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.header-title h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: #0f172a;
}

.text-primary {
  color: #0ea5e9;
}

.close-btn {
  background: transparent;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.25rem;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.close-btn:hover:not(:disabled) {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-body {
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-group-row {
  display: flex;
  gap: 1rem;
}

.flex-1 {
  flex: 1;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #334155;
}

.required {
  color: #ef4444;
}

.form-input {
  width: 100%;
  padding: 0.625rem 0.875rem;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.875rem;
  color: #0f172a;
  background: #ffffff;
  transition: all 0.2s;
}

.form-input:focus {
  outline: none;
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.1);
}

.form-input:disabled {
  background: #f8fafc;
  color: #94a3b8;
  cursor: not-allowed;
}

.form-group.has-error .form-input {
  border-color: #ef4444;
}

.form-group.has-error .form-input:focus {
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.1);
}

.error-msg {
  color: #ef4444;
  font-size: 0.75rem;
}

.import-hint {
  padding: 1rem;
  background: #f8fafc;
  border-radius: 8px;
  border-left: 3px solid #cbd5e1;
}

.import-hint p {
  margin: 0;
  font-size: 0.8125rem;
  color: #64748b;
  line-height: 1.5;
}

.follow-source-option {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.95rem 1rem;
  border: 1px solid #bae6fd;
  border-radius: 10px;
  background: linear-gradient(135deg, #f0f9ff 0%, #ffffff 100%);
  cursor: pointer;
}

.follow-source-option input {
  width: 1rem;
  height: 1rem;
  margin-top: 0.15rem;
  accent-color: #0ea5e9;
  cursor: pointer;
}

.follow-source-option input:disabled {
  cursor: not-allowed;
}

.follow-source-copy {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.follow-source-copy strong {
  color: #075985;
  font-size: 0.875rem;
  font-weight: 700;
}

.follow-source-copy small {
  color: #64748b;
  font-size: 0.78rem;
  line-height: 1.45;
}

.modal-footer {
  padding: 1rem 1.5rem;
  background: #f8fafc;
  border-top: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
}

.btn-secondary {
  padding: 0.5rem 1rem;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #475569;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover:not(:disabled) {
  background: #f1f5f9;
  border-color: #94a3b8;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1.25rem;
  background: #0ea5e9;
  border: 1px solid #0ea5e9;
  color: #ffffff;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary:hover:not(:disabled) {
  background: #0284c7;
  border-color: #0284c7;
}

.btn-primary:disabled,
.btn-secondary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
