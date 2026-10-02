import { computed, ref, watch } from 'vue'
import api from '@/utils/api'
import type { RequirementOption } from '@/types/taskRail'

export function useRequirementTaskCreation(getWorkspaceId: () => string) {
  const selectedRequirement = ref<RequirementOption | null>(null)
  const allowed = ref(false)
  let generation = 0
  watch(getWorkspaceId, async (workspaceId) => {
    const seq = ++generation
    selectedRequirement.value = null
    allowed.value = false
    if (!workspaceId) return
    try {
      const { data } = await api.get(`/workspaces/${workspaceId}/permissions/me`)
      if (generation === seq) allowed.value = Boolean(data.permissions?.create_task)
    } catch { /* The server also checks task creation permission. */ }
  }, { immediate:true })
  return {
    selectedRequirement, canCreateTask:computed(() => allowed.value),
    open: (requirement: RequirementOption) => { if (allowed.value && !requirement.child_count && requirement.can_link_task !== false) selectedRequirement.value = requirement },
    close: () => { selectedRequirement.value = null },
  }
}
