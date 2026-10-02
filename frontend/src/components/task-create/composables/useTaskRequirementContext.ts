import { onScopeDispose, shallowRef, watch } from 'vue'
import api from '@/utils/api'
import type { RequirementDetail, RequirementSummary } from '@/types/workspaceAssets'

/** Fetch the saved prompt and document once per selection; stale responses cannot fill another draft. */
export function useTaskRequirementContext(getWorkspaceId: () => string, getRequirementId: () => string | undefined) {
  const requirement = shallowRef<RequirementSummary | null>(null)
  const loading = shallowRef(false)
  const error = shallowRef(false)
  let generation = 0
  let controller: AbortController | undefined
  async function load() {
    const seq = ++generation
    controller?.abort()
    controller = new AbortController()
    requirement.value = null
    error.value = false
    const id = getRequirementId()
    loading.value = Boolean(id)
    if (!id) return
    try {
      const { data } = await api.get<RequirementDetail>(`/workspaces/${getWorkspaceId()}/workspace-assets/requirements/${id}`, { signal: controller.signal })
      if (seq !== generation) return
      if (data.requirement.id !== id || !data.requirement.can_link_task || data.requirement.child_count > 0) throw new Error('Select a leaf requirement')
      requirement.value = data.requirement
    } catch { if (seq === generation) error.value = true }
    finally { if (seq === generation) loading.value = false }
  }
  watch([getWorkspaceId, getRequirementId], () => { void load() }, { immediate: true })
  onScopeDispose(() => { generation++; controller?.abort() })
  return { requirement, loading, error, load }
}
