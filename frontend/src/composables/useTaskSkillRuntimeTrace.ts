import { ref } from 'vue'
import api from '@/utils/api'
import type { SkillRuntimeEvent } from '@/types/runtimeSkillTrace'

export function useTaskSkillRuntimeTrace() {
  const runtimeTraceEvents = ref<SkillRuntimeEvent[]>([])
  const runtimeTraceLoading = ref(false)
  const runtimeTraceError = ref('')

  const loadRuntimeTraceEvents = async (
    workspaceId: string,
    taskId: string,
    options?: { skillId?: string; eventType?: string; limit?: number; silent?: boolean },
  ) => {
    if (!workspaceId || !taskId) return
    if (!options?.silent) runtimeTraceLoading.value = true
    runtimeTraceError.value = ''
    try {
      const res = await api.get(`/workspaces/${workspaceId}/tasks/${taskId}/skills/runtime/events`, {
        params: {
          skill_id: options?.skillId || undefined,
          event_type: options?.eventType || undefined,
          limit: options?.limit || 100,
        },
      })
      runtimeTraceEvents.value = Array.isArray(res.data?.items) ? res.data.items : []
    } catch (error) {
      runtimeTraceError.value = error instanceof Error ? error.message : 'Failed to load runtime trace'
      if (!options?.silent) {
        runtimeTraceEvents.value = []
      }
    } finally {
      if (!options?.silent) runtimeTraceLoading.value = false
    }
  }

  const appendRuntimeTraceEvent = (event: SkillRuntimeEvent) => {
    if (!event?.id) return
    const next = [...runtimeTraceEvents.value]
    const index = next.findIndex(item => item.id === event.id)
    if (index >= 0) next[index] = { ...next[index], ...event }
    else next.push(event)
    next.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    runtimeTraceEvents.value = next.slice(-120)
  }

  const resetRuntimeTraceEvents = () => {
    runtimeTraceEvents.value = []
    runtimeTraceError.value = ''
    runtimeTraceLoading.value = false
  }

  return {
    runtimeTraceEvents,
    runtimeTraceLoading,
    runtimeTraceError,
    loadRuntimeTraceEvents,
    appendRuntimeTraceEvent,
    resetRuntimeTraceEvents,
  }
}
