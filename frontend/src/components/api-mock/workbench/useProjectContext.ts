import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import type { ApiMockDocument, ApiMockEndpoint, ApiMockEntity, ApiMockMockCase, ApiMockProject, ApiMockSourceVersion } from '@/types/apiMock'
import type { Ref } from 'vue'
import type { WorkbenchNotifications } from './notifications'

export function useProjectContext(wsId: Ref<string>, selectedTaskId: Ref<string>, notifications: WorkbenchNotifications) {
  const { notifyError } = notifications

  const { t } = useI18n()

  const project = ref<ApiMockProject | null>(null)

  const sourceVersions = ref<ApiMockSourceVersion[]>([])

  const endpoints = ref<ApiMockEndpoint[]>([])

  const endpointCache = ref<Record<string, ApiMockEndpoint>>({})

  const entities = ref<ApiMockEntity[]>([])

  const mockCases = ref<ApiMockMockCase[]>([])

  const selectedEndpointId = ref('')

  const selectedMockCaseId = ref('')

  const documentData = ref<ApiMockDocument | null>(null)

  const loading = ref(false)

  const documentLoading = ref(false)

  const endpointKeyword = ref('')

  let keywordTimer: number | null = null

  const contextVersion = ref(0)
  let endpointRequest = 0
  let caseRequest = 0
  let documentRequest = 0

  const selectedEndpoint = computed(() => {
    if (!selectedEndpointId.value) return null
    const fromVisibleList = endpoints.value.find((item) => item.id === selectedEndpointId.value)
    if (fromVisibleList) return fromVisibleList
    return endpointCache.value[selectedEndpointId.value] || null
  })

  const currentSource = computed(() => sourceVersions.value.find((item) => item.is_active) || null)

  const currentSourceLabel = computed(() => {
    if (!selectedTaskId.value) return t('api_mock.task_empty')
    if (!currentSource.value) return t('api_mock.source_empty_hint')
    return `${currentSource.value.source_type} · ${currentSource.value.source_name || currentSource.value.id.slice(0, 8)}`
  })

  const endpointIdentity = (endpoint: ApiMockEndpoint | null | undefined) =>
    endpoint ? `${endpoint.method.toUpperCase()} ${endpoint.path}` : ''

  const resetTaskContext = () => {
    contextVersion.value += 1
    loading.value = false
    documentLoading.value = false
    if (keywordTimer !== null) {
      window.clearTimeout(keywordTimer)
      keywordTimer = null
    }
    project.value = null
    sourceVersions.value = []
    endpoints.value = []
    endpointCache.value = {}
    entities.value = []
    mockCases.value = []
    selectedEndpointId.value = ''
    selectedMockCaseId.value = ''
    documentData.value = null
  }

  const loadProject = async () => {
    if (!selectedTaskId.value) return null
    const version = contextVersion.value
    const res = await api.get(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}`)
    if (version !== contextVersion.value) return
    project.value = res.data
    return res.data as ApiMockProject
  }

  const loadSourceVersions = async () => {
    if (!selectedTaskId.value) return []
    const version = contextVersion.value
    const res = await api.get(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/source-versions`)
    if (version !== contextVersion.value) return
    sourceVersions.value = res.data.items || []
    return sourceVersions.value
  }

  const loadEndpoints = async () => {
    const request = ++endpointRequest
    if (!selectedTaskId.value) return []
    const version = contextVersion.value
    const res = await api.get(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/endpoints`, {
      params: { keyword: endpointKeyword.value || undefined },
    })
    if (version !== contextVersion.value) return
    if (request !== endpointRequest) return
    endpoints.value = res.data.items || []
    if (endpoints.value.length > 0) {
      const nextCache = { ...endpointCache.value }
      for (const endpoint of endpoints.value) {
        nextCache[endpoint.id] = endpoint
      }
      endpointCache.value = nextCache
    }
    return endpoints.value
  }

  const loadEntities = async () => {
    if (!selectedTaskId.value) return []
    const version = contextVersion.value
    const res = await api.get(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/entities`)
    if (version !== contextVersion.value) return
    entities.value = res.data.items || []
    return entities.value
  }

  const loadDocument = async () => {
    const request = ++documentRequest
    if (!project.value?.id || !currentSource.value) {
      documentData.value = null
      return
    }
    const version = contextVersion.value
    documentLoading.value = true
    try {
      const res = await api.get(`/workspaces/${wsId.value}/api-mock/projects/${project.value.id}/document`)
      if (version !== contextVersion.value) return
      if (request !== documentRequest) return
      documentData.value = res.data
    } catch (err) {
      if (version !== contextVersion.value) return
      documentData.value = null
      notifyError(err, t('api_mock.document_load_failed'))
    } finally {
      if (version === contextVersion.value && request === documentRequest) documentLoading.value = false
    }
  }

  const loadMockCases = async (options?: { fallbackToFirst?: boolean }) => {
    const request = ++caseRequest
    const endpointId = selectedEndpointId.value
    if (!selectedEndpointId.value) {
      mockCases.value = []
      selectedMockCaseId.value = ''
      return
    }
    const version = contextVersion.value
    const res = await api.get(`/workspaces/${wsId.value}/api-mock/endpoints/${endpointId}/mock-cases`)
    if (version !== contextVersion.value) return
    if (request !== caseRequest || endpointId !== selectedEndpointId.value) return
    mockCases.value = res.data.items || []
    const shouldFallbackToFirst = options?.fallbackToFirst === true
    if (!mockCases.value.some((item) => item.id === selectedMockCaseId.value)) {
      selectedMockCaseId.value = shouldFallbackToFirst ? (mockCases.value[0]?.id || '') : ''
    }
  }

  const refreshProjectContext = async (options?: { preserveKey?: string; explicitEndpointId?: string }) => {
    if (!selectedTaskId.value) return
    const version = contextVersion.value
    loading.value = true
    try {
      await loadProject()
      if (version !== contextVersion.value) return
      await Promise.all([loadSourceVersions(), loadEndpoints(), loadEntities()])
      if (version !== contextVersion.value) return
      const explicitEndpointId = options?.explicitEndpointId || ''
      if (explicitEndpointId && endpoints.value.some((item) => item.id === explicitEndpointId)) {
        selectedEndpointId.value = explicitEndpointId
      } else if (options?.preserveKey) {
        const matched = endpoints.value.find((item) => endpointIdentity(item) === options.preserveKey)
        selectedEndpointId.value = matched?.id || ''
      } else if (!endpoints.value.some((item) => item.id === selectedEndpointId.value)) {
        selectedEndpointId.value = ''
      }
      await loadMockCases()
      if (version !== contextVersion.value) return
      await loadDocument()
      if (version !== contextVersion.value) return
    } finally {
      if (version === contextVersion.value) loading.value = false
    }
  }

  watch(endpointKeyword, () => {
      endpointRequest += 1
      if (!selectedTaskId.value) return
      if (keywordTimer !== null) window.clearTimeout(keywordTimer)
      keywordTimer = window.setTimeout(() => { keywordTimer = null; void loadEndpoints() }, 260)
    })
    onBeforeUnmount(() => { contextVersion.value += 1; if (keywordTimer !== null) window.clearTimeout(keywordTimer) })

  return { project, sourceVersions, endpoints, endpointCache, entities, mockCases, selectedEndpointId, selectedMockCaseId, documentData, loading, documentLoading, endpointKeyword, contextVersion, selectedEndpoint, currentSource, currentSourceLabel, endpointIdentity, resetTaskContext, loadProject, loadSourceVersions, loadEndpoints, loadEntities, loadDocument, loadMockCases, refreshProjectContext, wsId, selectedTaskId }
}

export type ProjectContext = ReturnType<typeof useProjectContext>
