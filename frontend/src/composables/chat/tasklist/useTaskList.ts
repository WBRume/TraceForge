import { computed, ref } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { TaskRelationFilter, TaskSessionFilter, TaskTypeFilterValue } from '../types'

/**
 * 会话（任务）列表：分页加载、状态/类型/关系三维筛选、跟随切换、滚动加载。
 * 会话选中（selectTask）由组合根注入，列表自身不感知会话编排。
 */
export function useTaskList(options: {
  getWorkspaceId: () => string
  selectRouteTask: (loadOptions?: { allowFetch?: boolean }) => Promise<void>
  canCreateTask: () => boolean
}) {
  const { t } = useI18n()

  const TASK_LIST_PAGE_SIZE = 20

  const tasks = ref<any[]>([])
  const taskListContainer = ref<HTMLElement | null>(null)
  const taskStatusFilter = ref<TaskSessionFilter>('ALL')
  const taskRelationFilter = ref<TaskRelationFilter[]>([])
  const taskTypeFilter = ref<TaskTypeFilterValue>('ALL')
  const taskListPage = ref(1)
  const taskListTotal = ref(0)
  const taskListLoading = ref(false)
  const taskListLoadingMore = ref(false)
  const showTaskModal = ref(false)

  const taskListHasMore = computed(() => tasks.value.length < taskListTotal.value)

  const resolveTaskStatusQuery = (): 'DONE' | 'FAILED' | undefined => {
    if (taskStatusFilter.value === 'DONE') return 'DONE'
    if (taskStatusFilter.value === 'FAILED') return 'FAILED'
    return undefined
  }

  /** 列表加载完成后是否允许对路由任务做单条补拉（筛选状态下不做）。 */
  const canAutoFetchRouteTask = () => (
    !resolveTaskStatusQuery()
    && taskRelationFilter.value.length === 0
    && taskTypeFilter.value === 'ALL'
  )

  const loadTasks = async (loadOptions?: { reset?: boolean; trySelectRouteTask?: boolean; onLoaded?: () => void }) => {
    const reset = loadOptions?.reset ?? true
    const trySelectRouteTask = loadOptions?.trySelectRouteTask ?? reset
    if (reset) {
      if (taskListLoading.value) return
      taskListLoading.value = true
      taskListPage.value = 1
    } else {
      if (taskListLoading.value || taskListLoadingMore.value || !taskListHasMore.value) return
      taskListLoadingMore.value = true
      taskListPage.value += 1
    }

    const wsId = options.getWorkspaceId()
    const statusQuery = resolveTaskStatusQuery()
    try {
      const params: Record<string, string | number> = {
        page: taskListPage.value,
        page_size: TASK_LIST_PAGE_SIZE,
      }
      if (statusQuery) {
        params.status = statusQuery
      }
      if (taskTypeFilter.value !== 'ALL') {
        params.task_type = taskTypeFilter.value
      }
      if (taskRelationFilter.value.length > 0) {
        params.relation = taskRelationFilter.value.join(',')
      }

      const res = await api.get(`/workspaces/${wsId}/tasks`, { params })
      const items = Array.isArray(res.data?.items) ? res.data.items : []
      taskListTotal.value = Number(res.data?.total || 0)
      tasks.value = reset ? items : [...tasks.value, ...items]
      loadOptions?.onLoaded?.()

      if (trySelectRouteTask) {
        // 筛选状态下仅支持从已加载列表中选择，不做单任务补拉
        await options.selectRouteTask({
          allowFetch: reset && canAutoFetchRouteTask(),
        })
      }
    } catch (e) {
      if (!reset) {
        taskListPage.value = Math.max(1, taskListPage.value - 1)
      }
      console.error('Failed to load tasks', e)
    } finally {
      if (reset) {
        taskListLoading.value = false
      } else {
        taskListLoadingMore.value = false
      }
    }
  }

  const loadMoreTasks = async () => {
    if (!taskListHasMore.value) return
    await loadTasks({ reset: false, trySelectRouteTask: false })
  }

  const applyTaskStatusFilter = async () => {
    await loadTasks({ reset: true, trySelectRouteTask: false })
  }

  const applyTaskTypeFilter = async () => {
    await loadTasks({ reset: true, trySelectRouteTask: false })
  }

  const applyTaskRelationFilter = async (relations: TaskRelationFilter[]) => {
    taskRelationFilter.value = [...new Set(relations)]
    await loadTasks({ reset: true, trySelectRouteTask: false })
  }

  const resetTaskRelationFilter = async () => {
    await applyTaskRelationFilter([])
  }

  const handleTaskListScroll = () => {
    const container = taskListContainer.value
    if (!container || taskListLoading.value || taskListLoadingMore.value || !taskListHasMore.value) return
    const nearBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 40
    if (nearBottom) {
      void loadMoreTasks()
    }
  }

  const toggleTaskFollow = async (task: any) => {
    const wsId = options.getWorkspaceId()
    const taskId = String(task?.id || '')
    if (!wsId || !taskId) return
    const following = !Boolean(task.is_following)
    try {
      const response = following
        ? await api.put(`/workspaces/${wsId}/tasks/${taskId}/follow`)
        : await api.delete(`/workspaces/${wsId}/tasks/${taskId}/follow`)
      const nextFollowing = Boolean(response.data?.is_following ?? following)
      tasks.value = tasks.value.map((item: any) => (
        item.id === taskId ? { ...item, is_following: nextFollowing } : item
      ))
      return nextFollowing
    } catch (error) {
      console.error('Failed to update task follow state', error)
      ElMessage.error(t('chat.task_follow_failed'))
      return undefined
    }
  }

  // ─── 任务列表条目的定点更新（供会话编排同步状态/补拉快照） ───
  const findTask = (taskId: string) => tasks.value.find((task: any) => task.id === taskId)

  const patchTask = (taskId: string, patch: Record<string, any>) => {
    const target = tasks.value.find((task: any) => task.id === taskId)
    if (target) Object.assign(target, patch)
  }

  const removeTask = (taskId: string) => {
    tasks.value = tasks.value.filter((item: any) => item.id !== taskId)
  }

  /** 把任务置顶插入列表（路由补拉的场景：移除旧条目并置顶）。 */
  const unshiftTask = (task: any) => {
    tasks.value = [task, ...tasks.value.filter((item: any) => item.id !== task.id)]
  }

  /** 用最新任务快照更新列表：已有条目原位合并，否则置顶插入。 */
  const upsertTask = (task: any) => {
    if (!task?.id) return
    const existing = tasks.value.find((item: any) => item.id === task.id)
    if (existing) Object.assign(existing, task)
    else unshiftTask(task)
  }

  /** 列表刷新后把最新摘要合并进当前会话对象，避免旧状态覆盖。 */
  const syncCurrentTaskFromList = (currentTask: any, currentTaskId: string) => {
    if (!currentTaskId) return
    const latest = tasks.value.find((task: any) => task.id === currentTaskId)
    if (latest && currentTask) {
      Object.assign(currentTask, latest)
    }
  }

  const openNewTaskModal = () => {
    if (!options.canCreateTask()) return
    showTaskModal.value = true
  }

  return {
    tasks,
    taskListContainer,
    taskStatusFilter,
    taskRelationFilter,
    taskTypeFilter,
    taskListHasMore,
    taskListLoading,
    taskListLoadingMore,
    showTaskModal,
    loadTasks,
    loadMoreTasks,
    applyTaskStatusFilter,
    applyTaskTypeFilter,
    applyTaskRelationFilter,
    resetTaskRelationFilter,
    handleTaskListScroll,
    toggleTaskFollow,
    findTask,
    patchTask,
    removeTask,
    unshiftTask,
    upsertTask,
    syncCurrentTaskFromList,
    openNewTaskModal,
  }
}
