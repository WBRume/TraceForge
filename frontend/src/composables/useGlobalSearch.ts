import { shallowRef, watch, onScopeDispose, type Ref } from 'vue'
import { searchApi } from '@/services/searchApi'
import type { Retrieval, SearchItem, SearchResponse } from '@/types/search'

export function useGlobalSearch(open: Ref<boolean>) {
  const query = shallowRef('')
  const retrieval = shallowRef<Retrieval>('hybrid')
  const kind = shallowRef('all')
  const composing = shallowRef(false)
  const loading = shallowRef(false)
  const error = shallowRef('')
  const items = shallowRef<SearchItem[]>([])
  const response = shallowRef<SearchResponse | null>(null)
  let generation = 0
  let controller: AbortController | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  const release = (cursor?: string) => { if (cursor) void searchApi.close(cursor).catch(() => {}) }
  const reset = () => {
    generation++
    controller?.abort()
    clearTimeout(timer)
    release(response.value?.session_cursor)
    response.value = null
    items.value = []
    loading.value = false
    error.value = ''
  }
  const execute = async (more = false) => {
    const text = query.value.trim()
    if (!open.value || composing.value || text.length < 2 || text.length > 200 || (more && !response.value?.next_cursor)) return
    controller?.abort()
    controller = new AbortController()
    const token = ++generation
    loading.value = true
    error.value = ''
    try {
      const result = await searchApi.query({ q: text, retrieval: retrieval.value, type: kind.value,
        ...(more ? { cursor: response.value!.next_cursor! } : {}) }, controller.signal)
      if (token !== generation || !open.value) { release(result.session_cursor); return }
      items.value = more ? [...items.value, ...result.items] : result.items
      response.value = result
    } catch (err: any) {
      if (token === generation && !controller.signal.aborted) {
        const code = err.response?.data?.detail
        error.value = code === 'SEARCH_SEMANTIC_NOT_READY' ? '语义索引尚未就绪，请选择关键词模式。'
          : err.response?.status === 410 ? '搜索结果已过期，请重新搜索。' : '搜索暂不可用，请稍后重试。'
      }
    } finally { if (token === generation) loading.value = false }
  }
  watch([query, retrieval, kind, composing, open], () => {
    reset()
    if (open.value && !composing.value) timer = setTimeout(() => void execute(), 300)
  })
  onScopeDispose(reset)
  return { query, retrieval, kind, composing, loading, error, items, response, reset, execute }
}
