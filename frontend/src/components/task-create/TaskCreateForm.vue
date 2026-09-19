<!-- TaskCreateForm: 任务创建草稿表单。
     持有草稿字段与附件文件（随弹窗挂载/销毁天然复位），提交时发出草稿快照；
     仓库 / Skills 侧栏入口条只负责发出切换事件，不做任何业务判断。 -->
<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { ChevronRight, Clock, FileText, GitFork, Loader2, Sparkles, Upload, X } from 'lucide-vue-next'
import type { TaskCreateSidebar, TaskCreateSidebarName, TaskDraftSnapshot, TaskTypeValue } from './types'

const props = defineProps<{
  wsId: string
  taskType: TaskTypeValue
  creating: boolean
  /** 工作区绑定仓库数（>0 才显示仓库入口条） */
  reposTotal: number
  selectedRepoCount: number
  selectedSkillCount: number
  activeSidebar: TaskCreateSidebar
}>()

const emit = defineEmits<{
  submit: [draft: TaskDraftSnapshot]
  cancel: []
  'toggle-sidebar': [name: TaskCreateSidebarName]
}>()

const isDiagnosisTask = computed(() => props.taskType === 'DIAGNOSIS')

const PRIORITIES = ['P0', 'P1', 'P2', 'P3'] as const

// ── 草稿字段 ──
const name = shallowRef('')
const description = shallowRef('')
const phenomenon = shallowRef('')
const priority = shallowRef('P2')
const requirementDuration = shallowRef(8)

// ── 附件：研发态规范文档（单文件）/ 诊断态文档（多文件，类型不限） ──
const specFile = shallowRef<File | null>(null)
const diagnosisFiles = shallowRef<File[]>([])

const isPdfSpecFile = computed(() => (specFile.value?.name || '').toLowerCase().endsWith('.pdf'))

const handleSpecFileUpload = (event: Event) => {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  specFile.value = file
}

const handleDiagnosisFiles = (event: Event) => {
  const files = Array.from((event.target as HTMLInputElement).files || [])
  if (files.length === 0) return
  diagnosisFiles.value = [...diagnosisFiles.value, ...files]
  ;(event.target as HTMLInputElement).value = ''
}

const removeDiagnosisFile = (index: number) => {
  diagnosisFiles.value = diagnosisFiles.value.filter((_, i) => i !== index)
}

const submitDraft = () => {
  emit('submit', {
    taskType: props.taskType,
    name: name.value,
    description: description.value,
    phenomenon: phenomenon.value,
    priority: priority.value,
    requirementDurationHours: Number(requirementDuration.value),
    specFile: specFile.value,
    diagnosisFiles: [...diagnosisFiles.value],
  })
}

/** 清空草稿（创建成功后由对话框调用） */
const reset = () => {
  name.value = ''
  description.value = ''
  phenomenon.value = ''
  priority.value = 'P2'
  requirementDuration.value = 8
  specFile.value = null
  diagnosisFiles.value = []
}

defineExpose({ reset })
</script>

