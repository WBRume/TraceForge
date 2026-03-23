<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Plus, Upload, Loader2, ChevronDown, Sparkles, Globe, FolderOpen } from 'lucide-vue-next'
import api from '@/utils/api'

const props = defineProps<{
  show: boolean
  wsId: string
}>()

const emit = defineEmits(['close', 'created'])

const newTaskName = ref('')
const newTaskDesc = ref('')
const requirementDuration = ref(8)
const useBrainstorm = ref(false)
const creatingTask = ref(false)
const uploadingSpec = ref(false)
const selectedFileName = ref('')
const pendingSpecFile = ref<File | null>(null)

const showSkillPanel = ref(false)
const skillsLoading = ref(false)
const skills = ref<any[]>([])
const selectedSkillIds = ref<string[]>([])

const globalSkills = computed(() => skills.value.filter((s) => s.dimension === 'GLOBAL'))
const workspaceSkills = computed(() => skills.value.filter((s) => s.dimension === 'WORKSPACE'))

const handleFileUpload = (event: any) => {
  const file = event.target.files[0]
  if (!file) return
  pendingSpecFile.value = file
  selectedFileName.value = file.name
}

const loadSkills = async () => {
  skillsLoading.value = true
  try {
    const res = await api.get(`/workspaces/${props.wsId}/skills`, {
      params: { scope: 'all' },
    })
    skills.value = res.data.items || []
  } catch (e) {
    console.error('Failed to load skills', e)
  } finally {
    skillsLoading.value = false
  }
}

const handleCreateTask = async () => {
  if (!newTaskName.value) return
  creatingTask.value = true
  try {
    const res = await api.post(`/workspaces/${props.wsId}/tasks`, {
      name: newTaskName.value,
      description: newTaskDesc.value,
      use_brainstorm: useBrainstorm.value,
      requirement_duration_hours: Number(requirementDuration.value),
      skill_ids: selectedSkillIds.value,
    })

    const taskId = res.data.id

    if (pendingSpecFile.value) {
      uploadingSpec.value = true
      const formData = new FormData()
      formData.append('file', pendingSpecFile.value)
      try {
        await api.post(`/workspaces/${props.wsId}/tasks/${taskId}/upload-spec`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      } catch (uploadError) {
        console.error('Spec upload failed', uploadError)
      } finally {
        uploadingSpec.value = false
      }
    }

    emit('created', taskId)
    resetForm()
  } catch (e) {
    console.error('Failed to create task', e)
  } finally {
    creatingTask.value = false
  }
}

const resetForm = () => {
  newTaskName.value = ''
  newTaskDesc.value = ''
  requirementDuration.value = 8
  pendingSpecFile.value = null
  useBrainstorm.value = false
  selectedFileName.value = ''
  showSkillPanel.value = false
  selectedSkillIds.value = []
}

const close = () => {
  resetForm()
  emit('close')
}

watch(
  () => props.show,
  async (visible) => {
    if (visible) {
      await loadSkills()
    } else {
      resetForm()
    }
  },
)
</script>

<template>
  <div v-if="show" class="modal-overlay" @click.self="close">
    <div class="modal glass-panel">
      <div class="modal-header">
        <Plus class="w-6 h-6 text-primary" />
        <h2>{{ $t('dashboard.new_task') }}</h2>
      </div>

      <form @submit.prevent="handleCreateTask" class="modal-form">
        <div class="form-group">
          <label>{{ $t('dashboard.task_name') }}</label>
          <input
            v-model="newTaskName"
            type="text"
            class="input-field"
            required
            :placeholder="$t('dashboard.task_name_placeholder')"
          />
        </div>

        <div class="form-group">
          <label>{{ $t('dashboard.description') }}</label>
          <textarea
            v-model="newTaskDesc"
            class="input-field"
            rows="3"
            :placeholder="$t('dashboard.desc_placeholder')"
          />
        </div>

        <div class="form-group">
          <label>{{ $t('dashboard.requirement_duration') }}</label>
          <input
            v-model="requirementDuration"
            type="number"
            class="input-field"
            required
            min="0"
            step="0.5"
            :placeholder="$t('dashboard.requirement_placeholder')"
          />
        </div>

        <div class="form-group">
          <label>{{ $t('dashboard.spec_doc') }}</label>
          <div class="file-upload-box glass-panel">
            <Upload v-if="!uploadingSpec" class="w-5 h-5 text-primary" />
            <Loader2 v-else class="w-5 h-5 spin text-primary" />
            <div class="file-name text-slate-600">
              {{ selectedFileName || $t('dashboard.spec_placeholder') }}
            </div>
            <input
              :id="`spec-upload-${props.wsId}`"
              type="file"
              class="hidden-input"
              accept=".pdf,.doc,.docx,.md,.txt"
              @change="handleFileUpload"
            />
            <label :for="`spec-upload-${props.wsId}`" class="btn-primary file-choose-btn">
              {{ $t('common.select') }}
            </label>
          </div>
        </div>

        <div class="form-group checkbox-group py-1">
          <label class="flex items-center gap-2 cursor-pointer text-sm text-slate-700 select-none">
            <input v-model="useBrainstorm" type="checkbox" class="w-4 h-4 accent-primary-600 rounded" />
            {{ $t('dashboard.brainstorm_hint') }}
          </label>
        </div>

        <button type="button" class="expand-btn" @click="showSkillPanel = !showSkillPanel">
          <div class="expand-left">
            <Sparkles class="w-4 h-4" />
            <span>{{ $t('skills.task_panel.expand_title') }}</span>
          </div>
          <ChevronDown class="w-4 h-4 chevron" :class="{ open: showSkillPanel }" />
        </button>

        <div v-if="showSkillPanel" class="skills-panel">
          <div class="skills-header">
            <span>{{ $t('skills.task_panel.hint') }}</span>
            <button type="button" class="link-btn" @click="loadSkills">{{ $t('skills.task_panel.refresh') }}</button>
          </div>

          <div v-if="skillsLoading" class="skills-state">
            <Loader2 class="w-4 h-4 spin" />
            <span>{{ $t('skills.task_panel.loading') }}</span>
          </div>

          <div v-else-if="skills.length === 0" class="skills-state empty">
            {{ $t('skills.task_panel.empty') }}
          </div>

          <div v-else class="skills-groups">
            <div v-if="workspaceSkills.length > 0" class="skills-group">
              <div class="group-title">
                <FolderOpen class="w-4 h-4" />
                <span>{{ $t('skills.task_panel.workspace_group') }}</span>
              </div>
              <label v-for="skill in workspaceSkills" :key="skill.id" class="skill-item">
                <input v-model="selectedSkillIds" type="checkbox" :value="skill.id" />
                <div class="skill-item-body">
                  <div class="skill-name">{{ skill.name }}</div>
                  <div class="skill-desc">{{ skill.description || $t('skills.list.no_description') }}</div>
                </div>
              </label>
            </div>

            <div v-if="globalSkills.length > 0" class="skills-group">
              <div class="group-title">
                <Globe class="w-4 h-4" />
                <span>{{ $t('skills.task_panel.global_group') }}</span>
              </div>
              <label v-for="skill in globalSkills" :key="skill.id" class="skill-item">
                <input v-model="selectedSkillIds" type="checkbox" :value="skill.id" />
                <div class="skill-item-body">
                  <div class="skill-name">{{ skill.name }}</div>
                  <div class="skill-desc">{{ skill.description || $t('skills.list.no_description') }}</div>
                </div>
              </label>
            </div>
          </div>
        </div>

        <div class="modal-actions">
          <button type="button" class="btn-secondary" @click="close">{{ $t('common.cancel') }}</button>
          <button type="submit" class="btn-primary" :disabled="creatingTask">
            {{ creatingTask ? $t('common.loading') : $t('chat.initialize') }}
          </button>
        </div>
      </form>
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
  z-index: 100;
}

