import { computed, ref } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { Router } from 'vue-router'

/**
 * 任务状态动作：临时中断、标记完成/失败（closeout 面板入口）、
 * closeout 成功收敛，以及创建人取消任务资源准备。
 */
export function useTaskStatusActions(options: {
  getCurrentTask: () => any
  isTaskProvisioning: { value: boolean }
  canManageTaskStatus: { value: boolean }
  getWorkspaceId: () => string
  engineRunning: { value: boolean }
  interruptingTask: { value: boolean }
  cardsDropStatusCards: () => void
  cardsDropByTypes: (types: string[]) => void
  jobsReset: () => void
  messagesPush: (message: any) => void
  isHistoryAnchored: () => boolean
  scrollToChatBottom: () => void
  interruptTask: (taskId: string, reason?: string) => Promise<any>
  applyTaskSessionPayload: (payload: any) => void
  refreshActiveJobs: (taskId: string) => Promise<boolean>
  loadTasks: (loadOptions?: { reset?: boolean; trySelectRouteTask?: boolean }) => Promise<void>
  patchTask: (taskId: string, patch: Record<string, any>) => void
  removeTask: (taskId: string) => void
  clearCurrentTask: () => void
  router: Router
  resolveActionError: (error: unknown, fallbackKey: string, noPermissionKey: string) => string
}) {
  const { t } = useI18n()

  // closeout 面板模式：'complete' 标记完成 / 'fail' 标记失败；null 关闭
  const closeoutMode = ref<'complete' | 'fail' | null>(null)

  const canTemporarilyInterrupt = computed(() => (
    Boolean(options.getCurrentTask()?.id)
    && options.engineRunning.value
    && options.canManageTaskStatus.value
    && !options.interruptingTask.value
  ))

  const handleInterruptClick = (): boolean => {
    if (!options.canManageTaskStatus.value) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return false
    }

    // 准备中的任务：停止按钮 = 取消任务创建（回滚资源并删除任务），不走 closeout
    if (options.isTaskProvisioning.value) {
      void cancelTaskProvision()
      return true
    }

    const status = options.getCurrentTask()?.status
    const isRunningStatus = status && !['DONE', 'FAILED'].includes(status)

    if (!isRunningStatus && !options.engineRunning.value) {
      ElMessage.warning(t('chat.no_running_engine'))
      return false
    }
    closeoutMode.value = 'fail'
    return true
  }

  const handleCompleteClick = (): boolean => {
    if (!options.canManageTaskStatus.value) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return false
    }

    const status = options.getCurrentTask()?.status
    const isRunningStatus = status && !['DONE', 'FAILED'].includes(status)

    if (!isRunningStatus && !options.engineRunning.value) {
      ElMessage.warning(t('chat.no_running_engine'))
      return false
    }
    closeoutMode.value = 'complete'
    return true
  }

  /** 临时中断当前执行（不改任务终态），引擎可随后恢复。 */
  const interruptCurrentRun = async (): Promise<boolean> => {
    const task = options.getCurrentTask()
    if (!task?.id) return false
    if (!options.canManageTaskStatus.value) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return false
    }
    if (!options.engineRunning.value) {
      ElMessage.warning(t('chat.no_running_engine'))
      return false
    }

    try {
      const payload = await options.interruptTask(
        task.id,
        t('chat.temporary_interrupt_reason'),
      )
      options.cardsDropStatusCards()
      options.engineRunning.value = false
      options.applyTaskSessionPayload(payload)
      return true
    } catch (e: any) {
      console.error('Temporary interrupt failed', e)
      const detail = String(e?.response?.data?.detail || '')
      if (
        detail.includes('No running Claude CLI session')
        || detail.includes('No running Claude CLI session or active AI job')
      ) {
        // 后端认为已经没有可中断的会话/作业：同步前端运行状态，避免停止按钮一直可点
        options.engineRunning.value = false
        if (options.getCurrentTask()?.id) {
          void options.refreshActiveJobs(options.getCurrentTask().id)
        }
      }
      ElMessage.error(options.resolveActionError(e, 'chat.errors.temporary_interrupt_failed', 'chat.errors.no_permission_manage_task_status'))
      return false
    }
  }

  const closeTaskCloseout = () => {
    closeoutMode.value = null
  }

  const handleTaskCloseoutSuccess = (status: string) => {
    const task = options.getCurrentTask()
    if (!task) return
    closeoutMode.value = null
    options.engineRunning.value = false
    options.cardsDropByTypes(['status', 'hitl'])
    options.jobsReset()
    task.status = status
    options.patchTask(task.id, { status })
    options.messagesPush({
      id: Date.now().toString(),
      role: 'system',
      content: status === 'DONE' ? t('chat.closeout.complete_saved') : t('chat.closeout.failure_saved'),
      created_at: new Date().toISOString(),
      message_type: 'text',
    })
    if (!options.isHistoryAnchored()) options.scrollToChatBottom()
  }

  /** 创建人取消当前任务的资源准备：后台回滚清理并删除任务，随后刷新列表并离开该任务 */
  const cancelTaskProvision = async (): Promise<boolean> => {
    const task = options.getCurrentTask()
    const wsId = options.getWorkspaceId()
    if (!task?.id || !wsId) return false
    try {
      await api.post(`/workspaces/${wsId}/tasks/${task.id}/provision-job/cancel`)
      ElMessage.info(t('provisioning.cancelling'))
      options.removeTask(task.id)
      if (options.getCurrentTask()?.id === task.id) {
        options.clearCurrentTask()
        if (options.router.currentRoute.value.params.taskId) {
          options.router.push(`/workspaces/${wsId}/chat`)
        }
      }
      return true
    } catch (e: any) {
      const detail = String(e?.response?.data?.detail || '')
      if (detail.includes('No active provisioning job')) {
        // 已经没有进行中的准备（可能刚完成）：回读任务最新状态
        await options.loadTasks({ reset: true, trySelectRouteTask: false })
        return false
      }
      ElMessage.error(options.resolveActionError(e, 'provisioning.cancel_failed', 'provisioning.cancel_failed'))
      return false
    }
  }

  return {
    closeoutMode,
    canTemporarilyInterrupt,
    handleInterruptClick,
    handleCompleteClick,
    interruptCurrentRun,
    closeTaskCloseout,
    handleTaskCloseoutSuccess,
    cancelTaskProvision,
  }
}
