import { computed, ref } from 'vue'
import api from '@/utils/api'
import type { ContextTokenCategory, ContextWindowResponse } from '@/types/contextWindow'

type ContextWindowOptions = {
  getWorkspaceId: () => string
  getTaskId: () => string
  getAiJobId?: () => string | null | undefined
}

export function useTaskContextWindow(options: ContextWindowOptions) {
  const data = ref<ContextWindowResponse | null>(null)
  const loading = ref(false)
  const segmentsLoading = ref(false)
  const error = ref<string | null>(null)
  const selectedCategory = ref<string | null>(null)
  const page = ref(1)
  const pageSize = ref(50)

  const hasSnapshot = computed(() => Boolean(data.value?.snapshot?.id))
  const categories = computed(() => data.value?.categories || [])
  const segments = computed(() => data.value?.segments || [])
  const providerTokens = computed(() => data.value?.provider_tokens || {
    available: false,
    status: 'unavailable',
  })

  const buildParams = (category?: string | null, targetPage = 1) => {
    const params: Record<string, string | number> = {
      page: targetPage,
      page_size: pageSize.value,
    }
    const aiJobId = String(options.getAiJobId?.() || '').trim()
    if (aiJobId) params.ai_job_id = aiJobId
    if (category) params.category = category
    return params
  }

  const fetchContextWindow = async (category?: string | null, targetPage = 1, mode: 'summary' | 'segments' = 'summary') => {
    const wsId = String(options.getWorkspaceId() || '').trim()
    const taskId = String(options.getTaskId() || '').trim()
    if (!wsId || !taskId) return
    if (mode === 'segments') {
      segmentsLoading.value = true
    } else {
      loading.value = true
    }
    error.value = null
    try {
      const res = await api.get(`/workspaces/${wsId}/tasks/${taskId}/context-window`, {
        params: buildParams(category, targetPage),
      })
      data.value = res.data as ContextWindowResponse
      selectedCategory.value = category || null
      page.value = targetPage
    } catch (err: any) {
      error.value = err?.response?.data?.detail || err?.message || 'Failed to load context window'
    } finally {
      loading.value = false
      segmentsLoading.value = false
    }
  }

  const load = async () => {
    await fetchContextWindow(selectedCategory.value, page.value, selectedCategory.value ? 'segments' : 'summary')
  }

  const loadSummary = async () => {
    selectedCategory.value = null
    page.value = 1
    await fetchContextWindow(null, 1, 'summary')
  }

  const loadCategory = async (category: ContextTokenCategory | string, targetPage = 1) => {
    await fetchContextWindow(String(category), targetPage, 'segments')
  }

  const reset = () => {
    data.value = null
    loading.value = false
    segmentsLoading.value = false
    error.value = null
    selectedCategory.value = null
    page.value = 1
  }

  return {
    categories,
    data,
    error,
    hasSnapshot,
    load,
    loadCategory,
    loadSummary,
    loading,
    page,
    pageSize,
    providerTokens,
    reset,
    segments,
    segmentsLoading,
    selectedCategory,
  }
}
