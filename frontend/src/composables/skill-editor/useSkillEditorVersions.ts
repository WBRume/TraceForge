import { computed, reactive, ref, type ComputedRef, type Ref } from 'vue'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type { ContentViewMode, SkillDiffFile, SkillVersion } from './skillEditorTypes'

type TranslateFn = (key: string, params?: Record<string, unknown>) => string

type UseSkillEditorVersionsOptions = {
  t: TranslateFn
  actionError: Ref<string>
  isEdit: ComputedRef<boolean>
  getIsReadOnly: () => boolean
  getHasWriteAccess: () => boolean
  skillId: ComputedRef<string | undefined>
  selectedWorkspaceId: Ref<string>
  viewVersionId: Ref<string>
  compareFromVersionId: Ref<string>
  compareToVersionId: Ref<string>
  contentViewMode: Ref<ContentViewMode>
  expandRightDrawer: (tab: 'history' | 'diff') => void
}

export function useSkillEditorVersions(options: UseSkillEditorVersionsOptions) {
  const {
    t,
    actionError,
    isEdit,
    getIsReadOnly,
    getHasWriteAccess,
    skillId,
    selectedWorkspaceId,
    viewVersionId,
    compareFromVersionId,
    compareToVersionId,
    contentViewMode,
    expandRightDrawer,
  } = options

  const versions = ref<SkillVersion[]>([])
  const versionsLoading = ref(false)
  const diffLoading = ref(false)
  const diffFiles = ref<SkillDiffFile[]>([])
  const activeDiffFilePath = ref('')
  const hasPendingWorktreeChanges = ref(false)
  const pendingChangedFilesCount = ref(0)

  const diffPayload = reactive({
    original: '',
    modified: '',
    fromVersionNo: 0,
    toVersionNo: 0,
    isBinary: false,
    loaded: false,
  })

  const latestVersionId = computed(() => versions.value[0]?.id || '')
  const latestVersionNo = computed(() => versions.value[0]?.version_no || 0)
  const workspaceParams = () => (
    selectedWorkspaceId.value ? { workspace_id: selectedWorkspaceId.value } : {}
  )

  const resolveVersionNo = (versionId: string) => {
    const version = versions.value.find(item => item.id === versionId)
    return version?.version_no || 0
  }

  const loadVersions = async () => {
    if (!isEdit.value || !skillId.value) return
    versionsLoading.value = true
    try {
      const res = await api.get(`/skills/${skillId.value}/versions`, {
        params: workspaceParams(),
      })
      versions.value = (res.data.items || []).sort((a: SkillVersion, b: SkillVersion) => b.version_no - a.version_no)
      if (!viewVersionId.value || !versions.value.some(item => item.id === viewVersionId.value)) {
        viewVersionId.value = versions.value[0]?.id || ''
      }
      compareToVersionId.value = compareToVersionId.value || versions.value[0]?.id || ''
      compareFromVersionId.value = compareFromVersionId.value || versions.value[1]?.id || versions.value[0]?.id || ''
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.version_load_failed'), t)
    } finally {
      versionsLoading.value = false
    }
  }

  const loadPublishStatus = async () => {
    if (!isEdit.value || !skillId.value) return
    try {
      const res = await api.get(`/skills/${skillId.value}/versions/pending`, {
        params: workspaceParams(),
      })
      hasPendingWorktreeChanges.value = Boolean(res.data?.has_pending_changes)
      pendingChangedFilesCount.value = Number(res.data?.changed_files_count || 0)
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.version_load_failed'), t)
    }
  }

  const loadFileDiff = async (path: string) => {
    if (!isEdit.value || !skillId.value) return
    if (!compareFromVersionId.value || !compareToVersionId.value) return

    try {
      const res = await api.get(`/skills/${skillId.value}/versions/compare/file`, {
        params: {
          ...workspaceParams(),
          from_version_id: compareFromVersionId.value,
          to_version_id: compareToVersionId.value,
          path,
        },
      })
      diffPayload.original = res.data.original || ''
      diffPayload.modified = res.data.modified || ''
      diffPayload.isBinary = Boolean(res.data.is_binary)
      diffPayload.fromVersionNo = resolveVersionNo(compareFromVersionId.value)
      diffPayload.toVersionNo = resolveVersionNo(compareToVersionId.value)
      diffPayload.loaded = true

      if (getIsReadOnly() || !getHasWriteAccess()) {
        contentViewMode.value = 'diff'
      }
      activeDiffFilePath.value = path
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.diff_failed'), t)
    }
  }

  const loadDirectoryDiff = async () => {
    if (!isEdit.value || !skillId.value) return
    if (!compareFromVersionId.value || !compareToVersionId.value) return

    diffLoading.value = true
    try {
      const res = await api.get(`/skills/${skillId.value}/versions/compare`, {
        params: {
          ...workspaceParams(),
          from_version_id: compareFromVersionId.value,
          to_version_id: compareToVersionId.value,
        },
      })
      diffFiles.value = res.data.files || []
      activeDiffFilePath.value = diffFiles.value[0]?.path || ''
      if (activeDiffFilePath.value) {
        await loadFileDiff(activeDiffFilePath.value)
      }

      if (getIsReadOnly()) {
        contentViewMode.value = 'diff'
      } else if (getHasWriteAccess()) {
        expandRightDrawer('diff')
      } else {
        contentViewMode.value = 'diff'
      }
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.diff_failed'), t)
    } finally {
      diffLoading.value = false
    }
  }

  return {
    versions,
    versionsLoading,
    diffLoading,
    diffFiles,
    activeDiffFilePath,
    diffPayload,
    hasPendingWorktreeChanges,
    pendingChangedFilesCount,
    latestVersionId,
    latestVersionNo,
    resolveVersionNo,
    loadVersions,
    loadPublishStatus,
    loadFileDiff,
    loadDirectoryDiff,
  }
}
