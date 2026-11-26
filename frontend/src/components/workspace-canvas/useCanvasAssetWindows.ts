import { computed, onScopeDispose, shallowRef } from 'vue'
import api from '@/utils/api'
import { canvasUrl, referenceKey, type CanvasAsset, type CanvasAssetWindow, type SourceReference } from './model'

const OPEN_BRANCH_LIMIT = 6

interface OpenBranch {
  reference: SourceReference
  first: CanvasAssetWindow
  firstReveal?: SourceReference
  appended: CanvasAssetWindow[]
  revealed: ReadonlyMap<string, { reference: SourceReference; response: CanvasAssetWindow }>
  children: boolean
}

const branchPages = (branch: OpenBranch) =>
  [branch.first, ...branch.appended, ...Array.from(branch.revealed.values(), entry => entry.response)]
const nextCursor = (branch: OpenBranch) => (branch.appended.at(-1) ?? branch.first).next_cursor

export function useCanvasAssetWindows(workspaceId: string, getQuarter: () => string | undefined, seeds: () => CanvasAsset[]) {
  const url = canvasUrl(workspaceId)
  const branches = shallowRef(new Map<string, OpenBranch>())
  const openReferences = computed(() => new Set(branches.value.keys()))
  const located = shallowRef<CanvasAsset | null>(null)
  const loadingKey = shallowRef('')
  let pending: AbortController | null = null

  const projection = computed(() => {
    const initial = located.value ? [...seeds(), located.value] : seeds()
    const byReference = new Map(initial.map(asset => [referenceKey(asset.reference), asset]))
    const queue = [...byReference.keys()]
    const entries = new Map<string, OpenBranch>()
    const parents = new Map<string, string>()
    const pages: CanvasAssetWindow[] = []
    for (const key of queue) {
      const entry = branches.value.get(key)
      if (!entry) continue
      entries.set(key, entry)
      const parent = byReference.get(key)!.node_id
      for (const page of branchPages(entry)) {
        pages.push(page)
        for (const child of page.assets) {
          const childKey = referenceKey(child.reference)
          if (byReference.has(childKey)) continue
          parents.set(child.node_id, parent)
          byReference.set(childKey, child)
          queue.push(childKey)
        }
      }
    }
    return { entries, parents, assets: byReference, pages }
  })
  const windows = computed(() => projection.value.pages)
  const treeParents = computed(() => projection.value.parents)
  const expanded = computed(() => new Map([...projection.value.entries].map(([key, entry]) => [key, {
    cursor: nextCursor(entry),
    empty: !nextCursor(entry) && branchPages(entry).every(page => page.assets.length <= 1 && page.relations.length === 0),
  }])))

  async function query(reference: SourceReference, signal: AbortSignal, cursor?: string, reveal?: SourceReference, children = false) {
    const visible: string[] = []
    for (const { reference: asset } of projection.value.assets.values()) {
      if (asset.kind === 'plan_document' || ('block' in asset && asset.block)) continue
      visible.push(`${asset.kind}:${asset.id}`)
      if (visible.length === 120) break
    }
    const { data } = await api.get<CanvasAssetWindow>(`${url}/window`, {
      params: { kind: reference.kind, id: reference.id, cursor, quarter: getQuarter(), visible,
        reveal: reveal && `${reveal.kind}:${reveal.id}`, children },
      paramsSerializer: { indexes: null },
      signal,
      timeout: 5000,
    })
    return data
  }

  async function load(reference: SourceReference,
    options: { cursor?: string; locate?: boolean; reveal?: SourceReference; children?: boolean } = {}) {
    if (reference.kind === 'plan_document' || ('block' in reference && reference.block)) return null
    const key = referenceKey(reference)
    const existing = options.locate ? undefined : projection.value.entries.get(key)
    const children = options.children ?? existing?.children ?? false
    if (!options.locate && !existing && projection.value.entries.size >= OPEN_BRANCH_LIMIT) return 'limit'
    if (options.cursor && (!existing || options.cursor !== nextCursor(existing))) return null
    pending?.abort()
    const request = new AbortController()
    pending = request
    loadingKey.value = key
    try {
      const response = await query(reference, request.signal, options.cursor, options.reveal, children)
      if (request.signal.aborted || !response.assets.length) return null
      if (options.locate) {
        located.value = response.assets[0]
        branches.value = new Map()
      }
      let branch: OpenBranch = { reference, first: response, firstReveal: options.reveal, appended: [], revealed: new Map(), children }
      if (existing && options.cursor) {
        branch = { ...existing, appended: [...existing.appended, response] }
      } else if (existing && options.reveal) {
        const revealed = new Map(existing.revealed)
        revealed.set(referenceKey(options.reveal), { reference: options.reveal, response })
        branch = { ...existing, revealed }
      }
      branches.value = new Map(branches.value).set(key, branch)
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
          const first = await query(entry.reference, request.signal, undefined, entry.firstReveal, entry.children)
          if (request.signal.aborted) return
          if (!first.assets.length) {
            result.delete(key)
          } else {
            const appended: CanvasAssetWindow[] = []
            let cursor = first.next_cursor
            for (let i = 0; i < entry.appended.length && cursor; i++) {
              const page = await query(entry.reference, request.signal, cursor, undefined, entry.children)
              if (request.signal.aborted) return
              appended.push(page)
              cursor = page.next_cursor
            }
            const revealed = new Map<string, { reference: SourceReference; response: CanvasAssetWindow }>()
            for (const [id, { reference }] of entry.revealed) {
              const response = await query(entry.reference, request.signal, undefined, reference, entry.children)
              if (request.signal.aborted) return
              revealed.set(id, { reference, response })
            }
            result.set(key, { ...entry, first, appended, revealed })
          }
          if (located.value && referenceKey(located.value.reference) === key) located.value = first.assets[0] ?? null
        } catch (error) {
          if (request.signal.aborted) return
          const status = (error as { response?: { status?: number } }).response?.status
          if (status !== 403 && status !== 404) throw error
          result.delete(key)
          if (located.value && referenceKey(located.value.reference) === key) located.value = null
        }
      }
      if (!request.signal.aborted) {
        branches.value = result
        branches.value = projection.value.entries
      }
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
  return { windows, treeParents, located, loadingKey, expanded, openReferences, load, collapse, sync, search, clear }
}
