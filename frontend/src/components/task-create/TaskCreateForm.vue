<script setup lang="ts">
import { computed, nextTick, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { BookOpen, ChevronRight, FileText, GitFork, Loader2, Sparkles } from '@/components/icons'
import TaskResourcePicker from '@/components/local-resource/TaskResourcePicker.vue'
import AgentModelSelect from '@/components/agent/AgentModelSelect.vue'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import { isDesktop } from '@/utils/runtime'
import TaskAttachmentFields from './TaskAttachmentFields.vue'
import TaskCreateReview from './TaskCreateReview.vue'
import { useTaskCreateDraft } from './composables/useTaskCreateDraft'
import type { TaskCreateFormProps, TaskCreateSidebarName, TaskCreateStep, TaskDraftSnapshot } from './types'

const props = defineProps<TaskCreateFormProps>()
const emit = defineEmits<{
  submit: [draft: TaskDraftSnapshot]
  cancel: []
  'toggle-sidebar': [name: TaskCreateSidebarName]
  'playbook-context': [context: { name: string; description: string }]
  'retry-requirement': []
  'retry-repos': []
  'step-change': [step: TaskCreateStep]
}>()
const { t } = useI18n()
const { isDiagnosisTask, execution, localCollaborationIntent, models, name, description,
  phenomenon, priority, sopAutoRun, requirementDuration, specFile, diagnosisFiles, snapshot, reset } =
  useTaskCreateDraft(props, context => emit('playbook-context', context))
const guided = computed(() => props.mode === 'guided')
const steps: TaskCreateStep[] = ['content', 'environment', 'options', 'review']
const step = shallowRef<TaskCreateStep>('content')
const validationMessage = shallowRef('')
const executionLabel = shallowRef('')
const formContent = useTemplateRef<HTMLElement>('formContent')
const stepHeading = useTemplateRef<HTMLElement>('stepHeading')
const modelLabel = computed(() => models.options.value.find(item => item.value === models.selected.value)?.label || models.selected.value || t('task_create.default_model'))
const visible = (target: TaskCreateStep) => !guided.value || target === step.value

function goTo(target: TaskCreateStep) {
  if (props.creating) return
  step.value = target
  validationMessage.value = ''
  emit('step-change', target)
  void nextTick(() => {
    formContent.value?.scrollTo?.({ top: 0 })
    stepHeading.value?.focus({ preventScroll: true })
  })
}

function validateThrough(target: TaskCreateStep): boolean {
  let issue: { step: TaskCreateStep; key: string } | undefined
  if (!isDiagnosisTask.value && props.requirementLoading) issue = { step: 'content', key: 'task_rail.loading_context' }
  else if (!isDiagnosisTask.value && props.requirementError) issue = { step: 'content', key: 'task_rail.context_error' }
  else if (!isDiagnosisTask.value && props.requirementRequired && !props.selectedRequirement) issue = { step: 'content', key: 'task_rail.select_requirement' }
  else if (!name.value.trim()) issue = { step: 'content', key: 'task_create.name_required' }
  else if (isDiagnosisTask.value && !phenomenon.value.trim()) issue = { step: 'content', key: 'diagnosis.phenomenon_required' }
  else if (target !== 'content') {
    if (props.reposLoading) issue = { step: 'environment', key: 'task_create.repos_loading' }
    else if (props.reposError) issue = { step: 'environment', key: 'task_create.repos_error' }
    else if (props.reposTotal > 0 && props.selectedRepoCount === 0) issue = { step: 'environment', key: 'dashboard.task_repo_required' }
    else if (models.loading.value) issue = { step: 'environment', key: 'task_create.models_loading' }
    else if (target !== 'environment' && !isDiagnosisTask.value && (String(requirementDuration.value).trim() === '' || !Number.isFinite(Number(requirementDuration.value)) || Number(requirementDuration.value) < 0 || Number(requirementDuration.value) % 0.5 !== 0)) issue = { step: 'options', key: 'task_create.duration_invalid' }
  }
  if (!issue) return true
  goTo(issue.step)
  validationMessage.value = t(issue.key)
  return false
}

function submitDraft() {
  if (props.creating) return
  if (guided.value) {
    if (!validateThrough(step.value)) return
    if (step.value !== 'review') {
      goTo(steps[steps.indexOf(step.value) + 1]!)
      return
    }
  }
  emit('submit', snapshot.value)
}

watch(() => props.taskType, () => { if (guided.value) goTo('content') })
watch(() => props.mode, () => goTo('content'))
defineExpose({ reset, goTo })
</script>

<template>
  <form class="modal-form-main" :class="{ 'guided-form': guided }" :novalidate="guided" @submit.prevent="submitDraft">
    <div ref="formContent" class="form-content">
    <div v-if="guided" class="guide-heading" tabindex="-1" ref="stepHeading">
      <span class="guide-eyebrow">{{ $t('task_create.step_count', { current: steps.indexOf(step) + 1, total: steps.length }) }}</span>
      <h3>{{ $t(`task_create.steps.${step}.heading`) }}</h3>
      <p>{{ $t(isDiagnosisTask && step === 'content' ? 'task_create.diagnosis_content_hint' : `task_create.steps.${step}.hint`) }}</p>
    </div>
    <p v-if="validationMessage" class="guide-error" role="alert">{{ validationMessage }}</p>
    <fieldset class="form-fields" :disabled="creating">
    <slot v-if="guided && step === 'content'" name="task-type" />
    <TaskResourcePicker v-show="visible('environment')" :workspace-id="wsId" @change="execution = $event" @label-change="executionLabel = $event" />
    <p v-if="guided && step === 'environment' && !isDesktop()" class="guide-notice">{{ $t('task_create.server_execution_hint') }}</p>
    <div v-if="!isDiagnosisTask" v-show="visible('content')" class="form-meta-container">
      <button type="button" class="meta-skills-bar skills-entry-card requirement-entry-card"
        :class="{ active: activeSidebar === 'requirements', 'has-selection': Boolean(selectedRequirement) }" :disabled="creating"
        :aria-expanded="activeSidebar === 'requirements'" @click="emit('toggle-sidebar', 'requirements')">
        <span class="skills-bar-left"><span class="skills-bar-icon-box"><FileText class="w-3.5 h-3.5 text-primary" /></span><span class="skills-bar-title">{{ $t('task_rail.requirement_optional') }}</span></span>
        <span class="skills-bar-right"><span class="skills-bar-action-text requirement-selection">{{ selectedRequirement?.title || $t('task_rail.select_requirement') }}</span><ChevronRight class="w-3.5 h-3.5 chevron-icon" :class="{ open: activeSidebar === 'requirements' }" /></span>
      </button>
      <small v-if="requirementLocked" class="requirement-context-hint">{{ $t('task_rail.inherited') }}</small>
      <small v-if="requirementLoading" class="requirement-context-hint">{{ $t('task_rail.loading_context') }}</small>
      <div v-if="requirementError" class="requirement-context-error" role="alert">{{ $t('task_rail.context_error') }} <button type="button" @click="emit('retry-requirement')">{{ $t('task_rail.retry') }}</button></div>
    </div>
    <div v-show="visible('environment')" class="form-row">
      <div class="form-group">
        <label class="form-label">{{ $t('task_create.model') }}</label>
        <AgentModelSelect
          :model-value="models.selected.value" :options="models.options.value"
          :loading="models.loading.value" :error="models.error.value" :disabled="creating"
          @update:model-value="models.select" @retry="models.reload" @refresh="models.reload"
        />
      </div>
    </div>
    <!-- 任务内容 -->
    <div v-show="visible('content')" class="form-row">
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

    <TaskAttachmentFields v-show="visible('options')" :ws-id="wsId" :is-diagnosis-task="isDiagnosisTask" :creating="creating"
      v-model:requirement-duration="requirementDuration" v-model:priority="priority" v-model:spec-file="specFile" v-model:diagnosis-files="diagnosisFiles" />

    <!-- 初始化提示词 / 现象描述 -->
    <div v-show="visible('content')" class="form-row">
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

    <!-- 自动执行全流程主开关（仅问题定位任务） -->
    <div v-if="isDiagnosisTask" v-show="visible('options')" class="form-row">
      <label class="auto-run-switch" title="开启后，SOP 阶段确认通过即由服务端自动衔接下一阶段，无需逐步确认；证据不足或执行失败时暂停。">
        <ToggleSwitch v-model="sopAutoRun" aria-label="自动执行全流程" />
        <span class="auto-run-title">自动执行全流程</span>
        <span class="auto-run-hint">阶段确认通过后自动推进下一阶段，无需逐步确认</span>
      </label>
    </div>

    <!-- 诊断规程入口（仅问题定位任务；研发态不可选诊断规程） -->
    <div v-if="isDiagnosisTask" v-show="visible('options')" class="form-meta-container">
      <button type="button" class="meta-skills-bar skills-entry-card playbook-entry-card"
        :class="{ active: activeSidebar === 'playbooks', 'has-selection': !!selectedPlaybook }"
        :disabled="creating" @click="emit('toggle-sidebar', 'playbooks')">
        <span class="skills-bar-left"><span class="skills-bar-icon-box"><BookOpen class="w-3.5 h-3.5 text-primary" /></span>
          <span class="skills-bar-title">诊断规程</span>
          <span class="skills-bar-badge" :class="{ 'has-selected': !!selectedPlaybook }">{{ selectedPlaybook ? '已选 1 项' : '可选' }}</span>
        </span>
        <span class="skills-bar-right"><span class="skills-bar-action-text">{{ selectedPlaybook?.title || '推荐并选择' }}</span>
          <ChevronRight class="w-3.5 h-3.5 chevron-icon" :class="{ open: activeSidebar === 'playbooks' }" />
        </span>
      </button>
    </div>

    <!-- 行 4：Worktree 仓库载入触发条（整行可点击展开右侧仓库树） -->
    <label v-if="!isDiagnosisTask && isDesktop() && execution.location === 'SERVER' && reposTotal > 0" v-show="visible('environment')" class="collaboration-intent"><input v-model="localCollaborationIntent" type="checkbox" :disabled="creating" />{{ $t('collaboration.createIntent') }}<small>{{ $t('collaboration.createIntentHint') }}</small></label>
    <div v-if="reposTotal > 0" v-show="visible('environment')" class="form-meta-container">
      <button type="button" :disabled="creating"
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
      </button>
    </div>

    <p v-if="visible('environment') && reposLoading" class="guide-notice" role="status">{{ $t('task_create.repos_loading') }}</p>
    <p v-else-if="visible('environment') && reposError" class="guide-error" role="alert">{{ $t('task_create.repos_error') }} <button type="button" @click="emit('retry-repos')">{{ $t('task_rail.retry') }}</button></p>
    <p v-else-if="guided && step === 'environment' && reposTotal === 0" class="guide-notice">{{ $t('task_create.no_repos') }}</p>

    <!-- Skills -->
    <div v-show="visible('options')" class="form-meta-container">
      <button type="button" :disabled="creating"
        class="meta-skills-bar skills-entry-card skill-picker-entry-card"
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
      </button>
    </div>

    </fieldset>
    <TaskCreateReview v-if="guided && step === 'review'" :draft="snapshot" :model-label="modelLabel" :execution-label="executionLabel"
      :requirement-title="selectedRequirement?.title" :repos="repoReview || []" :skill-names="selectedSkillNames || []"
      :show-local-collaboration="isDesktop() && reposTotal > 0"
      :skill-count="selectedSkillCount" :playbook-title="selectedPlaybook?.title" :disabled="creating" @edit="goTo" />
    </div>
    <div class="modal-footer">
      <div class="footer-left-hint">
        <span v-if="!guided && selectedSkillCount > 0" class="footer-skills-hint">
          <Sparkles class="w-3.5 h-3.5 text-primary" />{{ $t('skills.task_panel.selected_count', { count: selectedSkillCount }) }}
        </span>
        <button v-if="guided && step !== 'content'" type="button" class="btn-secondary modal-btn" :disabled="creating" @click="goTo(steps[steps.indexOf(step) - 1]!)">{{ $t('task_create.previous') }}</button>
      </div>
      <div class="footer-actions">
        <button type="button" class="btn-secondary modal-btn" :disabled="creating" @click="emit('cancel')">{{ $t('common.cancel') }}</button>
        <button v-if="guided && step !== 'review'" type="submit" class="btn-primary modal-btn guide-next" :disabled="creating">
          {{ step === 'options' ? $t('task_create.review_action') : $t('task_create.next') }}<ChevronRight class="w-4 h-4" />
        </button>
        <button v-else type="submit" class="btn-primary modal-btn" :disabled="creating || reposLoading || reposError || (!isDiagnosisTask && (requirementLoading || requirementError || (requirementRequired && !selectedRequirement)))">
          <Loader2 v-if="creating" class="w-4 h-4 spin" />
          <span>{{ creating ? $t('common.loading') : guided ? $t('task_create.create') : $t('chat.initialize') }}</span>
        </button>
      </div>
    </div>
  </form>
</template>
<style scoped src="@/styles/task-create/task-create-shared.css"></style>
<style scoped src="@/styles/task-create/task-create-form.css"></style>