<template>
  <form class="modal-form-main" @submit.prevent="submitDraft">
    <!-- 行 1：任务名称 -->
    <div class="form-row">
      <div class="form-group">
        <label class="form-label">
          <span>{{ $t('dashboard.task_name') }}</span>
          <span class="required">*</span>
        </label>
        <input
          v-model="name"
          type="text"
          class="input-field primary-input"
          required
          :placeholder="$t('dashboard.task_name_placeholder')"
        />
      </div>
    </div>

    <!-- 行 2：双列网格（研发态：工时 + 规范文档上传；诊断态：优先级 + 文档上传） -->
    <div class="form-row form-grid-2">
      <!-- 研发态工时 -->
      <div v-if="!isDiagnosisTask" class="form-group">
        <label class="form-label">
          <Clock class="w-3.5 h-3.5 text-slate-400" />
          <span>{{ $t('dashboard.requirement_duration') }}</span>
        </label>
        <div class="input-with-suffix">
          <input
            v-model="requirementDuration"
            type="number"
            class="input-field"
            required
            min="0"
            step="0.5"
            :placeholder="$t('dashboard.requirement_placeholder')"
          />
          <span class="input-suffix">h</span>
        </div>
      </div>

      <!-- 诊断态优先级 -->
      <div v-if="isDiagnosisTask" class="form-group">
        <label class="form-label">
          <span>{{ $t('diagnosis.priority') }}</span>
        </label>
        <div class="priority-options">
          <button
            v-for="p in PRIORITIES"
            :key="p"
            type="button"
            class="priority-option"
            :class="{ active: priority === p, [`prio-${p.toLowerCase()}`]: true }"
            @click="priority = p"
          >
            {{ p }}
          </button>
        </div>
      </div>

      <!-- 规范文档上传（研发态） -->
      <div v-if="!isDiagnosisTask" class="form-group">
        <label class="form-label">
          <FileText class="w-3.5 h-3.5 text-slate-400" />
          <span>{{ $t('dashboard.spec_doc') }}</span>
        </label>
        <div class="file-upload-box glass-panel compact-upload">
          <Upload v-if="!creating" class="w-4 h-4 text-primary flex-shrink-0" />
          <Loader2 v-else class="w-4 h-4 spin text-primary flex-shrink-0" />
          <div class="file-name text-slate-600">
            {{ specFile?.name || $t('dashboard.spec_placeholder') }}
          </div>
          <input
            :id="`spec-upload-${props.wsId}`"
            type="file"
            class="hidden-input"
            accept=".pdf,.docx,.md,.txt"
            @change="handleSpecFileUpload"
          />
          <label :for="`spec-upload-${props.wsId}`" class="btn-primary file-choose-btn">
            {{ $t('common.select') }}
          </label>
        </div>
        <p v-if="isPdfSpecFile" class="pdf-agent-hint">
          {{ $t('dashboard.spec_pdf_agent_hint') }}
        </p>
      </div>

      <!-- 诊断态文档上传 -->
      <div v-if="isDiagnosisTask" class="form-group">
        <label class="form-label">
          <FileText class="w-3.5 h-3.5 text-slate-400" />
          <span>{{ $t('diagnosis.docs_upload_label') }}</span>
        </label>
        <div class="file-upload-box glass-panel compact-upload">
          <Upload v-if="!creating" class="w-4 h-4 text-primary flex-shrink-0" />
          <Loader2 v-else class="w-4 h-4 spin text-primary flex-shrink-0" />
          <div class="file-name text-slate-600">
            {{ $t('diagnosis.docs_upload_placeholder') }}
          </div>
          <input
            :id="`diag-docs-upload-${props.wsId}`"
            type="file"
            class="hidden-input"
            multiple
            @change="handleDiagnosisFiles"
          />
          <label :for="`diag-docs-upload-${props.wsId}`" class="btn-primary file-choose-btn">
            {{ $t('common.select') }}
          </label>
        </div>
      </div>
    </div>

    <!-- 诊断模式已选文件列表 -->
    <div v-if="isDiagnosisTask && diagnosisFiles.length > 0" class="diagnosis-files-list">
      <div v-for="(file, index) in diagnosisFiles" :key="`${file.name}-${index}`" class="diagnosis-file-row">
        <FileText class="w-3.5 h-3.5 diagnosis-file-icon" />
        <span class="diagnosis-file-name">{{ file.name }}</span>
        <button type="button" class="diagnosis-file-remove" :title="$t('common.delete')" @click="removeDiagnosisFile(index)">
          <X class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- 行 3：初始化提示词 / 现象描述 -->
    <div class="form-row">
      <div class="form-group">
        <label class="form-label">
          <span>{{ isDiagnosisTask ? $t('diagnosis.phenomenon') : $t('dashboard.description') }}</span>
          <span v-if="isDiagnosisTask" class="required">*</span>
        </label>
        <textarea
          v-if="!isDiagnosisTask"
          v-model="description"
          class="input-field textarea-field"
          rows="3"
          :placeholder="$t('dashboard.desc_placeholder')"
        />
        <textarea
          v-else
          v-model="phenomenon"
          class="input-field textarea-field"
          rows="3"
          required
          :placeholder="$t('diagnosis.phenomenon_placeholder')"
        />
      </div>
    </div>

    <!-- 行 4：Worktree 仓库载入触发条（整行可点击展开右侧仓库树） -->
    <div v-if="reposTotal > 0" class="form-meta-container">
      <div
        class="meta-skills-bar skills-entry-card repo-entry-card"
        :class="{ active: activeSidebar === 'repos', 'has-selection': selectedRepoCount > 0 }"
        @click="emit('toggle-sidebar', 'repos')"
      >
        <div class="skills-bar-left">
          <div class="skills-bar-icon-box">
            <GitFork class="w-3.5 h-3.5 text-primary" />
          </div>
          <span class="skills-bar-title">{{ $t('dashboard.task_repo_entry_title') }}</span>
          <span class="skills-bar-badge" :class="{ 'has-selected': selectedRepoCount > 0 }">
            {{ $t('dashboard.task_repo_selected_badge', { selected: selectedRepoCount, total: reposTotal }) }}
          </span>
        </div>
        <div class="skills-bar-right">
          <span class="skills-bar-action-text">{{ activeSidebar === 'repos' ? $t('skills.task_panel.close_panel') : $t('dashboard.task_repo_entry_action') }}</span>
          <ChevronRight class="w-3.5 h-3.5 chevron-icon" :class="{ open: activeSidebar === 'repos' }" />
        </div>
      </div>
    </div>

    <!-- 行 5：Skills 载入触发条（独占一行，整行可点击，研发 / 诊断态均可用） -->
    <div class="form-meta-container">
      <div
        class="meta-skills-bar skills-entry-card"
        :class="{ active: activeSidebar === 'skills', 'has-selection': selectedSkillCount > 0 }"
        @click="emit('toggle-sidebar', 'skills')"
      >
        <div class="skills-bar-left">
          <div class="skills-bar-icon-box">
            <Sparkles class="w-3.5 h-3.5 text-primary" />
          </div>
          <span class="skills-bar-title">{{ $t('skills.task_panel.expand_title') }}</span>
          <span class="skills-bar-badge" :class="{ 'has-selected': selectedSkillCount > 0 }">
            {{ selectedSkillCount > 0
              ? $t('skills.task_panel.selected_count', { count: selectedSkillCount })
              : $t('skills.task_panel.none_selected')
            }}
          </span>
        </div>
        <div class="skills-bar-right">
          <span class="skills-bar-action-text">{{ activeSidebar === 'skills' ? $t('skills.task_panel.close_panel') : $t('skills.task_panel.select_skills') }}</span>
          <ChevronRight class="w-3.5 h-3.5 chevron-icon" :class="{ open: activeSidebar === 'skills' }" />
        </div>
      </div>
    </div>

    <!-- 底部操作区 -->
    <div class="modal-footer">
      <div class="footer-left-hint">
        <span v-if="selectedSkillCount > 0" class="footer-skills-hint">
          <Sparkles class="w-3.5 h-3.5 text-primary" />
          {{ $t('skills.task_panel.selected_count', { count: selectedSkillCount }) }}
        </span>
      </div>
      <div class="footer-actions">
        <button type="button" class="btn-secondary modal-btn" @click="emit('cancel')">{{ $t('common.cancel') }}</button>
        <button type="submit" class="btn-primary modal-btn" :disabled="creating">
          <Loader2 v-if="creating" class="w-4 h-4 spin" />
          <span>{{ creating ? $t('common.loading') : $t('chat.initialize') }}</span>
        </button>
      </div>
    </div>
  </form>
