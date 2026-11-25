import { computed, onScopeDispose, shallowRef } from 'vue'
import api from '@/utils/api'
import { canvasUrl, referenceKey, type CanvasAsset, type CanvasAssetWindow, type SourceReference } from './model'

const PAGE_LIMIT = 6

interface OpenBranch {
  reference: SourceReference
  response: CanvasAssetWindow
  cursor?: string
  previous: (string | undefined)[]
  reveal?: SourceReference
}

export function useCanvasAssetWindows(workspaceId: string, getQuarter: () => string | undefined, seeds: () => CanvasAsset[]) {
  const url = canvasUrl(workspaceId)
  const branches = shallowRef(new Map<string, OpenBranch>())
  const located = shallowRef<CanvasAsset | null>(null)
  const loadingKey = shallowRef('')
  let pending: AbortController | null = null

  const projection = computed(() => {
    const initial = located.value ? [...seeds(), located.value] : seeds()
    const byReference = new Map(initial.map(asset => [referenceKey(asset.reference), asset]))
    const queue = [...byReference.keys()]
    const entries = new Map<string, OpenBranch>()
    const parents = new Map<string, string>()
    for (const key of queue) {
      const entry = branches.value.get(key)
      if (!entry) continue
      entries.set(key, entry)
      const parent = byReference.get(key)!.node_id
      for (const child of entry.response.assets) {
        const childKey = referenceKey(child.reference)
        if (byReference.has(childKey)) continue
        parents.set(child.node_id, parent)
        byReference.set(childKey, child)
        queue.push(childKey)
      }
    }
    return { entries, parents, assets: byReference, pages: [...entries.values()].map(entry => entry.response) }
  })
  const windows = computed(() => projection.value.pages)
  const treeParents = computed(() => projection.value.parents)
  const expanded = computed(() => new Map([...projection.value.entries].map(([key, entry]) => [key, {
    cursor: entry.response.next_cursor,
    previous: entry.previous.length > 0,
    empty: entry.response.assets.length <= 1 && entry.response.relations.length === 0 && !entry.response.next_cursor,
  }])))

  async function query(reference: SourceReference, signal: AbortSignal, cursor?: string, reveal?: SourceReference) {
    const visible = [...projection.value.assets.values()].flatMap(asset =>
      asset.reference.kind !== 'plan_document' && !('block' in asset.reference && asset.reference.block)
        ? [`${asset.reference.kind}:${asset.reference.id}`] : []).slice(0, 120)
    const { data } = await api.get<CanvasAssetWindow>(`${url}/window`, {
      params: { kind: reference.kind, id: reference.id, cursor, quarter: getQuarter(), visible,
        reveal: reveal && `${reveal.kind}:${reveal.id}` },
      paramsSerializer: { indexes: null },
      signal,
      timeout: 5000,
    })
    return data
  }

  async function load(reference: SourceReference,
    options: { cursor?: string; previous?: boolean; locate?: boolean; reveal?: SourceReference } = {}) {
    if (reference.kind === 'plan_document' || ('block' in reference && reference.block)) return null
    const key = referenceKey(reference)
    const existing = projection.value.entries.get(key)
    if (!options.locate && !existing && projection.value.entries.size >= PAGE_LIMIT) return 'limit'
    const cursor = options.previous ? existing?.previous.at(-1) : options.cursor
    const previous = options.previous ? existing?.previous.slice(0, -1) ?? []
      : options.cursor ? [...(existing?.previous ?? []), existing?.cursor] : []
    pending?.abort()
    const request = new AbortController()
    pending = request
    loadingKey.value = key
    try {
      const response = await query(reference, request.signal, cursor, options.reveal)
      if (request.signal.aborted || !response.assets.length) return null
      if (options.locate) {
        located.value = response.assets[0]
        branches.value = new Map()
      }
      branches.value = new Map(branches.value).set(key, { reference, response, cursor, previous, reveal: options.reveal })
      branches.value = projection.value.entries
      return response
    } catch (error) {
      if (!request.signal.aborted) throw error
      return null
    } finally {
      if (pending === request) { pending = null; loadingKey.value = '' }
    }
  }

  async function sync() {
    if (pending || !branches.value.size) return
    const request = new AbortController()
    pending = request
    try {
      const result = new Map(branches.value)
      for (const [key, entry] of projection.value.entries) {
        try {
          const response = await query(entry.reference, request.signal, entry.cursor, entry.reveal)
          if (request.signal.aborted) return
          result.set(key, { ...entry, response })
          if (located.value && referenceKey(located.value.reference) === key) located.value = response.assets[0] ?? null
        } catch (error) {
          if (request.signal.aborted) return
          const status = (error as { response?: { status?: number } }).response?.status
          if (status !== 403 && status !== 404) throw error
          result.delete(key)
          if (located.value && referenceKey(located.value.reference) === key) located.value = null
        }
      }
      if (!request.signal.aborted) branches.value = result
    } catch {
      // A transient read failure leaves the last usable expansion on screen.
    } finally {
      if (pending === request) pending = null
    }
  }

  function cancel() {
    pending?.abort()
    pending = null
    loadingKey.value = ''
  }

  function collapse(reference: SourceReference) {
    cancel()
    const next = new Map(branches.value)
    next.delete(referenceKey(reference))
    branches.value = next
    branches.value = projection.value.entries
  }

  function clear() {
    cancel()
    located.value = null
    branches.value = new Map()
  }

  async function search(q: string, signal?: AbortSignal, kind?: SourceReference['kind']) {
    const { data } = await api.get<CanvasAsset[]>(`${url}/search`, { params: { q, kind }, signal, timeout: 3800 })
    return data
  }

  onScopeDispose(clear)
  return { windows, treeParents, located, loadingKey, expanded, load, collapse, sync, search, clear }
}
