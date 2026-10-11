import { shallowRef, watch } from 'vue'
import api from '@/utils/api'
import type { TaskInspection } from '@/types/taskInspection'

export function useTaskInspection(workspaceId: () => string, taskId: () => string) {
  const detail = shallowRef<TaskInspection | null>(null)
  const loading = shallowRef(false)
  const failed = shallowRef(false)
  const revision = shallowRef(0)

  watch([workspaceId, taskId, revision], async ([wsId, id], _previous, onCleanup) => {
    const controller = new AbortController()
    onCleanup(() => controller.abort())
    detail.value = null
    failed.value = false
    loading.value = Boolean(wsId && id)
    if (!wsId || !id) return
    try {
      const response = await api.get<TaskInspection>(
        `/workspaces/${encodeURIComponent(wsId)}/tasks/${encodeURIComponent(id)}/details`,
        { signal: controller.signal },
      )
      if (!controller.signal.aborted) detail.value = response.data
    } catch {
      if (!controller.signal.aborted) failed.value = true
    } finally {
      if (!controller.signal.aborted) loading.value = false
    }
  }, { immediate: true })

  return { detail, loading, failed, reload: () => { revision.value++ } }
}
