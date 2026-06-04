import { computed, ref, type Ref } from 'vue'
import type { SkillDimension, SkillMetaSnapshot } from './skillEditorTypes'

type TranslateFn = (key: string, params?: Record<string, unknown>) => string

type WorkspaceOption = { id: string, name: string }

type UseSkillEditorMetaFormOptions = {
  t: TranslateFn
  selectedWorkspaceId: Ref<string>
  workspaceSource: Ref<WorkspaceOption[]>
  isEdit: Ref<boolean> | { value: boolean }
}

export function useSkillEditorMetaForm(options: UseSkillEditorMetaFormOptions) {
  const {
    t,
    selectedWorkspaceId,
    workspaceSource,
    isEdit,
  } = options

  const form = ref({
    sourceMode: 'manual' as 'manual' | 'github',
    name: '',
    description: '',
    dimension: 'WORKSPACE' as SkillDimension,
    workspaceId: selectedWorkspaceId.value || '',
    entryFilePath: 'SKILL.md',
    githubRepoUrl: '',
    githubSkillName: '',
    followOfficialSource: false,
  })

  const initialMeta = ref<SkillMetaSnapshot | null>(null)
  const showErrors = ref(false)

  const currentMetaSnapshot = computed<SkillMetaSnapshot>(() => ({
    name: form.value.name.trim(),
    description: form.value.description.trim(),
    dimension: form.value.dimension,
    workspaceId: form.value.dimension === 'WORKSPACE' ? String(form.value.workspaceId || '') : '',
    entryFilePath: form.value.entryFilePath.trim() || 'SKILL.md',
  }))

  const hasMetadataChanges = computed(() => {
    if (!isEdit.value || !initialMeta.value) return false
    const current = currentMetaSnapshot.value
    const baseline = initialMeta.value
    return (
      current.name !== baseline.name
      || current.description !== baseline.description
      || current.dimension !== baseline.dimension
      || current.workspaceId !== baseline.workspaceId
      || current.entryFilePath !== baseline.entryFilePath
    )
  })

  const formErrors = computed(() => {
    if (!showErrors.value) return {}
    const errors: Record<string, boolean> = {}
    if (form.value.sourceMode === 'github') {
      if (!form.value.githubRepoUrl.trim()) errors.githubRepoUrl = true
      if (!form.value.githubSkillName.trim()) errors.githubSkillName = true
    } else if (!form.value.name.trim()) {
      errors.name = true
    }
    if (form.value.dimension === 'WORKSPACE' && !form.value.workspaceId) errors.workspaceId = true
    return errors
  })

  const isValid = computed(() => {
    if (form.value.sourceMode === 'github') {
      if (!form.value.githubRepoUrl.trim()) return false
      if (!form.value.githubSkillName.trim()) return false
    } else if (!form.value.name.trim()) {
      return false
    }
    if (form.value.dimension === 'WORKSPACE' && !form.value.workspaceId) return false
    return true
  })

  const dimensionOptions = computed(() => [
    { value: 'GLOBAL', label: t('skills.editor.dimension_global') },
    { value: 'WORKSPACE', label: t('skills.editor.dimension_workspace') },
  ])

  const workspaceOptions = computed(() => (
    workspaceSource.value.map(ws => ({ value: ws.id, label: ws.name }))
  ))

  const applyDetailToForm = (detail: {
    name?: string | null
    description?: string | null
    dimension?: string | null
    workspace_id?: string | null
    entry_file_path?: string | null
  }) => {
    form.value = {
      sourceMode: 'manual',
      name: detail.name || '',
      description: detail.description || '',
      dimension: (detail.dimension || 'WORKSPACE') as SkillDimension,
      workspaceId: detail.workspace_id || selectedWorkspaceId.value,
      entryFilePath: detail.entry_file_path || 'SKILL.md',
      githubRepoUrl: '',
      githubSkillName: '',
      followOfficialSource: false,
    }
    initialMeta.value = { ...currentMetaSnapshot.value }
  }

  const resetNewSkillMeta = () => {
    form.value = {
      sourceMode: 'manual',
      name: '',
      description: '',
      dimension: 'WORKSPACE',
      workspaceId: selectedWorkspaceId.value || '',
      entryFilePath: 'SKILL.md',
      githubRepoUrl: '',
      githubSkillName: '',
      followOfficialSource: false,
    }
    initialMeta.value = null
  }

  return {
    form,
    initialMeta,
    showErrors,
    currentMetaSnapshot,
    hasMetadataChanges,
    formErrors,
    isValid,
    dimensionOptions,
    workspaceOptions,
    applyDetailToForm,
    resetNewSkillMeta,
  }
}
