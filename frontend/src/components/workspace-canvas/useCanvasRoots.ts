import { computed, onScopeDispose, shallowRef } from 'vue'
import api from '@/utils/api'
import { canvasUrl, type CanvasRootWindow, type CanvasRootFilters } from './model'

export type RootDirection = 'next' | 'previous'
interface RootPage {
  index: number
  cursor?: string
  data?: CanvasRootWindow
}

const MAX_PAGES = 3

export function useCanvasRoots(workspaceId: string, first: () => CanvasRootWindow | null) {
  const active = shallowRef<RootPage[]>([{ index: 0 }])
  const filters = shallowRef<CanvasRootFilters>({})
  const loading = shallowRef(false)
  const history = new Map<number, string>()
  let pending: AbortController | null = null
  const resolve = (page: RootPage) => page.data ?? first()
  const pages = computed(() => active.value.flatMap(page => resolve(page) ?? []))
  const canContinue = computed(() => Boolean(resolve(active.value.at(-1)!)?.next_cursor))
  const canReturn = computed(() => active.value[0]!.index > 0)

  async function read(quarter: string, scope: CanvasRootFilters, signal: AbortSignal, cursor?: string, visible: string[] = []) {
    const { data } = await api.get<CanvasRootWindow>(`${canvasUrl(workspaceId)}/roots`, {
      params: { quarter, ...scope, cursor, visible, preview: true }, paramsSerializer: { indexes: null }, signal, timeout: 5000,
    })
    return data
  }

  function visibleRoots() {
    return [...new Set(pages.value.flatMap(page => {
      const roots = new Set(page.root_ids)
      return page.assets.flatMap(asset => roots.has(asset.node_id) ? [`${asset.reference.kind}:${asset.reference.id}`] : [])
    }))].slice(0, 32)
  }

  async function request(action: (signal: AbortSignal) => Promise<boolean>, background = false) {
    const controller = new AbortController()
    pending = controller
    loading.value = !background
    try {
      return await action(controller.signal)
    } catch (error) {
      if (!controller.signal.aborted && !background) throw error
      return false
    } finally {
      if (pending === controller) {
        pending = null
        loading.value = false
      }
    }
  }

  async function filter(quarter: string, scope: CanvasRootFilters) {
    pending?.abort()
    return request(async signal => {
      const data = await read(quarter, scope, signal)
      if (signal.aborted) return false
      filters.value = scope
      history.clear()
      active.value = [{ index: 0, data }]
      return true
    })
  }

  async function move(quarter: string, direction: RootDirection) {
    if (loading.value) return false
    const next = direction === 'next'
    const edge = next ? active.value.at(-1)! : active.value[0]!
    const index = edge.index + (next ? 1 : -1)
    const cursor = next ? resolve(edge)?.next_cursor ?? undefined : history.get(index)
    if ((next && !cursor) || index < 0 || (!next && index > 0 && !cursor)) return false
    pending?.abort()
    return request(async signal => {
      const data = await read(quarter, filters.value, signal, cursor, visibleRoots())
      if (signal.aborted) return false
      if (cursor) history.set(index, cursor)
      const page = { index, cursor, data }
      active.value = next ? [...active.value, page].slice(-MAX_PAGES) : [page, ...active.value].slice(0, MAX_PAGES)
      return true
    })
  }

  function clear() {
    pending?.abort()
    pending = null
    active.value = [{ index: 0 }]
    filters.value = {}
    history.clear()
    loading.value = false
  }

  async function sync(quarter: string) {
    if (pending || !active.value.some(page => page.data)) return
    await request(async signal => {
      const visible = visibleRoots()
      const refreshed = []
      for (const page of active.value) {
        if (!page.data) { refreshed.push(page); continue }
        const data = await read(quarter, filters.value, signal, page.cursor, visible)
        if (signal.aborted) return false
        refreshed.push({ ...page, data })
      }
      active.value = refreshed
      return true
    }, true)
  }

  onScopeDispose(clear)
  return { pages, filters, loading, canContinue, canReturn, filter, move, sync, clear }
}
