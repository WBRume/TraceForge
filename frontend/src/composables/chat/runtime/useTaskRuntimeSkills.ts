import { computed, ref, watch } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useTaskSkillRuntimeTrace } from '@/composables/useTaskSkillRuntimeTrace'
import type { SkillRuntimeEvent } from '@/types/runtimeSkillTrace'
import { isCanceledRequest } from '../shared/requestGuards'
import type { RuntimeSkillFileNode, RuntimeSkillItem } from '../types'

/**
 * 任务运行时技能面板：技能列表、文件树与文件编辑、运行轨迹、使用刷新。
 * 按需加载——面板打开才拉取，关闭期间只标记失效（stale），首屏用任务摘要显示数量；
 * 进行中的请求按 workspace+task 单飞合并，任务切换时全部作废。
 */
export function useTaskRuntimeSkills(options: {
  getWorkspaceId: () => string
  getTaskId: () => string
  getCurrentTask: () => any
  getSignal: () => AbortSignal | undefined
  canEdit: () => boolean
}) {
  const { t } = useI18n()

  const showTaskSkillsDrawer = ref(false)
  const taskRuntimeSkills = ref<RuntimeSkillItem[]>([])
  const taskRuntimeSkillsLoading = ref(false)
  const taskRuntimeSkillsUsageScopeStartAt = ref<string | null>(null)
  const runtimeActiveSkillId = ref('')
  const runtimeFileTreeLoading = ref(false)
  const runtimeFileTree = ref<RuntimeSkillFileNode[]>([])
  const runtimeActiveFilePath = ref('')
  const runtimeActiveFileLoading = ref(false)
  const runtimeActiveFileSaving = ref(false)
  const runtimeActiveFileContent = ref('')
  const runtimeActiveFileOriginalContent = ref('')
  const runtimeActiveFileBinary = ref(false)

  // 技能面板按需加载：列表只在面板打开时拉取，关闭期间只标记失效
  const taskRuntimeSkillsLoaded = ref(false)
  let runtimeSkillsLoadedKey = ''
  let runtimeSkillsFlightKey = ''
  let runtimeSkillsFlight: Promise<boolean> | null = null
  let runtimeSkillsStale = false
  let runtimeSkillsAbort: AbortController | null = null
  let runtimeTraceFlightKey = ''
  let runtimeTraceFlight: Promise<void> | null = null
  let runtimeUsageRefreshTimer: number | null = null

  const {
    runtimeTraceEvents,
    runtimeTraceLoading,
    loadRuntimeTraceEvents,
    appendRuntimeTraceEvent,
    resetRuntimeTraceEvents,
  } = useTaskSkillRuntimeTrace()

  const runtimeSkillsKeyFor = (taskId: string) => `${options.getWorkspaceId()}:${taskId}`
  const runtimeSkillsSignal = (): AbortSignal | undefined => {
    if (!runtimeSkillsAbort) runtimeSkillsAbort = new AbortController()
    return runtimeSkillsAbort.signal
  }

  const clearRuntimeUsageRefreshTimer = () => {
    if (runtimeUsageRefreshTimer !== null) {
      window.clearTimeout(runtimeUsageRefreshTimer)
      runtimeUsageRefreshTimer = null
    }
  }

  const resetForTask = () => {
    runtimeSkillsAbort?.abort()
    runtimeSkillsAbort = null
    taskRuntimeSkillsLoaded.value = false
    runtimeSkillsLoadedKey = ''
    runtimeSkillsFlightKey = ''
    runtimeSkillsFlight = null
    runtimeSkillsStale = false
    runtimeTraceFlightKey = ''
    runtimeTraceFlight = null
    taskRuntimeSkills.value = []
    taskRuntimeSkillsUsageScopeStartAt.value = null
    taskRuntimeSkillsLoading.value = false
    runtimeActiveSkillId.value = ''
    runtimeFileTree.value = []
    runtimeFileTreeLoading.value = false
    runtimeActiveFilePath.value = ''
    runtimeActiveFileLoading.value = false
    runtimeActiveFileSaving.value = false
    runtimeActiveFileContent.value = ''
    runtimeActiveFileOriginalContent.value = ''
    runtimeActiveFileBinary.value = false
    resetRuntimeTraceEvents()
    clearRuntimeUsageRefreshTimer()
  }

  const collectFirstFilePath = (nodes: RuntimeSkillFileNode[]): string => {
    for (const node of nodes) {
      if (node.node_type === 'file') return node.path
      if (node.node_type === 'directory') {
        const nested = collectFirstFilePath(Array.isArray(node.children) ? node.children : [])
        if (nested) return nested
      }
    }
    return ''
  }

  const treeContainsFilePath = (nodes: RuntimeSkillFileNode[], filePath: string): boolean => {
    if (!filePath) return false
    for (const node of nodes) {
      if (node.node_type === 'file' && node.path === filePath) return true
      if (node.node_type === 'directory') {
        if (treeContainsFilePath(Array.isArray(node.children) ? node.children : [], filePath)) {
          return true
        }
      }
    }
    return false
  }

  // ─── 首屏数量（面板未加载时用任务摘要的 skill_ids） ───
  const taskRuntimeSkillCount = computed(() => {
    if (taskRuntimeSkillsLoaded.value) return taskRuntimeSkills.value.length
    const configured = options.getCurrentTask()?.skill_ids
    return Array.isArray(configured) ? configured.length : 0
  })

  const runtimeActiveSkill = computed(() => (
    taskRuntimeSkills.value.find((item) => item.skill_id === runtimeActiveSkillId.value) || null
  ))

  const runtimeActiveFileDirty = computed(() => (
    !runtimeActiveFileBinary.value
    && runtimeActiveFilePath.value.length > 0
    && runtimeActiveFileContent.value !== runtimeActiveFileOriginalContent.value
  ))

  const loadRuntimeSkillFileContent = async (skillId: string, filePath: string) => {
    const taskId = options.getTaskId()
    if (!taskId || !skillId || !filePath) return
    runtimeActiveFileLoading.value = true
    try {
      const res = await api.get(
        `/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/skills/${skillId}/files/content`,
        { params: { path: filePath }, signal: runtimeSkillsSignal() },
      )
      if (options.getTaskId() !== taskId || runtimeActiveSkillId.value !== skillId) return
      runtimeActiveFilePath.value = res.data?.path || filePath
      runtimeActiveFileBinary.value = Boolean(res.data?.is_binary)
      const text = runtimeActiveFileBinary.value ? '' : String(res.data?.content ?? '')
      runtimeActiveFileContent.value = text
      runtimeActiveFileOriginalContent.value = text
    } catch (e) {
      if (isCanceledRequest(e)) return
      if (options.getTaskId() !== taskId) return
      console.error('Failed to load runtime skill file content', e)
      runtimeActiveFilePath.value = filePath
      runtimeActiveFileBinary.value = false
      runtimeActiveFileContent.value = ''
      runtimeActiveFileOriginalContent.value = ''
      ElMessage.error(t('chat.task_skills_file_load_failed'))
    } finally {
      if (options.getTaskId() === taskId) runtimeActiveFileLoading.value = false
    }
  }

  const loadRuntimeSkillFileTree = async (
    skillId: string,
    loadOptions?: { keepCurrentFile?: boolean },
  ) => {
    const taskId = options.getTaskId()
    if (!taskId || !skillId) return
    runtimeFileTreeLoading.value = true
    try {
      const res = await api.get(
        `/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/skills/${skillId}/files/tree`,
        { signal: runtimeSkillsSignal() },
      )
      if (options.getTaskId() !== taskId || runtimeActiveSkillId.value !== skillId) return
      const nodes = Array.isArray(res.data?.nodes) ? res.data.nodes : []
      runtimeFileTree.value = nodes
      const keepCurrent = Boolean(loadOptions?.keepCurrentFile)
      const currentFileExists = keepCurrent
        && Boolean(runtimeActiveFilePath.value)
        && treeContainsFilePath(nodes, runtimeActiveFilePath.value)
      const nextFilePath = currentFileExists ? runtimeActiveFilePath.value : collectFirstFilePath(nodes)
      if (!nextFilePath) {
        runtimeActiveFilePath.value = ''
        runtimeActiveFileBinary.value = false
        runtimeActiveFileContent.value = ''
        runtimeActiveFileOriginalContent.value = ''
        return
      }
      await loadRuntimeSkillFileContent(skillId, nextFilePath)
    } catch (e) {
      if (isCanceledRequest(e)) return
      if (options.getTaskId() !== taskId) return
      console.error('Failed to load runtime skill file tree', e)
      runtimeFileTree.value = []
      runtimeActiveFilePath.value = ''
      runtimeActiveFileBinary.value = false
      runtimeActiveFileContent.value = ''
      runtimeActiveFileOriginalContent.value = ''
      ElMessage.error(t('chat.task_skills_tree_load_failed'))
    } finally {
      if (options.getTaskId() === taskId) runtimeFileTreeLoading.value = false
    }
  }

  const fetchTaskRuntimeSkills = async (fetchOptions?: { silent?: boolean; hydrateEditor?: boolean }): Promise<boolean> => {
    const taskId = options.getTaskId()
    if (!taskId) return false
    const key = runtimeSkillsKeyFor(taskId)
    const silent = Boolean(fetchOptions?.silent)
    const hydrateEditor = Boolean(fetchOptions?.hydrateEditor)
    if (!silent) {
      taskRuntimeSkillsLoading.value = true
    }
    try {
      const res = await api.get(
        `/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/skills/runtime`,
        { signal: runtimeSkillsSignal() },
      )
      if (options.getTaskId() !== taskId) return false
      const items = Array.isArray(res.data?.items) ? res.data.items : []
      taskRuntimeSkills.value = items
      taskRuntimeSkillsUsageScopeStartAt.value = res.data?.usage_scope_start_at || null
      taskRuntimeSkillsLoaded.value = true
      runtimeSkillsLoadedKey = key
      runtimeSkillsStale = false

      const hasActive = items.some((item: RuntimeSkillItem) => item.skill_id === runtimeActiveSkillId.value)
      if (!hasActive) {
        runtimeActiveSkillId.value = items[0]?.skill_id || ''
      }
      if (!runtimeActiveSkillId.value) {
        runtimeFileTree.value = []
        runtimeActiveFilePath.value = ''
        runtimeActiveFileContent.value = ''
        runtimeActiveFileOriginalContent.value = ''
        runtimeActiveFileBinary.value = false
        return true
      }
      if (hydrateEditor || showTaskSkillsDrawer.value) {
        await loadRuntimeSkillFileTree(runtimeActiveSkillId.value, { keepCurrentFile: true })
      }
      return true
    } catch (e) {
      if (isCanceledRequest(e)) return false
      console.error('Failed to load task runtime skills', e)
      if (!silent) {
        ElMessage.error(t('chat.task_skills_runtime_load_failed'))
      }
      if (options.getTaskId() === taskId) {
        taskRuntimeSkills.value = []
        taskRuntimeSkillsUsageScopeStartAt.value = null
        taskRuntimeSkillsLoaded.value = false
        runtimeSkillsLoadedKey = ''
      }
      return false
    } finally {
      if (!silent && options.getTaskId() === taskId) {
        taskRuntimeSkillsLoading.value = false
      }
    }
  }

  /**
   * 技能面板按需加载入口：面板打开/手动刷新时才拉取；进行中的请求合并复用；
   * 列表仍新鲜时直接用（force 强制刷新），runtimeSkillsStale 表示关闭期间事件已使其失效。
   */
  const loadTaskRuntimeSkills = (loadOptions?: { silent?: boolean; hydrateEditor?: boolean; force?: boolean }): Promise<boolean> => {
    const taskId = options.getTaskId()
    if (!taskId) return Promise.resolve(false)
    const key = runtimeSkillsKeyFor(taskId)
    if (runtimeSkillsFlight && runtimeSkillsFlightKey === key) return runtimeSkillsFlight
    const fresh = taskRuntimeSkillsLoaded.value && runtimeSkillsLoadedKey === key && !runtimeSkillsStale
    if (fresh && !loadOptions?.force) {
      const skillId = runtimeActiveSkillId.value
      if (loadOptions?.hydrateEditor && skillId) {
        return loadRuntimeSkillFileTree(skillId, { keepCurrentFile: true }).then(() => true)
      }
      return Promise.resolve(true)
    }
    const flight = fetchTaskRuntimeSkills({
      silent: loadOptions?.silent ?? false,
      hydrateEditor: loadOptions?.hydrateEditor,
    })
    runtimeSkillsFlight = flight
    runtimeSkillsFlightKey = key
    void flight.then(() => {
      if (runtimeSkillsFlight === flight) {
        runtimeSkillsFlight = null
        runtimeSkillsFlightKey = ''
      }
    })
    return flight
  }

  const loadTaskRuntimeTrace = (traceOptions?: { silent?: boolean }): Promise<void> => {
    const taskId = options.getTaskId()
    if (!taskId) return Promise.resolve()
    const key = runtimeSkillsKeyFor(taskId)
    if (runtimeTraceFlight && runtimeTraceFlightKey === key) return runtimeTraceFlight
    const flight = loadRuntimeTraceEvents(
      options.getWorkspaceId(),
      taskId,
      {
        limit: 100,
        silent: traceOptions?.silent,
        isCurrent: () => options.getTaskId() === taskId,
      },
    ).finally(() => {
      if (runtimeTraceFlight === flight) {
        runtimeTraceFlight = null
        runtimeTraceFlightKey = ''
      }
    })
    runtimeTraceFlight = flight
    runtimeTraceFlightKey = key
    return flight
  }

  const openTaskSkillsDrawer = async () => {
    if (!options.getCurrentTask()) return
    showTaskSkillsDrawer.value = true
    await Promise.all([
      loadTaskRuntimeSkills({ hydrateEditor: true }),
      loadTaskRuntimeTrace(),
    ])
  }

  // 技能面板打开时才加载（合并进行中请求；失效/未加载则刷新）；首屏只显示任务摘要数量
  watch([() => String(options.getCurrentTask()?.id || ''), showTaskSkillsDrawer], ([taskId, visible]) => {
    if (!taskId || !visible) return
    void loadTaskRuntimeSkills({ hydrateEditor: true })
    void loadTaskRuntimeTrace()
  })

  const closeTaskSkillsDrawer = () => {
    showTaskSkillsDrawer.value = false
  }

  const selectRuntimeSkill = async (skillId: string) => {
    if (!skillId || runtimeActiveSkillId.value === skillId) return
    runtimeActiveSkillId.value = skillId
    runtimeActiveFilePath.value = ''
    runtimeActiveFileContent.value = ''
    runtimeActiveFileOriginalContent.value = ''
    runtimeActiveFileBinary.value = false
    await loadRuntimeSkillFileTree(skillId)
  }

  const selectRuntimeSkillFile = async (path: string) => {
    const skillId = runtimeActiveSkillId.value
    if (!skillId || !path) return
    await loadRuntimeSkillFileContent(skillId, path)
  }

  const saveRuntimeSkillFileContent = async () => {
    const taskId = options.getTaskId()
    const skillId = runtimeActiveSkillId.value
    const filePath = runtimeActiveFilePath.value
    if (!taskId || !skillId || !filePath) return
    if (!options.canEdit()) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return
    }
    if (runtimeActiveFileBinary.value) {
      ElMessage.warning(t('chat.task_skills_binary_readonly'))
      return
    }
    if (!runtimeActiveFileDirty.value) return
    runtimeActiveFileSaving.value = true
    try {
      const res = await api.put(
        `/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/skills/${skillId}/files/content`,
        { path: filePath, content: runtimeActiveFileContent.value },
        { signal: runtimeSkillsSignal() },
      )
      if (options.getTaskId() !== taskId
        || runtimeActiveSkillId.value !== skillId
        || runtimeActiveFilePath.value !== filePath) return
      const text = String(res.data?.content ?? runtimeActiveFileContent.value)
      runtimeActiveFileContent.value = text
      runtimeActiveFileOriginalContent.value = text
      runtimeActiveFileBinary.value = Boolean(res.data?.is_binary)
      ElMessage.success(t('chat.task_skills_file_saved'))
    } catch (e) {
      if (isCanceledRequest(e)) return
      if (options.getTaskId() !== taskId) return
      console.error('Failed to save runtime skill file', e)
      ElMessage.error(t('chat.task_skills_file_save_failed'))
    } finally {
      if (options.getTaskId() === taskId) runtimeActiveFileSaving.value = false
    }
  }

  const updateRuntimeSkillFileContent = (value: string) => {
    runtimeActiveFileContent.value = value
  }

  /** 技能运行事件到达：面板未打开只标记失效；打开则防抖刷新列表与轨迹。 */
  const scheduleRuntimeUsageRefresh = () => {
    const taskId = options.getTaskId()
    if (!taskId) return
    if (taskRuntimeSkillsLoaded.value && runtimeSkillsLoadedKey === runtimeSkillsKeyFor(taskId)) {
      runtimeSkillsStale = true
    }
    if (!showTaskSkillsDrawer.value) return
    clearRuntimeUsageRefreshTimer()
    runtimeUsageRefreshTimer = window.setTimeout(() => {
      runtimeUsageRefreshTimer = null
      void loadTaskRuntimeSkills({ silent: true, hydrateEditor: false, force: true })
      void loadTaskRuntimeTrace({ silent: true })
    }, 1200)
  }

  /** 轨迹事件合并进面板，并按事件回填对应技能的使用计数。 */
  const mergeRuntimeTraceEvent = (event: SkillRuntimeEvent) => {
    const alreadySeen = runtimeTraceEvents.value.some(item => item.id === event.id)
    appendRuntimeTraceEvent(event)
    if (alreadySeen || !event.skill_id || event.event_type === 'TOOL_RESULT') {
      return
    }
    taskRuntimeSkills.value = taskRuntimeSkills.value.map((skill) => {
      if (skill.skill_id !== event.skill_id) return skill
      const usage = skill.usage || { is_used: false, used_count: 0, last_used_at: null }
      return {
        ...skill,
        usage: {
          ...usage,
          is_used: true,
          used_count: Number(usage.used_count || 0) + 1,
          last_used_at: event.created_at || usage.last_used_at || null,
        },
      }
    })
  }

  return {
    showTaskSkillsDrawer,
    taskRuntimeSkills,
    taskRuntimeSkillsLoading,
    taskRuntimeSkillsUsageScopeStartAt,
    taskRuntimeSkillCount,
    runtimeActiveSkillId,
    runtimeActiveSkill,
    runtimeFileTree,
    runtimeFileTreeLoading,
    runtimeActiveFilePath,
    runtimeActiveFileLoading,
    runtimeActiveFileSaving,
    runtimeActiveFileContent,
    runtimeActiveFileOriginalContent,
    runtimeActiveFileBinary,
    runtimeActiveFileDirty,
    runtimeTraceEvents,
    runtimeTraceLoading,
    openTaskSkillsDrawer,
    closeTaskSkillsDrawer,
    selectRuntimeSkill,
    selectRuntimeSkillFile,
    saveRuntimeSkillFileContent,
    updateRuntimeSkillFileContent,
    loadTaskRuntimeSkills,
    loadTaskRuntimeTrace,
    loadRuntimeSkillFileTree,
    scheduleRuntimeUsageRefresh,
    mergeRuntimeTraceEvent,
    resetForTask,
  }
}
