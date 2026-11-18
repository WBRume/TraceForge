import { onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'
import api from '@/utils/api'
import type { WorkspaceMemberWorkload, WorkspaceWorkload, WorkloadLimits } from '@/types/workload'

export function useWorkspaceWorkload(workspaceId: () => string, enabled: () => boolean = () => true) {
  return useWorkloadSnapshot<WorkspaceWorkload>(workspaceId, 'workload', enabled)
}

export function useWorkspaceMemberWorkload(workspaceId: () => string) {
  return useWorkloadSnapshot<WorkspaceMemberWorkload>(workspaceId, 'workload/members', () => true)
}

function useWorkloadSnapshot<T extends WorkspaceWorkload | WorkspaceMemberWorkload>(
  workspaceId: () => string,
  endpoint: 'workload' | 'workload/members',
  enabled: () => boolean,
) {
  const data = shallowRef<T | null>(null)
  const failed = shallowRef(false)
  const loading = shallowRef(false)
  let timer: ReturnType<typeof setTimeout> | undefined
  let request: AbortController | undefined
  let disposed = false

  async function refresh() {
    clearTimeout(timer)
    if (disposed || !workspaceId() || !enabled() || document.hidden) return
    request?.abort()
    const controller = new AbortController()
    request = controller
    loading.value = true
    try {
      const result = await api.get<T>(`/workspaces/${workspaceId()}/workspace-assets/${endpoint}`, {
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      data.value = result.data
      failed.value = false
    } catch {
      if (!controller.signal.aborted) failed.value = true
    } finally {
      if (!controller.signal.aborted) {
        loading.value = false
        const next = data.value?.next_evaluate_at
        const serverTime = data.value?.as_of
        const untilExpiry = next && serverTime ? Date.parse(next) - Date.parse(serverTime) : 8000
        const delay = failed.value ? 12000 : Math.max(250, Math.min(8000, untilExpiry))
        timer = setTimeout(refresh, delay)
      }
    }
  }

  watch([workspaceId, enabled], () => {
    request?.abort()
    clearTimeout(timer)
    data.value = null
    failed.value = false
    loading.value = false
    void refresh()
  })
  onMounted(() => {
    document.addEventListener('visibilitychange', refresh)
    void refresh()
  })
  onBeforeUnmount(() => {
    disposed = true
    request?.abort()
    clearTimeout(timer)
    document.removeEventListener('visibilitychange', refresh)
  })

  async function saveLimits(userId: string, limits: WorkloadLimits) {
    await api.put(`/workspaces/${workspaceId()}/workspace-assets/workload/members/${userId}/limits`, limits)
    await refresh()
  }

  return { data, failed, loading, saveLimits }
}
