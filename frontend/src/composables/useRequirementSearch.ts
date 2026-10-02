import { computed, onScopeDispose, ref, watch } from 'vue'
import { fetchRequirementOptions } from '@/services/requirementOptions'
import type { RequirementOption } from '@/types/taskRail'

/** Debounced, SQL-paged search; generation guards both keyword and workspace changes. */
export function useRequirementSearch(getWorkspaceId: () => string, isActive: () => boolean,
  getScope?: (query: string) => { scope?: 'all' | 'roots' | 'children'; parent_id?: string },
  options: { pageSize?: number; append?: boolean } = {}) {
  const query = ref('')
  const items = ref<RequirementOption[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref(false)
  const page = ref(1)
  const pageSize = options.pageSize ?? 40
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
  let generation = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined

  async function search(reset = true) {
    if (!reset && (loading.value || items.value.length >= total.value)) return
    return loadPage(reset ? 1 : page.value + 1, !reset && options.append !== false)
  }

  async function loadPage(nextPage = page.value, append = false) {
    if (!getWorkspaceId() || !isActive()) return
    clearTimeout(timer)
    controller?.abort()
    controller = new AbortController()
    const seq = ++generation
    loading.value = true
    error.value = false
    try {
      const result = await fetchRequirementOptions(getWorkspaceId(), { ...getScope?.(query.value), q: query.value.trim(), page: nextPage, page_size: pageSize }, controller.signal)
      if (seq !== generation) return
      items.value = append ? [...items.value, ...result.items] : result.items
      total.value = result.total
      page.value = nextPage
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
    page.value = 1
    loading.value = isActive()
    error.value = false
    if (isActive()) timer = setTimeout(() => void search(), query.value ? 180 : 0)
  }, { immediate: true })
  onScopeDispose(() => { clearTimeout(timer); generation++; controller?.abort() })
  return { query, items, total, page, totalPages, loading, error, search, loadPage }
}
