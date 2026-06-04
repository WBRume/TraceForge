import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type * as Monaco from 'monaco-editor'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { ensureMonacoViteSetup } from '@/utils/monaco'
import { resolveSkillFileLanguage } from '@/utils/skillLanguage'
import { REVIEWER_COLOR_PALETTE, hashToInt, reviewerColor, reviewerColorIndex } from '@/utils/skillReview'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAuthStore } from '@/stores/auth'
import { useSkillEditorMetaForm } from '@/composables/skill-editor/useSkillEditorMetaForm'
import { useSkillEditorFiles } from '@/composables/skill-editor/useSkillEditorFiles'
import { useSkillEditorRightDrawer } from '@/composables/skill-editor/useSkillEditorRightDrawer'
import { useSkillEditorVersions } from '@/composables/skill-editor/useSkillEditorVersions'
import { useSkillEditorReview } from '@/composables/skill-editor/useSkillEditorReview'
import { useSkillEditorMonaco } from '@/composables/skill-editor/useSkillEditorMonaco'
import { useSkillAnalysis } from '@/composables/skill-editor/useSkillAnalysis'
import { waitForSkillImportJob } from '@/composables/skills/skillGithubImportJob'
import type {
  ContentViewMode,
  SelectionRange,
  SkillNodeType,
} from '@/composables/skill-editor/skillEditorTypes'

export type {
  ContentViewMode,
  SelectionRange,
  SkillComment,
  SkillDiffFile,
  SkillDimension,
  SkillFileNode,
  SkillRatingItem,
  SkillReviewOverview,
  SkillVersion,
} from '@/composables/skill-editor/skillEditorTypes'

export type SkillEditorMainTab = 'files' | 'analysis'