.modal {
  width: 92%;
  max-width: 640px;
  max-height: 90vh;
  overflow-y: auto;
  padding: var(--space-8);
  background-color: white;
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-2xl);
}

.modal-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.modal-header h2 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 700;
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #475569;
}

.input-field {
  padding: 10px 14px;
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-md);
  font-family: inherit;
  font-size: 1rem;
  width: 100%;
  box-sizing: border-box;
}

.input-field:focus {
  border-color: var(--color-primary-500);
  outline: none;
}

.file-upload-box {
  border: 1px dashed var(--color-primary-100);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  margin-top: 4px;
  border-radius: var(--radius-md);
}

.file-upload-box:hover {
  border-style: solid;
  border-color: var(--color-primary-500);
}

.file-name {
  flex: 1;
  font-size: 0.875rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-choose-btn {
  padding: 4px 12px;
  font-size: 0.75rem;
  cursor: pointer;
  white-space: nowrap;
}

.expand-btn {
  width: 100%;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.875rem;
  color: #334155;
  transition: all 0.2s;
}

.expand-btn:hover {
  border-color: #7dd3fc;
  background: #f0f9ff;
}

.expand-left {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.chevron {
  transition: transform 0.2s;
}

.chevron.open {
  transform: rotate(180deg);
}

.skills-panel {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.skills-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  color: #64748b;
}

.link-btn {
  border: none;
  background: transparent;
  color: var(--color-primary-600);
  font-weight: 600;
  font-size: 0.8rem;
}

.skills-state {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #475569;
  font-size: 0.84rem;
  padding: 6px 0;
}

.skills-state.empty {
  color: #64748b;
}

.skills-groups {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.skills-group {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 8px;
}

.group-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #0f172a;
  font-weight: 600;
  margin-bottom: 6px;
  font-size: 0.85rem;
}

.skill-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 6px;
  border-radius: 8px;
  cursor: pointer;
}

.skill-item:hover {
  background: #f8fafc;
}

.skill-item-body {
  min-width: 0;
}

.skill-name {
  font-size: 0.84rem;
  color: #1e293b;
  font-weight: 600;
}

.skill-desc {
  margin-top: 2px;
  font-size: 0.75rem;
  color: #64748b;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-2);
}

.btn-secondary {
  background: white;
  color: #475569;
  border: 1px solid #e2e8f0;
  padding: 8px 18px;
  border-radius: var(--radius-md);
  font-weight: 500;
  cursor: pointer;
}

.btn-primary {
  background: var(--color-primary-600);
  color: white !important;
  border: 1px solid var(--color-primary-700);
  padding: 8px 18px;
  border-radius: var(--radius-md);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary:hover {
  background: var(--color-primary-700);
  box-shadow: var(--shadow-md);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.hidden-input {
  display: none;
}

.spin {
  animation: spin 1s linear infinite;
}

.text-primary {
  color: var(--color-primary-600);
}

.text-slate-600 {
  color: #475569;
}

.text-slate-700 {
  color: #334155;
}

.text-sm {
  font-size: 0.875rem;
}

.flex {
  display: flex;
}

.items-center {
  align-items: center;
}

.gap-2 {
  gap: 0.5rem;
}

.py-1 {
  padding-top: 0.25rem;
  padding-bottom: 0.25rem;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.w-5 {
  width: 1.25rem;
  height: 1.25rem;
}

.w-6 {
  width: 1.5rem;
  height: 1.5rem;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>

