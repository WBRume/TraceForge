import { computed, onScopeDispose, shallowRef } from 'vue'
import api from '@/utils/api'
import { canvasUrl, type CanvasAssetWindow, type CanvasRootFilters } from './model'

export function useCanvasRoots(workspaceId: string) {
  const active = shallowRef<{ filters: CanvasRootFilters; cursor?: string } | null>(null)
  const page = shallowRef<CanvasAssetWindow | null>(null)
  const history = shallowRef<(string | undefined)[]>([])
  const loading = shallowRef(false)
  const filters = computed(() => active.value?.filters ?? {})
  let pending: AbortController | null = null

  async function read(quarter: string, scope: CanvasRootFilters, cursor?: string) {
    pending?.abort()
    const request = new AbortController()
    pending = request
    loading.value = true
    try {
      const { data } = await api.get<CanvasAssetWindow>(`${canvasUrl(workspaceId)}/roots`, {
        params: { quarter, ...scope, cursor }, signal: request.signal, timeout: 5000,
      })
      if (request.signal.aborted) return false
      active.value = { filters: scope, cursor }
      page.value = data
      return true
    } catch (error) {
      if (!request.signal.aborted) throw error
      return false
    } finally {
      if (pending === request) { pending = null; loading.value = false }
    }
  }

  async function filter(quarter: string, scope: CanvasRootFilters) {
    if (!await read(quarter, scope)) return false
    history.value = []
    return true
  }

  async function next(quarter: string, cursor: string) {
    const previous = active.value?.cursor
    if (!await read(quarter, filters.value, cursor)) return false
    history.value = [...history.value, previous]
    return true
  }

  async function previous(quarter: string) {
    if (!history.value.length || !await read(quarter, filters.value, history.value.at(-1))) return false
    history.value = history.value.slice(0, -1)
    return true
  }

  function clear() {
    pending?.abort()
    pending = null
    active.value = null
    page.value = null
    history.value = []
    loading.value = false
  }

  async function sync(quarter: string) {
    if (!active.value || pending) return
    try {
      await read(quarter, active.value.filters, active.value.cursor)
    } catch {
      // Keep the current page usable while the canvas reconnects.
    }
  }

  onScopeDispose(clear)
  return { page, filters, loading, history, filter, next, previous, sync, clear }
}