export function useSkillEditorViewModel() {
  ensureMonacoViteSetup()

  const route = useRoute()
  const router = useRouter()
  const wsStore = useWorkspaceStore()
  const authStore = useAuthStore()
  const { t, locale } = useI18n()

  const skillId = computed(() => route.params.skillId as string | undefined)
  const isEdit = computed(() => !!skillId.value)
  const forcedReadOnly = computed(() => route.query.readonly === '1')
  const activeEditorTab = computed<SkillEditorMainTab>(() => {
    const routeName = String(route.name || '')
    return isEdit.value && (
      routeName === 'skillsEditAnalysis'
      || routeName === 'skillsEditAnalysisRisk'
      || route.path.includes('/analysis')
    )
      ? 'analysis'
      : 'files'
  })
  const isAnalysisTabActive = computed(() => activeEditorTab.value === 'analysis')
  const activeAnalysisRiskKey = computed(() => {
    const value = route.params.riskKey
    return typeof value === 'string' ? value : ''
  })

  const selectedWorkspaceId = ref((route.query.wsId as string) || '')

  const normalizeWorkspaceId = (value: unknown) => String(value || '').trim()

  const workspaceParams = () => (
    selectedWorkspaceId.value ? { workspace_id: selectedWorkspaceId.value } : {}
  )

  const syncSelectedWorkspaceScope = (workspaceId: unknown) => {
    const nextWorkspaceId = normalizeWorkspaceId(workspaceId)
    if (selectedWorkspaceId.value !== nextWorkspaceId) {
      selectedWorkspaceId.value = nextWorkspaceId
    }
  }

  const loading = ref(false)
  const saving = ref(false)
  const publishing = ref(false)
  const restoring = ref(false)
  const actionError = ref('')

  const canManage = ref(true)
  const sourceType = ref<string | null>(null)
  const sourceRepoUrl = ref('')
  const sourceSkillName = ref('')
  const sourceSubdir = ref('')
  const sourceLocked = ref(false)
  const sourceCommitSha = ref('')
  const sourceLastSyncedAt = ref<string | null>(null)
  const sourceSyncing = ref(false)
  const showSwitchToEditConfirm = ref(false)
  const showRestoreConfirm = ref(false)
  const showPublishConfirm = ref(false)
  const pendingPublishNote = ref('')

  const metaForm = useSkillEditorMetaForm({
    t,
    selectedWorkspaceId,
    workspaceSource: computed(() => wsStore.workspaces as Array<{ id: string, name: string }>),
    isEdit,
  })
  const {
    form,
    showErrors,
    hasMetadataChanges,
    formErrors,
    isValid,
    dimensionOptions,
    workspaceOptions,
    applyDetailToForm,
    resetNewSkillMeta,
  } = metaForm

  const savedSkillWorkspaceScope = (payload: Record<string, unknown> | null | undefined) => {
    const dimension = String(payload?.dimension || form.value.dimension || '').trim()
    if (dimension !== 'WORKSPACE') return ''
    return normalizeWorkspaceId(payload?.workspace_id || form.value.workspaceId)
  }

  const viewVersionId = ref('')
  const compareFromVersionId = ref('')
  const compareToVersionId = ref('')
  const selectedRange = ref<SelectionRange | null>(null)

  const rightDrawer = useSkillEditorRightDrawer({
    t,
    actionError,
    selectedWorkspaceId,
    skillId,
    viewVersionId,
  })
  const {
    isRightDrawerOpen,
    rightDrawerLevel,
    rightDrawerTab,
    drawerFileTree,
    drawerActiveFilePath,
    drawerFileContent,
    drawerIsBinary,
    drawerTreeLoading,
    drawerFileLoading,
    toggleRightDrawer,
    expandRightDrawer,
    toggleDrawerFullWidth,
    openDrawerFile,
  } = rightDrawer

  const contentViewMode = ref<ContentViewMode>('edit')

  const isGithubImportMode = computed(() => form.value.sourceMode === 'github')
  const isOfficialSourceSkill = computed(() => (
    sourceLocked.value && sourceType.value === 'GITHUB_OFFICIAL'
  ))

  const hasWriteAccess = computed(() => {
    if (!isEdit.value) return true
    return canManage.value && !isOfficialSourceSkill.value
  })

  const skillVersions = useSkillEditorVersions({
    t,
    actionError,
    isEdit,
    getIsReadOnly: () => isReadOnly.value,
    getHasWriteAccess: () => hasWriteAccess.value,
    skillId,
    selectedWorkspaceId,
    viewVersionId,
    compareFromVersionId,
    compareToVersionId,
    contentViewMode,
    expandRightDrawer,
  })
  const {
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
  } = skillVersions

  const skillAnalysis = useSkillAnalysis({
    t,
    actionError,
    skillId,
    selectedWorkspaceId,
    hasPendingWorktreeChanges,
    latestVersionId,
    viewVersionId,
  })
  const {
    latestAnalysis,
    analysisLoading,
    analysisRunning,
    analysisError,
    defaultAnalysisRefKind,
    targetAnalysisVersionId,
    loadLatestAnalysis,
    runAnalysis,
    resetAnalysis,
  } = skillAnalysis

  const isViewingHistoricalVersion = computed(() => {
    if (!isEdit.value || versions.value.length === 0) return false
    if (!viewVersionId.value || !latestVersionId.value) return false
    return viewVersionId.value !== latestVersionId.value
  })

  const isReadOnly = computed(() => {
    if (!isEdit.value) return false
    if (isOfficialSourceSkill.value) return true
    if (forcedReadOnly.value) return true
    if (!hasWriteAccess.value) return true
    if (isSidebarLayout.value && isViewingHistoricalVersion.value) return true
    return false
  })

  const isSidebarLayout = computed(() => {
    if (!isEdit.value) return false
    return forcedReadOnly.value || !hasWriteAccess.value
  })

  const currentRef = computed(() => {
    if (!isEdit.value) return 'WORKTREE'
    if (isSidebarLayout.value && isViewingHistoricalVersion.value) return viewVersionId.value
    if (hasWriteAccess.value && !forcedReadOnly.value) return 'WORKTREE'
    return viewVersionId.value || 'WORKTREE'
  })

  const isWorktreeRef = computed(() => {
    const normalized = String(currentRef.value || '').trim().toUpperCase()
    return normalized === 'WORKTREE' || normalized === 'HEAD'
  })

  const skillFiles = useSkillEditorFiles({
    t,
    actionError,
    form,
    isEdit,
    isReadOnly,
    skillId,
    selectedWorkspaceId,
    currentRef,
    isWorktreeRef,
    onBeforeOpenFile: () => {
      clearSelectedRange()
      closeAvatarPopover()
      setActiveComment(null)
    },
    onAfterOpenFile: async () => {
      await loadComments()
    },
    onAfterRemoteMutation: async () => {
      await loadPublishStatus()
    },
  })
  const {
    fileTree,
    activeFilePath,
    selectedTreePath,
    fileContents,
    binaryFileMap,
    dirtyFiles,
    loadingFile,
    treeLoading,
    hasDirtyFiles,
    activeFileContent,
    showCreateNodeModal,
    creatingNode,
    showRenameNodeModal,
    renamingNode,
    showDeleteNodeConfirm,
    deletingNode,
    createNodeType,
    createNodeParentPath,
    createNodeName,
    renameNodeSourcePath,
    renameNodeType,
    renameNodeName,
    deleteNodePath,
    deleteNodeType,
    directoryOptions,
    createNodeDialogTitle,
    createNodeNamePlaceholder,
    canOperateSelectedNode,
    renameNodeDialogTitle,
    renameNodeNamePlaceholder,
    selectTreeNode: selectTreeNodeInner,
    loadFileTree,
    openFile,
    resetFilesForNewSkill,
    persistDirtyFiles,
    buildInitialEntriesForCreate,
    createNode,
    cancelCreateNode,
    confirmCreateNode,
    openRenameNodeDialog,
    cancelRenameNode,
    confirmRenameNode,
    openDeleteNodeConfirm,
    cancelDeleteNode,
    confirmDeleteNode,
  } = skillFiles

  watch(currentRef, async () => {
    if (isEdit.value) {
      if (!isAnalysisTabActive.value) {
        await loadFileTree()
      }
      if (isWorktreeRef.value) {
        await Promise.all([loadReviewOverview(), loadPublishStatus()])
      }
    }
  })

  const canSwitchToEdit = computed(() => (
    isEdit.value && isReadOnly.value && canManage.value && !isOfficialSourceSkill.value && !isViewingHistoricalVersion.value
  ))

  const isDiffMode = computed(() => contentViewMode.value === 'diff')

  const skillReview = useSkillEditorReview({
    t,
    actionError,
    isEdit,
    isReadOnly,
    isDiffMode,
    isViewingHistoricalVersion,
    skillId,
    selectedWorkspaceId,
    activeFilePath,
    currentRef,
    isWorktreeRef,
    latestVersionId,
    selectedRange,
  })
  const {
    reviewOverview,
    ratingForm,
    ratingNotes,
    comments,
    commentBody,
    ratingSaving,
    ratingNotesLoading,
    showRatingNotesModal,
    showRatingNoteError,
    commentSaving,
    canReview,
    canLineReview,
    canSubmitComment,
    applyDetailReviewState,
    resetForNewSkill,
    loadReviewOverview,
    loadRatingNotes,
    submitRating,
    loadComments,
    submitComment,
  } = skillReview

  const skillMonaco = useSkillEditorMonaco({
    selectedRange,
    comments,
    commentBody,
    canLineReview,
    isDiffMode,
    isReadOnly,
    switchToEditContentView: () => {
      contentViewMode.value = 'edit'
    },
  })
  const {
    AVATAR_RAIL_WIDTH,
    activeCommentId,
    isInlineComposerFocused,
    lineAvatarSlots,
    avatarPopover,
    inlineComposerPosition,
    commentDecorations,
    editorStageRef,
    avatarPopoverRef,
    showLineReviewAvatars,
    popoverLineReviewers,
    activePopoverComments,
    popoverReviewerName,
    popoverReviewerAvatarSvg,
    popoverReviewerColor,
    closeAvatarPopover,
    clearSelectedRange,
    setActiveComment,
    openReviewerPopover,
    switchPopoverReviewer,
    handleEditorStagePointerDown,
    handleDocumentPointerDown,
    handleDocumentPointerUp,
    pickPopoverComment,
    jumpToComment,
    handleEditorMount,
    disposeMonaco,
  } = skillMonaco

  const restoreSourceVersionId = computed(() => (
    viewVersionId.value || latestVersionId.value || ''
  ))

  const canRestoreSelectedVersion = computed(() => (
    isEdit.value
    && canManage.value
    && !isOfficialSourceSkill.value
    && !restoring.value
    && !!restoreSourceVersionId.value
    && !!latestVersionId.value
    && restoreSourceVersionId.value !== latestVersionId.value
  ))

  const pageTitle = computed(() => (
    isEdit.value
      ? (isReadOnly.value ? t('skills.editor.page_title_view') : t('skills.editor.page_title_edit'))
      : t('skills.editor.page_title_new')
  ))

  const readOnlyHintText = computed(() => {
    if (isOfficialSourceSkill.value) {
      return t('skills.editor.official_source_readonly_hint')
    }
    if (isViewingHistoricalVersion.value) {
      return t('skills.editor.historical_readonly_hint', { version: resolveVersionNo(viewVersionId.value) || '-' })
    }
    return canManage.value ? t('skills.editor.read_only_hint_manage') : t('skills.editor.read_only_hint')
  })

  const activeLanguage = computed(() => {
    return resolveSkillFileLanguage(String(activeFilePath.value || ''))
  })

  const drawerActiveLanguage = computed(() => {
    return resolveSkillFileLanguage(String(drawerActiveFilePath.value || activeDiffFilePath.value || ''))
  })

  const canSave = computed(() => {
    if (saving.value || publishing.value || isReadOnly.value) return false
    if (!isEdit.value) return true
    return hasDirtyFiles.value || hasMetadataChanges.value
  })



  const hasPendingPublishChanges = computed(() => (
    hasDirtyFiles.value || hasPendingWorktreeChanges.value
  ))

  const canPublish = computed(() => (
    isEdit.value
    && !isReadOnly.value
    && canManage.value
    && !isOfficialSourceSkill.value
    && !publishing.value
    && hasPendingPublishChanges.value
  ))

  const canSyncOfficialSource = computed(() => (
    isEdit.value
    && canManage.value
    && isOfficialSourceSkill.value
    && !sourceSyncing.value
  ))

  const isUnpublishedSkill = computed(() => (
    isEdit.value && hasPendingPublishChanges.value
  ))

  const versionOptions = computed(() => (
    versions.value.map(v => ({
      value: v.id,
      label: `v${v.version_no} · ${formatDateTime(v.created_at)}`,
    }))
  ))

  const versionSimpleOptions = computed(() => (
    versions.value.map(v => ({
      value: v.id,
      label: `v${v.version_no}`,
    }))
  ))

  const editorOptions = computed<Monaco.editor.IStandaloneEditorConstructionOptions>(() => ({
    automaticLayout: true,
    readOnly: isReadOnly.value,
    wordWrap: 'off',
    minimap: { enabled: false },
    fontSize: 13,
    lineNumbersMinChars: 3,
    scrollBeyondLastLine: false,
    padding: { top: 16, bottom: 16 },
  }))

  const diffEditorOptions = computed<Monaco.editor.IStandaloneDiffEditorConstructionOptions>(() => ({
    automaticLayout: true,
    readOnly: true,
    renderSideBySide: true,
    originalEditable: false,
    minimap: { enabled: false },
    lineNumbersMinChars: 3,
    scrollBeyondLastLine: false,
  }))

  const clearError = () => {
    actionError.value = ''
  }

  const navigateBack = () => {
    router.push({ path: '/skills' })
  }

  const editorTabQuery = () => {
    const query = { ...route.query } as Record<string, string | undefined>
    if (selectedWorkspaceId.value) {
      query.wsId = selectedWorkspaceId.value
    } else {
      delete query.wsId
    }
    return query
  }

  const goEditorFilesTab = async () => {
    if (!skillId.value) return
    await router.push({
      name: 'skillsEdit',
      params: { skillId: skillId.value },
      query: editorTabQuery(),
    })
  }

  const goEditorAnalysisTab = async () => {
    if (!skillId.value) return
    await router.push({
      name: 'skillsEditAnalysis',
      params: { skillId: skillId.value },
      query: editorTabQuery(),
    })
  }

  const goAnalysisRiskDetail = async (riskKey: string) => {
    const normalized = String(riskKey || '').trim()
    if (!skillId.value || !normalized) return
    await router.push({
      name: 'skillsEditAnalysisRisk',
      params: { skillId: skillId.value, riskKey: normalized },
      query: editorTabQuery(),
    })
  }

  const confirmSwitchToEditMode = () => {
    if (!canSwitchToEdit.value) return
    showSwitchToEditConfirm.value = false
    contentViewMode.value = 'edit'
    isRightDrawerOpen.value = true
    const nextQuery = { ...route.query, wsId: selectedWorkspaceId.value || undefined } as Record<string, string | undefined>
    delete nextQuery.readonly
    router.replace({ path: route.path, query: nextQuery })
  }

  const switchToReadOnlyMode = () => {
    if (!isEdit.value || isReadOnly.value) return
    
    if (rightDrawerTab.value === 'diff') {
      rightDrawerTab.value = null
      rightDrawerLevel.value = 1
    }
    contentViewMode.value = 'edit'

    const nextQuery = {
      ...route.query,
      wsId: selectedWorkspaceId.value || undefined,
      readonly: '1',
    } as Record<string, string | undefined>
    router.replace({ path: route.path, query: nextQuery })
  }

  const formatDateTime = (value: string) => new Date(value).toLocaleString(locale.value === 'zh' ? 'zh-CN' : 'en-US')

  const applySourceState = (detail: Record<string, any>) => {
    sourceType.value = detail.source_type || null
    sourceRepoUrl.value = detail.source_repo_url || ''
    sourceSkillName.value = detail.source_skill_name || ''
    sourceSubdir.value = detail.source_subdir || ''
    sourceLocked.value = Boolean(detail.source_locked)
    sourceCommitSha.value = detail.source_commit_sha || ''
    sourceLastSyncedAt.value = detail.source_last_synced_at || null
  }

  const resetSourceState = () => {
    sourceType.value = null
    sourceRepoUrl.value = ''
    sourceSkillName.value = ''
    sourceSubdir.value = ''
    sourceLocked.value = false
    sourceCommitSha.value = ''
    sourceLastSyncedAt.value = null
    sourceSyncing.value = false
  }

  const loadSkillDetail = async () => {
    if (!isEdit.value || !skillId.value) return
    loading.value = true
    showErrors.value = false
    clearError()
    try {
      const res = await api.get(`/skills/${skillId.value}`, {
        params: workspaceParams(),
      })
      canManage.value = Boolean(res.data.can_manage)
      applyDetailToForm(res.data)
      applySourceState(res.data)
      applyDetailReviewState(res.data)
      contentViewMode.value = 'edit'
      if (!isReadOnly.value && canManage.value) {
        isRightDrawerOpen.value = true
      }
      clearSelectedRange()
      closeAvatarPopover()
      setActiveComment(null)
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.load_failed'), t)
    } finally {
      loading.value = false
    }
  }

  const resetNewSkillEditor = () => {
    resetNewSkillMeta()
    if (route.query.source === 'github') {
      form.value.sourceMode = 'github'
    }
    resetSourceState()
    resetFilesForNewSkill()
    showErrors.value = false
    resetForNewSkill()
    resetAnalysis()
    clearSelectedRange()
    closeAvatarPopover()
    setActiveComment(null)
  }

  const performSaveSkill = async () => {
    showErrors.value = true
    if (!isValid.value) return
    if (!canSave.value) return

    saving.value = true
    clearError()

    try {
      if (!isEdit.value) {
        if (isGithubImportMode.value) {
          const importWorkspaceId = form.value.dimension === 'WORKSPACE' ? form.value.workspaceId : ''
          const imported = await api.post('/skills/import/github', {
            dimension: form.value.dimension,
            workspace_id: importWorkspaceId || null,
            repo_url: form.value.githubRepoUrl.trim(),
            skill_name: form.value.githubSkillName.trim(),
            description: form.value.description.trim() || null,
            follow_official_source: Boolean(form.value.followOfficialSource),
          }, {
            params: importWorkspaceId ? { workspace_id: importWorkspaceId } : {},
          })
          const importedSkillId = String(imported?.data?.id || '').trim()
          if (importedSkillId) {
            await router.replace({
              name: 'skillsEdit',
              params: { skillId: importedSkillId },
              query: {
                ...(importWorkspaceId ? { wsId: importWorkspaceId } : {}),
                ...(form.value.followOfficialSource ? { readonly: '1' } : {}),
              },
            })
            return
          }
          const importJobId = String(imported?.data?.job_id || '').trim()
          if (importJobId) {
            ElMessage.info(t('skills.editor.import_queued', 'Skill import queued'))
            const result = await waitForSkillImportJob(importJobId)
            if (result.state === 'success') {
              await router.replace({
                name: 'skillsEdit',
                params: { skillId: result.skillId },
                query: {
                  ...(importWorkspaceId ? { wsId: importWorkspaceId } : {}),
                  ...(form.value.followOfficialSource ? { readonly: '1' } : {}),
                },
              })
              return
            }
            if (result.state === 'failed') {
              throw new Error(result.message)
            }
            ElMessage.info(t('skills.editor.import_still_running', 'Import is still running in the background. Opening queue status.'))
            await router.replace({ name: 'opsQueueDetail', params: { source: 'provision', jobId: importJobId } })
            return
          }
          navigateBack()
          return
        }

        const entryPath = form.value.entryFilePath || 'SKILL.md'
        const createWorkspaceId = form.value.dimension === 'WORKSPACE' ? form.value.workspaceId : ''
        const created = await api.post('/skills', {
          name: form.value.name.trim(),
          description: form.value.description.trim() || null,
          dimension: form.value.dimension,
          workspace_id: createWorkspaceId || null,
          entry_file_path: entryPath,
          entry_content: fileContents[entryPath] || '',
          initial_entries: buildInitialEntriesForCreate(),
        }, {
          params: createWorkspaceId ? { workspace_id: createWorkspaceId } : {},
        })
        const createdSkillId = String(created?.data?.id || '').trim()
        if (createdSkillId) {
          await router.replace({
            name: 'skillsEdit',
            params: { skillId: createdSkillId },
            query: createWorkspaceId ? { wsId: createWorkspaceId } : {},
          })
          return
        }
        navigateBack()
        return
      }

      if (!skillId.value) return

      if (hasMetadataChanges.value) {
        const updated = await api.patch(`/skills/${skillId.value}`, {
          name: form.value.name.trim(),
          description: form.value.description.trim() || null,
          dimension: form.value.dimension,
          workspace_id: form.value.dimension === 'WORKSPACE' ? form.value.workspaceId : null,
          entry_file_path: form.value.entryFilePath,
        }, {
          params: workspaceParams(),
        })
        syncSelectedWorkspaceScope(savedSkillWorkspaceScope(updated?.data || null))
      }

      const hasChanges = dirtyFiles.value.length > 0
      if (hasChanges) {
        await persistDirtyFiles()
      }

      await Promise.all([loadSkillDetail(), loadReviewOverview(), loadPublishStatus()])
      contentViewMode.value = 'edit'
      diffPayload.loaded = false
      if (!isAnalysisTabActive.value) {
        await loadFileTree()
      }
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.save_failed'), t)
    } finally {
      saving.value = false
    }
  }

  const saveSkill = async () => {
    if (!canSave.value) return
    await performSaveSkill()
  }

  const openPublishConfirm = () => {
    if (!canPublish.value) return
    pendingPublishNote.value = ''
    showPublishConfirm.value = true
  }

  const cancelPublishConfirm = () => {
    if (publishing.value) return
    showPublishConfirm.value = false
    pendingPublishNote.value = ''
  }

  const confirmPublish = async () => {
    if (!isEdit.value || !skillId.value || !canPublish.value) return
    publishing.value = true
    clearError()
    try {
      if (dirtyFiles.value.length > 0) {
        await persistDirtyFiles()
      }
      await api.post(`/skills/${skillId.value}/versions/commit`, {
        change_note: pendingPublishNote.value.trim() || null,
      }, {
        params: workspaceParams(),
      })
      showPublishConfirm.value = false
      pendingPublishNote.value = ''
      await Promise.all([loadSkillDetail(), loadVersions(), loadReviewOverview(), loadPublishStatus()])
      viewVersionId.value = latestVersionId.value
      contentViewMode.value = 'edit'
      diffPayload.loaded = false
      clearSelectedRange()
      closeAvatarPopover()
      setActiveComment(null)
      if (!isAnalysisTabActive.value) {
        await loadFileTree()
        await loadComments()
      }
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.publish_failed'), t)
    } finally {
      publishing.value = false
    }
  }

  const switchToEditContentView = () => {
    contentViewMode.value = 'edit'
  }

  const confirmRestoreVersion = async () => {
    if (!isEdit.value || !skillId.value || !canRestoreSelectedVersion.value) return

    restoring.value = true
    try {
      await api.post(
        `/skills/${skillId.value}/versions/${restoreSourceVersionId.value}/restore`,
        {},
        { params: workspaceParams() },
      )
      showRestoreConfirm.value = false
      contentViewMode.value = 'edit'
      diffPayload.loaded = false
      clearSelectedRange()
      closeAvatarPopover()
      setActiveComment(null)
      await Promise.all([loadSkillDetail(), loadVersions(), loadReviewOverview(), loadPublishStatus()])
      viewVersionId.value = latestVersionId.value
      if (!isAnalysisTabActive.value) {
        await loadFileTree()
        await loadComments()
      }
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.restore_failed'), t)
    } finally {
      restoring.value = false
    }
  }

  const syncOfficialSource = async () => {
    if (!isEdit.value || !skillId.value || !canSyncOfficialSource.value) return

    const beforeVersionNo = Number(latestVersionNo.value || 0)
    sourceSyncing.value = true
    clearError()
    try {
      const res = await api.post(
        `/skills/${skillId.value}/source/sync`,
        {},
        { params: workspaceParams() },
      )
      applySourceState(res.data || {})
      await Promise.all([loadSkillDetail(), loadVersions(), loadReviewOverview(), loadPublishStatus()])
      const afterVersionNo = Number(latestVersionNo.value || 0)
      ElMessage.success(t(
        afterVersionNo > beforeVersionNo
          ? 'skills.editor.sync_official_source_success'
          : 'skills.editor.sync_official_source_no_changes',
      ))
      viewVersionId.value = latestVersionId.value
      contentViewMode.value = 'edit'
      diffPayload.loaded = false
      clearSelectedRange()
      closeAvatarPopover()
      setActiveComment(null)
      if (!isAnalysisTabActive.value) {
        await loadFileTree()
        await loadComments()
      }
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.sync_official_source_failed'), t)
    } finally {
      sourceSyncing.value = false
    }
  }

  const onFileClick = async (path: string) => {
    contentViewMode.value = 'edit'
    diffPayload.loaded = false
    await openFile(path)
  }

  const openAnalysisFile = async (path: string) => {
    const target = String(path || '').trim()
    if (!target) return
    if (isAnalysisTabActive.value) {
      await goEditorFilesTab()
      if (fileTree.value.length === 0) {
        await loadFileTree()
      }
    }
    await onFileClick(target)
  }

  const loadFilesTabData = async () => {
    if (!isEdit.value) return
    await loadFileTree()
    await loadComments()
  }

  const selectTreeNode = async (path: string, nodeType: SkillNodeType) => {
    await selectTreeNodeInner(path, nodeType, onFileClick)
  }

  const onViewVersionChanged = async () => {
    if (!isEdit.value) return
    if (hasWriteAccess.value) {
      if (!viewVersionId.value || viewVersionId.value === latestVersionId.value) {
        rightDrawerTab.value = null
        rightDrawerLevel.value = 1
        return
      }
      drawerTreeLoading.value = true
      try {
        const res = await api.get(`/skills/${skillId.value}/files/tree`, {
          params: { ...workspaceParams(), ref: viewVersionId.value },
        })
        drawerFileTree.value = res.data.nodes || []
        drawerActiveFilePath.value = ''
        drawerFileContent.value = ''
        expandRightDrawer('history')
      } catch (error) {
        actionError.value = formatApiError(error, t('skills.editor.load_failed'), t)
      } finally {
        drawerTreeLoading.value = false
      }
    } else {
      contentViewMode.value = 'edit'
      diffPayload.loaded = false
      if (!isAnalysisTabActive.value) {
        await loadFileTree()
      }
    }
  }

  // Export additional properties for Drawer
  watch(() => actionError.value, (newError) => {
    if (newError) {
      ElMessage.error(newError)
      // Reset after showing so identical consecutive errors can be caught
      actionError.value = ''
    }
  })

  watch(() => selectedWorkspaceId.value, (nextWsId) => {
    const query = { ...route.query } as Record<string, string | undefined>
    if (nextWsId) {
      query.wsId = nextWsId
    } else {
      delete query.wsId
    }
    router.replace({ path: route.path, query })
  })

  watch(() => viewVersionId.value, async (next, prev) => {
    if (!next || next === prev || versionsLoading.value) return
    await onViewVersionChanged()
    if (isAnalysisTabActive.value) {
      await loadLatestAnalysis()
    }
  })

  watch([latestVersionId, hasPendingWorktreeChanges], async ([nextVersion, nextPending], [prevVersion, prevPending]) => {
    if (!isEdit.value || !isAnalysisTabActive.value) return
    if (nextVersion === prevVersion && nextPending === prevPending) return
    await loadLatestAnalysis()
  })

  watch(() => route.query.wsId, async (nextWsId) => {
    const normalized = typeof nextWsId === 'string' ? nextWsId : ''
    if (normalized === selectedWorkspaceId.value) return
    selectedWorkspaceId.value = normalized
  })

  watch(activeEditorTab, async (next, prev) => {
    if (!isEdit.value || next === prev) return
    if (next === 'files') {
      await loadFilesTabData()
    } else {
      await loadLatestAnalysis()
    }
  })

  watch(() => route.params.skillId, async (nextSkillId, prevSkillId) => {
    const next = typeof nextSkillId === 'string' ? nextSkillId : ''
    const prev = typeof prevSkillId === 'string' ? prevSkillId : ''
    if (next === prev) return

    if (!next) {
      resetNewSkillEditor()
      return
    }

    await Promise.all([loadSkillDetail(), loadVersions()])
    await Promise.all([loadReviewOverview(), loadPublishStatus(), loadLatestAnalysis()])
    if (!isAnalysisTabActive.value) {
      await loadFilesTabData()
    }
  })

  onMounted(async () => {
    document.addEventListener('pointerdown', handleDocumentPointerDown)
    document.addEventListener('pointerup', handleDocumentPointerUp)
    await wsStore.fetchWorkspaces()
    if (!authStore.user) await authStore.fetchCurrentUser()

    if (!isEdit.value && (!selectedWorkspaceId.value || !wsStore.workspaces.some(ws => ws.id === selectedWorkspaceId.value)) && wsStore.workspaces.length > 0) {
      selectedWorkspaceId.value = wsStore.workspaces[0].id
    }

    if (!isEdit.value && !form.value.workspaceId && selectedWorkspaceId.value) {
      form.value.workspaceId = selectedWorkspaceId.value
    }

    if (isEdit.value) {
      await Promise.all([loadSkillDetail(), loadVersions()])
      await Promise.all([loadReviewOverview(), loadPublishStatus(), loadLatestAnalysis()])
      if (!isAnalysisTabActive.value) {
        await loadFilesTabData()
      }
    } else {
      resetNewSkillEditor()
    }
  })

  onBeforeUnmount(() => {
    document.removeEventListener('pointerdown', handleDocumentPointerDown)
    document.removeEventListener('pointerup', handleDocumentPointerUp)
    disposeMonaco()
  })

  return {
    AVATAR_RAIL_WIDTH,
    actionError,
    activeEditorTab,
    activeAnalysisRiskKey,
    activePopoverComments,
    activeCommentId,
    activeDiffFilePath,
    activeFileContent,
    activeFilePath,
    activeLanguage,
    analysisError,
    analysisLoading,
    analysisRunning,
    avatarPopover,
    avatarPopoverRef,
    authStore,
    binaryFileMap,
    canManage,
    canReview,
    canLineReview,
    canOperateSelectedNode,
    canPublish,
    canSave,
    canRestoreSelectedVersion,
    canSyncOfficialSource,
    canSubmitComment,
    canSwitchToEdit,
    switchToReadOnlyMode,
    clearSelectedRange,
    closeAvatarPopover,
    clearError,
    commentBody,
    commentDecorations,
    commentSaving,
    comments,
    compareFromVersionId,
    compareToVersionId,
    confirmCreateNode,
    confirmDeleteNode,
    confirmRenameNode,
    confirmRestoreVersion,
    confirmSwitchToEditMode,
    contentViewMode,
    createNodeDialogTitle,
    createNodeName,
    createNodeNamePlaceholder,
    createNodeParentPath,
    createNodeType,
    createNode,
    creatingNode,
    currentRef,
    defaultAnalysisRefKind,
    directoryOptions,
    deleteNodePath,
    deleteNodeType,
    deletingNode,
    diffEditorOptions,
    diffFiles,
    diffLoading,
    diffPayload,
    dimensionOptions,
    dirtyFiles,
    editorOptions,
    editorStageRef,
    form,
    formErrors,
    formatDateTime,
    forcedReadOnly,
    handleDocumentPointerDown,
    handleEditorMount,
    handleEditorStagePointerDown,
    hasDirtyFiles,
    hasPendingPublishChanges,
    hashToInt,
    inlineComposerPosition,
    isDiffMode,
    isEdit,
    isAnalysisTabActive,
    isGithubImportMode,
    isInlineComposerFocused,
    isOfficialSourceSkill,
    isReadOnly,
    isSidebarLayout,
    isUnpublishedSkill,
    isViewingHistoricalVersion,
    lineAvatarSlots,
    latestAnalysis,
    latestVersionId,
    latestVersionNo,
    targetAnalysisVersionId,
    loadReviewOverview,
    loadRatingNotes,
    ratingNotes,
    ratingNotesLoading,
    showRatingNotesModal,
    showRatingNoteError,
    loadDirectoryDiff,
    loadFileDiff,
    loadLatestAnalysis,
    loadPublishStatus,
    loadVersions,
    loading,
    loadingFile,
    locale,
    navigateBack,
    onFileClick,
    openAnalysisFile,
    goEditorAnalysisTab,
    goEditorFilesTab,
    goAnalysisRiskDetail,
    openReviewerPopover,
    openDeleteNodeConfirm,
    openPublishConfirm,
    openRenameNodeDialog,
    openFile,
    pageTitle,
    pendingChangedFilesCount,
    pendingPublishNote,
    pickPopoverComment,
    popoverLineReviewers,
    popoverReviewerAvatarSvg,
    popoverReviewerColor,
    popoverReviewerName,
    ratingForm,
    ratingSaving,
    readOnlyHintText,
    reviewerColor,
    reviewerColorIndex,
    REVIEWER_COLOR_PALETTE,
    renameNodeDialogTitle,
    renameNodeName,
    renameNodeNamePlaceholder,
    renameNodeSourcePath,
    renameNodeType,
    renamingNode,
    resolveVersionNo,
    restoreSourceVersionId,
    restoring,
    reviewOverview,
    route,
    router,
    runAnalysis,
    saveSkill,
    syncOfficialSource,
    confirmPublish,
    cancelCreateNode,
    cancelDeleteNode,
    cancelPublishConfirm,
    cancelRenameNode,
    publishing,
    saving,
    selectedRange,
    selectedTreePath,
    selectedWorkspaceId,
    selectTreeNode,
    showCreateNodeModal,
    showDeleteNodeConfirm,
    showRenameNodeModal,
    showRestoreConfirm,
    showPublishConfirm,
    showLineReviewAvatars,
    showSwitchToEditConfirm,
    skillId,
    sourceCommitSha,
    sourceLastSyncedAt,
    sourceLocked,
    sourceRepoUrl,
    sourceSkillName,
    sourceSubdir,
    sourceSyncing,
    sourceType,
    switchPopoverReviewer,
    submitComment,
    submitRating,
    switchToEditContentView,
    t,
    treeLoading,
    versionOptions,
    versions,
    versionsLoading,
    versionSimpleOptions,
    viewVersionId,
    workspaceOptions,
    wsStore,
    fileTree,
    jumpToComment,
    isRightDrawerOpen,
    rightDrawerLevel,
    rightDrawerTab,
    toggleRightDrawer,
    expandRightDrawer,
    drawerFileTree,
    drawerActiveFilePath,
    drawerFileContent,
    drawerIsBinary,
    drawerTreeLoading,
    drawerFileLoading,
    drawerActiveLanguage,
    openDrawerFile,
    toggleDrawerFullWidth,
  }
}


export type SkillEditorViewModel = ReturnType<typeof useSkillEditorViewModel>
