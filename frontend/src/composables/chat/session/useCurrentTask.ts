import { computed, ref } from 'vue'
import { isTerminalTaskStatus } from '@/utils/taskStatus'
import { mergeTaskSnapshot } from '@/utils/taskStatusProjection'

/**
 * 当前任务会话实体：currentTask 及其派生状态。
 * 只拥有 currentTask 本身；任务列表中对应条目的同步由组合根协调。
 */
export function useCurrentTask() {
  const currentTask = ref<any>(null)

  const setCurrent = (task: any) => {
    const next: any = {}
    if (task) mergeTaskSnapshot(next, task)
    currentTask.value = task ? next : null
  }

  const clearCurrent = () => {
    currentTask.value = null
  }

  const patchCurrent = (patch: Record<string, any>) => {
    if (!currentTask.value) return
    mergeTaskSnapshot(currentTask.value, patch)
  }

  const getTaskId = () => String(currentTask.value?.id || '')

  const isTaskPreStart = computed(() => currentTask.value?.status === 'INITIALIZED')
  // 任务创建后处于 PROVISIONING 时也保留启动引擎按钮（禁用态），避免按钮凭空消失；
  // 只有资源准备完成回到 INITIALIZED 后才允许真正启动。
  const isTaskProvisioning = computed(() => String(currentTask.value?.status || '') === 'PROVISIONING')
  const isTaskInterrupted = computed(() => currentTask.value?.status === 'INTERRUPTED')
  const isTerminalStatus = computed(() => isTerminalTaskStatus(currentTask.value?.status))
  // 问题定位任务：不展示需求文档抽屉，改用诊断文档/代码路径抽屉；隐藏 git patch 相关入口
  const isDiagnosisTask = computed(() => String(currentTask.value?.task_type || '') === 'DIAGNOSIS')
  const hidePatchWorkflows = computed(() => isDiagnosisTask.value)

  return {
    currentTask,
    setCurrent,
    clearCurrent,
    patchCurrent,
    getTaskId,
    isTaskPreStart,
    isTaskProvisioning,
    isTaskInterrupted,
    isTerminalStatus,
    isDiagnosisTask,
    hidePatchWorkflows,
  }
}
