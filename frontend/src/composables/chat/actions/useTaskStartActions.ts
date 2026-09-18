import { computed, ref } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { RuntimeSkillItem } from '../types'

/**
 * 引擎启动 / 会话初始化：启动确认弹窗、初始化弹窗（理由 + 初始提示词 + 技能选择）、
 * 已删除 runtime 技能的二次确认，以及初始化执行（清空会话视图 → POST → 重载快照）。
 */
export function useTaskStartActions(options: {
  getCurrentTask: () => any
  isTaskPreStart: { value: boolean }
  isTaskProvisioning: { value: boolean }
  canStartTask: { value: boolean }
  canManageTaskStatus: { value: boolean }
  getWorkspaceId: () => string
  engineRunning: { value: boolean }
  submissionsClear: (taskId: string) => void
  loadHistory: (taskId: string, reset?: boolean) => Promise<void>
  refreshActiveJobs: (taskId: string) => Promise<boolean>
  resetConversationView: () => void
  patchTask: (taskId: string, patch: Record<string, any>) => void
  specDrawerClose: () => void
  scrollIfNotAnchored: () => void
  skills: {
    taskRuntimeSkills: { value: RuntimeSkillItem[] }
    taskRuntimeSkillsLoading: { value: boolean }
    showTaskSkillsDrawer: { value: boolean }
    loadTaskRuntimeSkills: (opts?: { silent?: boolean; hydrateEditor?: boolean }) => Promise<boolean>
  }
  resolveActionError: (error: unknown, fallbackKey: string, noPermissionKey: string) => string
}) {
  const { t } = useI18n()

  // ─── 启动引擎 ───
  const startPrompt = ref('')
  const showStartConfirm = ref(false)
  const startingTask = ref(false)

  // ─── 会话初始化 ───
  const showInitReasonModal = ref(false)
  const initPrompt = ref('')
  const initReason = ref('')
  const initSkillOptionsLoading = ref(false)
  const initSkillOptions = ref<any[]>([])
  const initSelectedSkillIds = ref<string[]>([])
  const showDeletedRuntimeSkillConfirm = ref(false)

  const isStartActionVisible = computed(() => Boolean(options.getCurrentTask()) && (options.isTaskPreStart.value || options.isTaskProvisioning.value))
  const canClickStartAction = computed(() => (
    options.isTaskPreStart.value && options.canStartTask.value && !startingTask.value
  ))
  const canInitializeAction = computed(() => (
    Boolean(options.getCurrentTask()) && !options.isTaskPreStart.value && options.canManageTaskStatus.value
  ))

  const defaultInitialPromptForTask = (task: any): string => {
    const description = String(task?.description || '').trim()
    if (description) return description
    return t('chat.start_default_prompt', {
      taskName: String(task?.name || ''),
    })
  }

  const handleStartClick = () => {
    if (!options.getCurrentTask()) return
    if (!isStartActionVisible.value) return
    if (options.isTaskProvisioning.value) {
      ElMessage.warning(t('chat.task_provisioning_hint'))
      return
    }
    if (!options.canStartTask.value) {
      ElMessage.warning(t('chat.errors.no_permission_start_task'))
      return
    }
    if (startingTask.value) return
    startPrompt.value = defaultInitialPromptForTask(options.getCurrentTask())
    showStartConfirm.value = true
  }

  const startTask = async (): Promise<boolean> => {
    const task = options.getCurrentTask()
    if (!task) return false
    if (!isStartActionVisible.value) return false
    if (options.isTaskProvisioning.value) {
      ElMessage.warning(t('chat.task_provisioning_hint'))
      return false
    }
    if (!options.canStartTask.value) {
      ElMessage.warning(t('chat.errors.no_permission_start_task'))
      return false
    }
    if (startingTask.value) return false
    startingTask.value = true

    const prompt = String(startPrompt.value || defaultInitialPromptForTask(task)).trim()

    try {
      await api.post(
        `/workspaces/${options.getWorkspaceId()}/tasks/${task.id}/start`,
        { prompt }
      )

      task.status = 'CODING'
      options.engineRunning.value = true
      showStartConfirm.value = false
      options.specDrawerClose()

      // The API persists the exact user-visible initial prompt. Reload it so
      // start and initialize share the same durable transcript behavior.
      await options.loadHistory(task.id)
      options.scrollIfNotAnchored()
      return true
    } catch (e) {
      console.error('Start task failed', e)
      ElMessage.error(options.resolveActionError(e, 'chat.errors.start_failed', 'chat.errors.no_permission_start_task'))
      return false
    } finally {
      startingTask.value = false
    }
  }

  const activeInitSkillOptionIds = computed(() => new Set(
    initSkillOptions.value.map((item) => String(item.id || '').trim()).filter(Boolean),
  ))

  const loadInitSkillOptions = async () => {
    const wsId = options.getWorkspaceId()
    if (!wsId) return
    initSkillOptionsLoading.value = true
    try {
      const res = await api.get('/skills', {
        params: { workspace_id: wsId, scope: 'all', page: 1, page_size: 200 },
      })
      initSkillOptions.value = Array.isArray(res.data?.items) ? res.data.items : []
    } catch (e) {
      console.error('Failed to load initialize skill options', e)
      initSkillOptions.value = []
    } finally {
      initSkillOptionsLoading.value = false
    }
  }

  /** 初始化默认选中的技能：runtime 技能中仍存在的优先，回退到任务摘要的 skill_ids。 */
  const extractTaskSkillIds = (): string[] => {
    const optionIds = activeInitSkillOptionIds.value
    const list = options.skills.taskRuntimeSkills.value
      .map((item) => String(item.skill_id || '').trim())
      .filter((skillId) => Boolean(skillId) && !skillId.startsWith('runtime:') && optionIds.has(skillId))
    if (list.length) return list
    const fallback = Array.isArray(options.getCurrentTask()?.skill_ids) ? options.getCurrentTask().skill_ids : []
    return fallback
      .map((value: string) => String(value || '').trim())
      .filter((skillId: string) => (
        Boolean(skillId)
        && !skillId.startsWith('runtime:')
        && (optionIds.size === 0 || optionIds.has(skillId))
      ))
  }

  const deletedRuntimeSkillsForInitialize = computed(() => options.skills.taskRuntimeSkills.value.filter((item) => (
    Boolean(item.config_deleted) || String(item.skill_id || '').startsWith('runtime:')
  )))
  const deletedRuntimeSkillNamesForInitialize = computed(() => deletedRuntimeSkillsForInitialize.value
    .map((skill) => String(skill.name || skill.materialized_dir || skill.skill_id || '').trim())
    .filter(Boolean))

  const handleInitialize = async () => {
    if (!options.getCurrentTask()) return
    if (!options.canManageTaskStatus.value) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return
    }
    if (!canInitializeAction.value) return
    initReason.value = ''
    initPrompt.value = defaultInitialPromptForTask(options.getCurrentTask())
    const fallbackSkillIds = Array.isArray(options.getCurrentTask()?.skill_ids)
      ? options.getCurrentTask().skill_ids.map((value: string) => String(value || '').trim()).filter(Boolean)
      : []
    initSelectedSkillIds.value = Array.from(new Set(fallbackSkillIds))
    showInitReasonModal.value = true
    await Promise.all([
      options.skills.loadTaskRuntimeSkills({ hydrateEditor: false }),
      loadInitSkillOptions(),
    ])
    initSelectedSkillIds.value = extractTaskSkillIds()
  }

  const initializeTaskWithReason = async (
    reason?: string,
    prompt?: string,
    skillIds?: string[],
    initOptions?: { keepDeletedRuntimeSkills?: boolean },
  ): Promise<boolean> => {
    const task = options.getCurrentTask()
    if (!task) return false
    if (!options.canManageTaskStatus.value) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return false
    }

    const reasonText = String(reason ?? initReason.value).trim()
    const promptText = String(prompt ?? initPrompt.value).trim()
    const hasSkillSelectionArg = Array.isArray(skillIds)
    const optionIds = activeInitSkillOptionIds.value
    const normalizedSkillIds = hasSkillSelectionArg
      ? Array.from(new Set((skillIds || [])
          .map((value) => String(value || '').trim())
          .filter((skillId) => (
            Boolean(skillId)
            && !skillId.startsWith('runtime:')
            && (optionIds.size === 0 || optionIds.has(skillId))
          ))))
      : []
    options.resetConversationView()

    options.engineRunning.value = true
    try {
      const payload: Record<string, unknown> = {
        reason: reasonText || undefined,
        prompt: promptText || undefined,
      }
      if (hasSkillSelectionArg) {
        payload.skill_ids = normalizedSkillIds
        payload.keep_deleted_runtime_skills = initOptions?.keepDeletedRuntimeSkills !== false
      }
      await api.post(
        `/workspaces/${options.getWorkspaceId()}/tasks/${task.id}/initialize`,
        payload,
      )
      task.status = 'CODING'
      if (hasSkillSelectionArg) {
        task.skill_ids = normalizedSkillIds
      }

      options.submissionsClear(String(task.id))
      // 加载初始化时保存的消息（用户初始消息 + 可能的 init_reason 分隔线）
      await options.loadHistory(task.id)
      await options.refreshActiveJobs(task.id)
      await options.skills.loadTaskRuntimeSkills({ silent: true, hydrateEditor: options.skills.showTaskSkillsDrawer.value })

      options.patchTask(task.id, hasSkillSelectionArg
        ? { status: 'CODING', skill_ids: normalizedSkillIds }
        : { status: 'CODING' })
      return true
    } catch (e) {
      console.error('Initialize failed', e)
      ElMessage.error(options.resolveActionError(e, 'chat.errors.initialize_failed', 'chat.errors.no_permission_manage_task_status'))
      options.engineRunning.value = false
      return false
    }
  }

  const confirmInitialize = async () => {
    if (!options.getCurrentTask()) return
    if (initSkillOptionsLoading.value || options.skills.taskRuntimeSkillsLoading.value) return
    if (deletedRuntimeSkillsForInitialize.value.length > 0) {
      showDeletedRuntimeSkillConfirm.value = true
      return
    }
    showInitReasonModal.value = false
    await initializeTaskWithReason(
      initReason.value,
      initPrompt.value,
      initSelectedSkillIds.value,
      { keepDeletedRuntimeSkills: true },
    )
  }

  const cancelDeletedRuntimeSkillConfirm = () => {
    showDeletedRuntimeSkillConfirm.value = false
  }

  const confirmInitializeWithDeletedRuntimeSkillDecision = async (keepDeletedRuntimeSkills: boolean) => {
    if (!options.getCurrentTask()) return
    showDeletedRuntimeSkillConfirm.value = false
    showInitReasonModal.value = false
    await initializeTaskWithReason(
      initReason.value,
      initPrompt.value,
      initSelectedSkillIds.value,
      { keepDeletedRuntimeSkills },
    )
  }

  /** 会话切换：清空初始化弹窗的技能选择（弹窗状态由打开时重建）。 */
  const resetInitializeState = () => {
    initSelectedSkillIds.value = []
  }

  return {
    startPrompt,
    showStartConfirm,
    startingTask,
    showInitReasonModal,
    initPrompt,
    initReason,
    initSkillOptions,
    initSkillOptionsLoading,
    initSelectedSkillIds,
    showDeletedRuntimeSkillConfirm,
    isStartActionVisible,
    canClickStartAction,
    canInitializeAction,
    deletedRuntimeSkillsForInitialize,
    deletedRuntimeSkillNamesForInitialize,
    handleStartClick,
    startTask,
    handleInitialize,
    initializeTaskWithReason,
    confirmInitialize,
    cancelDeletedRuntimeSkillConfirm,
    confirmInitializeWithDeletedRuntimeSkillDecision,
    resetInitializeState,
  }
}
