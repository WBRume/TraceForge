import { computed, shallowRef, watch } from 'vue'
import { useAgentModels } from '@/composables/useAgentModels'
import type { TaskExecution } from '@/composables/useLocalResources'
import type { TaskCreateFormProps, TaskDraftSnapshot } from '../types'

/** Shared draft for quick and guided creation; switching presentation never remounts it. */
export function useTaskCreateDraft(props: TaskCreateFormProps, onPlaybookContext: (context: { name: string; description: string }) => void) {
  const isDiagnosisTask = computed(() => props.taskType === 'DIAGNOSIS')

  // ── 草稿字段 ──
  const execution = shallowRef<TaskExecution>({ location: 'SERVER' })
  const localCollaborationIntent = shallowRef(false)
  const models = useAgentModels(() => ({
    workspaceId: props.wsId,
    resourceId: execution.value.location === 'LOCAL' ? execution.value.resource_id : undefined,
    resourceRevision: execution.value.profile_revision,
  }))
  const name = shallowRef('')
  const description = shallowRef('')
  const phenomenon = shallowRef('')
  const priority = shallowRef('P2')
  const sopAutoRun = shallowRef(false)
  const requirementDuration = shallowRef<number | string>(8)
  watch(() => [name.value, description.value, phenomenon.value, props.taskType], () => {
    onPlaybookContext({ name: name.value, description: isDiagnosisTask.value ? phenomenon.value : description.value })
  }, { immediate: true })

  // ── 附件：研发态规范文档（单文件）/ 诊断态文档（多文件，类型不限） ──
  const specFile = shallowRef<File | null>(null)
  const diagnosisFiles = shallowRef<File[]>([])
  let inheritedName = ''
  let inheritedPrompt = ''
  let inheritedFile: File | null = null
  watch(() => props.requirementContext, (requirement) => {
    const nextName = requirement?.title || ''
    const rawPrompt = requirement?.task_prompt ?? requirement?.source_metadata?.task_prompt
    const nextPrompt = typeof rawPrompt === 'string' && rawPrompt.trim() ? rawPrompt : requirement?.body || ''
    if (!name.value || name.value === inheritedName) name.value = nextName
    if (!description.value || description.value === inheritedPrompt) description.value = nextPrompt
    if (!phenomenon.value || phenomenon.value === inheritedPrompt) phenomenon.value = nextPrompt
    const document = requirement ? [requirement.body?.trim(), requirement.acceptance_criteria.length
      ? `## 验收标准\n${requirement.acceptance_criteria.map((criterion) => `- ${criterion}`).join('\n')}` : ''].filter(Boolean).join('\n\n') : ''
    const nextFile = document ? new File([document], `${nextName.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 100) || '需求规范'}.md`, { type: 'text/markdown' }) : null
    if (!specFile.value || specFile.value === inheritedFile) specFile.value = nextFile
    diagnosisFiles.value = diagnosisFiles.value.filter((file) => file !== inheritedFile)
    if (nextFile) diagnosisFiles.value = [nextFile, ...diagnosisFiles.value]
    inheritedName = nextName
    inheritedPrompt = nextPrompt
    inheritedFile = nextFile
  }, { immediate: true })

  const snapshot = computed<TaskDraftSnapshot>(() => ({
      taskType: props.taskType,
      execution: execution.value,
      ...(!isDiagnosisTask.value && execution.value.location === 'SERVER' && localCollaborationIntent.value ? { enableLocalCollaboration: true } : {}),
      agentModel: models.selection.value,
      name: name.value,
      requirementId: isDiagnosisTask.value ? undefined : props.selectedRequirement?.id,
      description: description.value,
      phenomenon: phenomenon.value,
      priority: priority.value,
      sopAutoRun: sopAutoRun.value,
      requirementDurationHours: Number(requirementDuration.value),
      specFile: isDiagnosisTask.value ? null : specFile.value,
      diagnosisFiles: isDiagnosisTask.value ? [...diagnosisFiles.value] : [],
      diagnosisPlaybookSpecId: props.selectedPlaybook?.id,
  }))

  /** 清空草稿（创建成功后由对话框调用） */
  const reset = () => {
    name.value = ''
    description.value = ''
    phenomenon.value = ''
    priority.value = 'P2'
    sopAutoRun.value = false
    localCollaborationIntent.value = false
    requirementDuration.value = 8
    specFile.value = null
    diagnosisFiles.value = []
  }

  return { isDiagnosisTask, execution, localCollaborationIntent, models, name, description,
    phenomenon, priority, sopAutoRun, requirementDuration, specFile, diagnosisFiles, snapshot, reset }
}
