import { ref } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { Router } from 'vue-router'

/**
 * 会话管理动作：删除任务、导出会话 JSON、清空会话历史。
 */
export function useTaskAdminActions(options: {
  getCurrentTask: () => any
  clearCurrentTask: () => void
  canDeleteTask: { value: boolean }
  canExportTask: { value: boolean }
  getWorkspaceId: () => string
  loadTasks: (loadOptions?: { reset?: boolean; trySelectRouteTask?: boolean }) => Promise<void>
  submissionsClear: (taskId: string) => void
  clearConversationView: () => void
  resetHistoryPaging: () => void
  bumpHistoryGeneration: () => void
  loadHistory: (taskId: string, reset?: boolean) => Promise<void>
  router: Router
  resolveActionError: (error: unknown, fallbackKey: string, noPermissionKey: string) => string
}) {
  const { t } = useI18n()

  const taskToDelete = ref<any>(null)
  const showDeleteTaskConfirm = ref(false)
  const deletingTask = ref(false)

  const handleDeleteTask = (task: any) => {
    if (!options.canDeleteTask.value) {
      ElMessage.warning(t('chat.errors.no_permission_delete_task'))
      return
    }

    taskToDelete.value = task
    showDeleteTaskConfirm.value = true
  }

  const closeDeleteTaskConfirm = () => {
    if (deletingTask.value) return
    showDeleteTaskConfirm.value = false
    taskToDelete.value = null
  }

  const confirmDeleteTask = async () => {
    if (!taskToDelete.value) return
    if (!options.canDeleteTask.value) {
      ElMessage.warning(t('chat.errors.no_permission_delete_task'))
      return
    }

    deletingTask.value = true
    try {
      await api.delete(`/workspaces/${options.getWorkspaceId()}/tasks/${taskToDelete.value.id}`)
      const deletedId = taskToDelete.value.id
      await options.loadTasks({ reset: true, trySelectRouteTask: false })
      if (options.getCurrentTask()?.id === deletedId) {
        options.clearCurrentTask()
        options.router.push(`/workspaces/${options.getWorkspaceId()}/chat`)
      }
    } catch (e) {
      console.error('Failed to delete task', e)
      ElMessage.error(options.resolveActionError(e, 'chat.errors.delete_failed', 'chat.errors.no_permission_delete_task'))
    } finally {
      deletingTask.value = false
      showDeleteTaskConfirm.value = false
      taskToDelete.value = null
    }
  }

  const handleExport = async () => {
    const task = options.getCurrentTask()
    if (!task) return
    if (!options.canExportTask.value) {
      ElMessage.warning(t('chat.errors.no_permission_export_task'))
      return
    }

    try {
      const res = await api.get(`/workspaces/${options.getWorkspaceId()}/tasks/${task.id}/export`)
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `task-session-${task.id}.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Failed to export session', e)
      ElMessage.error(options.resolveActionError(e, 'chat.errors.export_failed', 'chat.errors.no_permission_export_task'))
    }
  }

  const clearTaskHistory = async (): Promise<{
    deleted_chat_messages: number
    deleted_execution_logs: number
    deleted_total: number
  } | null> => {
    const task = options.getCurrentTask()
    if (!task) return null
    try {
      const res = await api.delete(`/workspaces/${options.getWorkspaceId()}/tasks/${task.id}/history`)
      options.bumpHistoryGeneration()
      options.submissionsClear(String(task.id))
      options.clearConversationView()
      options.resetHistoryPaging()
      await options.loadHistory(task.id, true)
      return res.data
    } catch (e) {
      ElMessage.error(options.resolveActionError(e, 'chat.errors.clear_history_failed', 'chat.errors.no_permission_manage_task_status'))
      return null
    }
  }

  return {
    taskToDelete,
    showDeleteTaskConfirm,
    deletingTask,
    handleDeleteTask,
    closeDeleteTaskConfirm,
    confirmDeleteTask,
    handleExport,
    clearTaskHistory,
  }
}