</template>

<style scoped src="@/styles/task-create/task-create-shared.css"></style>
<style scoped>
.modal-form-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 1.2rem 1.4rem 1.2rem;
  display: flex;
  flex-direction: column;
  gap: 0.95rem;
}

.form-row {
  display: flex;
  flex-direction: column;
}

.form-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1.35fr;
  gap: 12px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.form-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 4px;
}

.required {
  color: #ef4444;
}

.input-field {
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-family: inherit;
  font-size: 0.875rem;
  width: 100%;
  box-sizing: border-box;
  background: #ffffff;
  color: #0f172a;
  transition: all 0.2s;
}

.input-field:focus {
  border-color: #0ea5e9;
  outline: none;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.input-field::placeholder {
  color: #94a3b8;
  font-size: 0.82rem;
}

.primary-input {
  font-weight: 500;
}

.input-with-suffix {
  position: relative;
  display: flex;
  align-items: center;
}

.input-with-suffix input {
  padding-right: 28px;
}

.input-suffix {
  position: absolute;
  right: 10px;
  font-size: 0.78rem;
  font-weight: 600;
  color: #94a3b8;
  pointer-events: none;
}

.textarea-field {
  resize: vertical;
  min-height: 80px;
  line-height: 1.45;
}

/* 优先级选择胶囊 */
.priority-options {
  display: flex;
  gap: 6px;
}

.priority-option {
  flex: 1;
  padding: 6px 0;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
  font-size: 0.78rem;
  font-weight: 700;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
  text-align: center;
}

.priority-option:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
}

