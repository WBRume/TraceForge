<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TaskCreateRepoReview, TaskCreateStep, TaskDraftSnapshot } from './types'

const props = defineProps<{
  draft: TaskDraftSnapshot
  modelLabel: string
  executionLabel?: string
  requirementTitle?: string
  repos: TaskCreateRepoReview[]
  skillNames: string[]
  skillCount: number
  playbookTitle?: string
  disabled: boolean
  showLocalCollaboration?: boolean
}>()
const emit = defineEmits<{ edit: [step: TaskCreateStep] }>()
const { t } = useI18n()
const groups = computed(() => {
  const diagnosis = props.draft.taskType === 'DIAGNOSIS'
  const empty = t('task_create.not_added')
  return [
    { step: 'content' as const, rows: [
      { label: t('task_create.task_type'), value: t(diagnosis ? 'task_types.diagnosis' : 'task_types.development') },
      { label: t('dashboard.task_name'), value: props.draft.name },
      ...(!diagnosis ? [{ label: t('task_rail.requirement_optional'), value: props.requirementTitle || t('task_create.independent') }] : []),
      { label: t(diagnosis ? 'diagnosis.phenomenon' : 'dashboard.description'), value: (diagnosis ? props.draft.phenomenon : props.draft.description) || empty },
    ] },
    { step: 'environment' as const, rows: [
      { label: t('task_create.execution'), value: props.draft.execution?.location === 'LOCAL' ? `${t('task_create.local')}${props.executionLabel ? ` · ${props.executionLabel}` : ''}` : t('task_create.server') },
      { label: t('task_create.model'), value: props.modelLabel },
      { label: t('task_create.repositories'), value: props.repos.map(repo => `${repo.name} · ${repo.branch}`).join('\n') || t('task_create.no_repos') },
      ...(!diagnosis && props.showLocalCollaboration && props.draft.execution?.location !== 'LOCAL' ? [{ label: t('collaboration.createIntent'), value: t(props.draft.enableLocalCollaboration ? 'task_create.enabled' : 'task_create.disabled') }] : []),
    ] },
    { step: 'options' as const, rows: [
      { label: t(diagnosis ? 'diagnosis.priority' : 'dashboard.requirement_duration'), value: diagnosis ? props.draft.priority : `${props.draft.requirementDurationHours} h` },
      { label: t(diagnosis ? 'diagnosis.docs_upload_label' : 'dashboard.spec_doc'), value: (diagnosis ? props.draft.diagnosisFiles.map(file => file.name).join('\n') : props.draft.specFile?.name) || empty },
      { label: 'Skills', value: props.skillCount ? props.skillNames.join('\n') || t('skills.task_panel.selected_count', { count: props.skillCount }) : empty },
      ...(diagnosis ? [
        { label: t('task_create.playbook'), value: props.playbookTitle || empty },
        { label: t('task_create.auto_run'), value: t(props.draft.sopAutoRun ? 'task_create.enabled' : 'task_create.disabled') },
      ] : []),
    ] },
  ]
})
</script>

<template>
  <div class="create-review">
    <section v-for="group in groups" :key="group.step" class="review-group">
      <header class="review-heading">
        <h4>{{ $t(`task_create.steps.${group.step}.title`) }}</h4>
        <button type="button" class="review-edit" :disabled="disabled" :aria-label="$t('task_create.edit_section', { section: $t(`task_create.steps.${group.step}.title`) })" @click="emit('edit', group.step)">{{ $t('task_create.edit') }}</button>
      </header>
      <dl class="review-rows">
        <div v-for="row in group.rows" :key="row.label" class="review-row">
          <dt>{{ row.label }}</dt>
          <dd>{{ row.value }}</dd>
        </div>
      </dl>
    </section>
  </div>
</template>

<style scoped>
.create-review { display: flex; flex-direction: column; gap: 20px; }
.review-group + .review-group { border-top: 1px solid #e2e8f0; padding-top: 16px; }
.review-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.review-heading h4 { margin: 0; color: #0f172a; font-size: 13px; }
.review-edit { border: 0; padding: 3px 6px; background: transparent; color: #0369a1; cursor: pointer; font-size: 12px; }
.review-rows { margin: 0; display: grid; gap: 10px; }
.review-row { display: grid; grid-template-columns: minmax(0, 120px) minmax(0, 1fr); gap: 14px; font-size: 12px; line-height: 1.6; }
.review-row dt { color: #64748b; }
.review-row dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: #1e293b; }
@media (max-width: 420px) { .review-row { grid-template-columns: minmax(0, 90px) minmax(0, 1fr); gap: 8px; } }
</style>
