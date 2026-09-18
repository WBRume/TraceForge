import { computed, ref } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { formatApiError } from '@/utils/error'
import type { Ref } from 'vue'
import type { TaskSpecBootstrap } from '../types'

/**
 * 任务规格引导（spec bootstrap）状态：快照拉取、手动触发构建、
 * WS spec_bootstrap_update 应用与状态文案。
 */
export function useSpecBootstrap(options: {
  getWorkspaceId: () => string
  currentTask: Ref<any>
  hasTaskSpecification: (task: any) => boolean
}) {
  const { t } = useI18n()

  const specBootstrap = ref<TaskSpecBootstrap | null>(null)
  const specBootstrapLoading = ref(false)
  const specBootstrapTriggering = ref(false)

  const isSpecBootstrapActive = computed(() => (
    specBootstrap.value?.status === 'PENDING' || specBootstrap.value?.status === 'RUNNING'
  ))

  const canTriggerSpecBootstrap = computed(() => {
    const status = specBootstrap.value?.status
    return status === 'PENDING' || status === 'FAILED' || status === 'STALE'
  })

  const reset = () => {
    specBootstrap.value = null
    specBootstrapLoading.value = false
  }

  const load = async (taskId: string, taskSnapshot?: any) => {
    if (!taskId || !options.hasTaskSpecification(taskSnapshot ?? options.currentTask.value)) {
      reset()
      return
    }
    specBootstrapLoading.value = true
    try {
      const res = await api.get(`/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/spec-bootstrap`)
      if (String(options.currentTask.value?.id || '') !== String(taskId)) return
      specBootstrap.value = res.data as TaskSpecBootstrap
    } catch (e: any) {
      if (String(options.currentTask.value?.id || '') !== String(taskId)) return
      if (e?.response?.status === 404) {
        specBootstrap.value = null
        return
      }
      console.warn('Failed to load spec bootstrap snapshot', e)
    } finally {
      if (String(options.currentTask.value?.id || '') === String(taskId)) specBootstrapLoading.value = false
    }
  }

  const trigger = async () => {
    const taskId = options.currentTask.value?.id
    if (!taskId || specBootstrapTriggering.value) return
    specBootstrapTriggering.value = true
    try {
      await api.post(`/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/spec-bootstrap/run`)
      ElMessage.success(t('chat.spec_bootstrap_build_started'))
    } catch (e: any) {
      if (e?.response?.status === 409) {
        const detail = typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : ''
        ElMessage.info(detail || t('chat.spec_bootstrap_build_started'))
      } else {
        ElMessage.error(formatApiError(e, t('chat.spec_bootstrap_build_failed'), t))
      }
    } finally {
      specBootstrapTriggering.value = false
      void load(taskId, options.currentTask.value)
    }
  }

  const statusText = (status?: string) => {
    if (status === 'PENDING') return t('chat.spec_bootstrap_status_pending')
    if (status === 'RUNNING') return t('chat.spec_bootstrap_status_running')
    if (status === 'READY') return t('chat.spec_bootstrap_status_ready')
    if (status === 'FAILED') return t('chat.spec_bootstrap_status_failed')
    if (status === 'STALE') return t('chat.spec_bootstrap_status_stale')
    return ''
  }

  /** WS spec_bootstrap_update：任务匹配且具备规格文档时应用。 */
  const applyUpdate = (payload: any) => {
    const task = options.currentTask.value
    if (!task?.id) return
    if (String(payload?.task_id || '') !== String(task.id)) return
    if (!options.hasTaskSpecification(task)) return
    specBootstrap.value = payload as TaskSpecBootstrap
  }

  return {
    specBootstrap,
    specBootstrapLoading,
    specBootstrapTriggering,
    isSpecBootstrapActive,
    canTriggerSpecBootstrap,
    reset,
    load,
    trigger,
    statusText,
    applyUpdate,
  }
}