.priority-option.active.prio-p0 {
  border-color: #ef4444;
  background: #fef2f2;
  color: #b91c1c;
}

.priority-option.active.prio-p1 {
  border-color: #f97316;
  background: #fff7ed;
  color: #c2410c;
}

.priority-option.active.prio-p2 {
  border-color: #0ea5e9;
  background: #f0f9ff;
  color: #0369a1;
}

.priority-option.active.prio-p3 {
  border-color: #94a3b8;
  background: #f1f5f9;
  color: #475569;
}

/* 规范文档上传区域 */
.file-upload-box {
  border: 1px dashed var(--color-primary-100);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
}

.compact-upload {
  padding: 6px 10px;
  min-height: 38px;
  box-sizing: border-box;
}

.file-upload-box:hover {
  border-style: solid;
  border-color: var(--color-primary-500);
}

.file-name {
  flex: 1;
  font-size: 0.8rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-choose-btn {
  padding: 3px 10px;
  font-size: 0.72rem;
  cursor: pointer;
  white-space: nowrap;
}

.pdf-agent-hint {
  margin: 6px 0 0;
  font-size: 0.78rem;
  line-height: 1.5;
  color: #b45309;
}

.hidden-input {
  display: none;
}

/* 仓库 / Skills 入口条容器（垂直两行排列，彻底避免横向重叠与遮挡） */
.form-meta-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 2px;
}

/* 入口条（整行可点击） */
.meta-skills-bar {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.meta-skills-bar:hover {
  border-color: #7dd3fc;
  background: #f0f9ff;
  transform: translateY(-1px);
}

.meta-skills-bar.active {
  border-color: #0ea5e9;
  background: #f0f9ff;
  box-shadow: 0 0 0 1px #0ea5e9, 0 2px 6px rgba(14, 165, 233, 0.08);
}

.skills-bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.skills-bar-icon-box {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #f0f9ff;
  border: 1px solid #e0f2fe;
  display: flex;
  align-items: center;
  justify-content: center;
}

.skills-bar-title {
  font-size: 0.8rem;
  font-weight: 700;
  color: #0f172a;
}

.skills-bar-badge {
  font-size: 0.7rem;
  padding: 1px 7px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-weight: 500;
}

.skills-bar-badge.has-selected {
  background: #0ea5e9;
  color: #ffffff;
  font-weight: 600;
}

.skills-bar-right {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #0ea5e9;
  font-size: 0.76rem;
  font-weight: 600;
}

.skills-bar-action-text {
  font-size: 0.76rem;
}

.chevron-icon {
  transition: transform 0.2s;
}

.chevron-icon.open {
  transform: rotate(90deg);
}

/* 诊断模式文件列表 */
.diagnosis-files-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: -4px;
}

.diagnosis-file-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
  font-size: 0.76rem;
}

.diagnosis-file-icon {
  flex-shrink: 0;
  color: #0ea5e9;
}

.diagnosis-file-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1e293b;
  font-weight: 500;
}

.diagnosis-file-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: color 0.2s;
}

.diagnosis-file-remove:hover {
  color: #ef4444;
}

/* 底部操作区 */
.modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}

.footer-left-hint {
  display: flex;
  align-items: center;
  font-size: 0.74rem;
  color: #64748b;
}

.footer-skills-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 600;
  color: #0369a1;
  background: #f0f9ff;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid #e0f2fe;
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.modal-btn {
  padding: 7px 16px;
  font-size: 0.84rem;
  border-radius: 8px;
}

.btn-primary {
  background: #0ea5e9;
  color: #ffffff !important;
  border: none;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 4px 6px -1px rgba(14, 165, 233, 0.2);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.btn-primary:hover {
  background: #0284c7;
  transform: translateY(-1px);
  box-shadow: 0 8px 12px -2px rgba(14, 165, 233, 0.25);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}
</style>
