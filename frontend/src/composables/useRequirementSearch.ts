import { onScopeDispose, ref, watch } from 'vue'
import { fetchRequirementOptions } from '@/services/requirementOptions'
import type { RequirementOption } from '@/types/taskRail'

/** Debounced, SQL-paged search; generation guards both keyword and workspace changes. */
export function useRequirementSearch(getWorkspaceId: () => string, isActive: () => boolean,
  getScope?: (query: string) => { scope?: 'all' | 'roots' | 'children'; parent_id?: string }) {
  const query = ref('')
  const items = ref<RequirementOption[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref(false)
  let page = 1
  let generation = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined

  async function search(reset = true) {
    if (!getWorkspaceId() || !isActive()) return
    if (!reset && (loading.value || items.value.length >= total.value)) return
    controller?.abort()
    controller = new AbortController()
    const seq = ++generation
    const nextPage = reset ? 1 : page + 1
    loading.value = true
    error.value = false
    try {
      const result = await fetchRequirementOptions(getWorkspaceId(), { ...getScope?.(query.value), q: query.value.trim(), page: nextPage, page_size: 40 }, controller.signal)
      if (seq !== generation) return
      items.value = reset ? result.items : [...items.value, ...result.items]
      total.value = result.total
      page = nextPage
    } catch {
      if (seq === generation) error.value = true
    } finally {
      if (seq === generation) loading.value = false
    }
  }

  watch([getWorkspaceId, isActive, query, () => JSON.stringify(getScope?.(query.value))], () => {
    clearTimeout(timer)
    controller?.abort()
    generation++
    items.value = []
    total.value = 0
    loading.value = isActive()
    error.value = false
    if (isActive()) timer = setTimeout(() => void search(), query.value ? 180 : 0)
  }, { immediate: true })
  onScopeDispose(() => { clearTimeout(timer); generation++; controller?.abort() })
  return { query, items, total, loading, error, search }
}
