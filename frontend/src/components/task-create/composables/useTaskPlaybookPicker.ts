import { computed, shallowRef, watch } from 'vue'
import api from '@/utils/api'
import type { PlaybookSpec } from '@/types/diagnosisPlaybook'

export type PlaybookRecommendation = PlaybookSpec & { reasons: string[]; score: number }
export function useTaskPlaybookPicker(options: {
  open: () => boolean; workspaceId: () => string; name: () => string
  description: () => string; taskType: () => 'DEVELOPMENT' | 'DIAGNOSIS'
}) {
  const items = shallowRef<PlaybookRecommendation[]>([])
  const keyword = shallowRef('')
  const page = shallowRef(1)
  const total = shallowRef(0)
  const loading = shallowRef(false)
  const error = shallowRef('')
  const revision = shallowRef(0)
  const pageSize = 8
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
  watch([options.workspaceId, options.name, options.description, options.taskType, keyword], () => { page.value = 1 }, { flush: 'sync' })
  watch([options.open, options.workspaceId, options.name, options.description, options.taskType, keyword, page, revision], (_value, _old, cleanup) => {
    loading.value = false
    if (!options.open() || !options.workspaceId()) return
    const abort = new AbortController()
    let active = true
    loading.value = true
    error.value = ''
    const timer = setTimeout(async () => {
      try {
        const { data } = await api.post(`/workspaces/${options.workspaceId()}/playbook-recommendations`, {
          name: options.name(), description: options.description(), task_type: options.taskType(),
          keyword: keyword.value.trim(), page: page.value, page_size: pageSize,
        }, { signal: abort.signal })
        if (!active) return
        items.value = Array.isArray(data.items) ? data.items : []
        total.value = Number(data.total || 0)
        if (page.value > totalPages.value) page.value = totalPages.value
      } catch {
        if (active) { items.value = []; error.value = '规程加载失败，请重试。也可不选规程直接创建任务。' }
      } finally {
        if (active) loading.value = false
      }
    }, 300)
    cleanup(() => { active = false; clearTimeout(timer); abort.abort() })
  }, { immediate: true })
  return { items, keyword, page, total, totalPages, loading, error, refresh: () => revision.value++ }
}
