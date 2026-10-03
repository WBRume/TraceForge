import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import type { ProjectContext } from './useProjectContext'
import type { ProjectJobs } from './useProjectJobs'
import type { WorkbenchNotifications } from './notifications'
import type { ProjectCollaboration } from './useProjectCollaboration'

export function useProjectEditing(context: ProjectContext, notifications: WorkbenchNotifications, jobs: ProjectJobs, collaboration: ProjectCollaboration, refresh: ProjectContext["refreshProjectContext"]) {
  const { wsId, selectedTaskId } = context
  const { selectedEndpointId, contextVersion, project, endpointIdentity, selectedEndpoint, selectedMockCaseId, loadMockCases, loadEntities } = context

  const { isProjectSwaggerMutationLocked, loadActiveJobs, isCurrentEndpointAutoMockLocked } = jobs

  const { notifyProjectSwaggerLocked, notifySuccess, isAutoMockProjectLockError, isConflictError, notifyError, notifyCurrentEndpointCreateLocked, isAutoMockEndpointLockError } = notifications

  const { sendCollabEvent } = collaboration

  const { t } = useI18n()

  const savingEndpoint = ref(false)

  const savingDocument = ref(false)

  const savingCase = ref(false)

  const deletingCase = ref(false)

  const onSaveEndpoint = async (payload: {
    row_version: number
    method: string
    path: string
    operation_id: string | null
    tag: string | null
    summary: string | null
    parameters_json: Array<Record<string, unknown>> | null
    request_schema_json: Record<string, unknown> | null
    responses_json: Record<string, unknown> | null
    response_schema_json: Record<string, unknown> | null
    entity_refs_json: string[] | null
  }) => {
    if (!selectedTaskId.value || !selectedEndpointId.value) return
    if (isProjectSwaggerMutationLocked.value) {
      notifyProjectSwaggerLocked()
      return
    }
    savingEndpoint.value = true
    const version = contextVersion.value
    const endpointId = selectedEndpointId.value
    try {
      const res = await api.put(
        `/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/endpoints/${endpointId}`,
        payload,
      )
      if (version !== contextVersion.value || endpointId !== selectedEndpointId.value) return
      selectedEndpointId.value = res.data.id
      await refresh({ explicitEndpointId: res.data.id })
      if (version !== contextVersion.value || endpointId !== selectedEndpointId.value) return
      sendCollabEvent('save', { endpoint_id: res.data.id, target: 'endpoint' })
      if (version !== contextVersion.value || endpointId !== selectedEndpointId.value) return
      notifySuccess(t('api_mock.endpoint_saved'))
    } catch (err) {
      if (version !== contextVersion.value) return
      if (isAutoMockProjectLockError(err)) {
        notifyProjectSwaggerLocked()
        await loadActiveJobs()
        return
      }
      if (isConflictError(err)) {
        sendCollabEvent('conflict', { endpoint_id: selectedEndpointId.value, target: 'endpoint' })
        await refresh({ preserveKey: `${payload.method.toUpperCase()} ${payload.path}` })
        notifyError(err, t('api_mock.conflict_detected'))
      } else {
        notifyError(err, t('api_mock.endpoint_save_failed'))
      }
    } finally {
      if (version === contextVersion.value) savingEndpoint.value = false
    }
  }

  const onSaveDocument = async (payload: { content: string }) => {
    if (!project.value?.id) return
    if (isProjectSwaggerMutationLocked.value) {
      notifyProjectSwaggerLocked()
      return
    }
    savingDocument.value = true
    const preserveKey = endpointIdentity(selectedEndpoint.value)
    const version = contextVersion.value
    try {
      await api.put(`/workspaces/${wsId.value}/api-mock/projects/${project.value.id}/document`, payload)
      if (version !== contextVersion.value) return
      await refresh({ preserveKey })
      if (version !== contextVersion.value) return
      sendCollabEvent('save', { endpoint_id: selectedEndpointId.value, target: 'document' })
      if (version !== contextVersion.value) return
      notifySuccess(t('api_mock.document_saved'))
    } catch (err) {
      if (version !== contextVersion.value) return
      if (isAutoMockProjectLockError(err)) {
        notifyProjectSwaggerLocked()
        await loadActiveJobs()
        return
      }
      notifyError(err, t('api_mock.document_save_failed'))
    } finally {
      if (version === contextVersion.value) savingDocument.value = false
    }
  }

  const onCreateCase = () => {
    if (isCurrentEndpointAutoMockLocked.value) {
      notifyCurrentEndpointCreateLocked()
      return
    }
    selectedMockCaseId.value = ''
  }

  const onSaveCase = async (payload: {
    id?: string
    row_version?: number
    name: string
    description: string | null
    is_default: boolean
    sort_order?: number
    mode: 'STATIC' | 'MOCKJS' | 'PROXY'
    request_path_params_json?: Record<string, unknown> | null
    request_query_json?: Record<string, unknown> | null
    request_body_json?: unknown
    static_body_json?: Record<string, unknown> | null
    mockjs_template?: string | null
    status_code: number
    headers_json?: Record<string, unknown> | null
    cookies_json?: Array<Record<string, unknown>> | null
    delay_ms: number
    enabled: boolean
  }) => {
    if (!selectedEndpointId.value) return
    if (!payload.id && isCurrentEndpointAutoMockLocked.value) {
      notifyCurrentEndpointCreateLocked()
      return
    }
    savingCase.value = true
    const version = contextVersion.value
    const endpointId = selectedEndpointId.value
    try {
      if (payload.id) {
        const res = await api.put(`/workspaces/${wsId.value}/api-mock/mock-cases/${payload.id}`, payload)
        if (version !== contextVersion.value || endpointId !== selectedEndpointId.value) return
        selectedMockCaseId.value = res.data.id
      } else {
        const res = await api.post(`/workspaces/${wsId.value}/api-mock/endpoints/${endpointId}/mock-cases`, payload)
        if (version !== contextVersion.value || endpointId !== selectedEndpointId.value) return
        selectedMockCaseId.value = res.data.id
      }
      if (version !== contextVersion.value || endpointId !== selectedEndpointId.value) return
      await loadMockCases()
      if (version !== contextVersion.value || endpointId !== selectedEndpointId.value) return
      sendCollabEvent('save', { endpoint_id: selectedEndpointId.value, target: 'mock-case' })
      if (version !== contextVersion.value || endpointId !== selectedEndpointId.value) return
      notifySuccess(t('api_mock.mock_case_saved'))
    } catch (err) {
      if (version !== contextVersion.value) return
      if (isAutoMockEndpointLockError(err)) {
        notifyCurrentEndpointCreateLocked()
        await loadActiveJobs()
        return
      }
      if (isConflictError(err)) {
        sendCollabEvent('conflict', { endpoint_id: selectedEndpointId.value, target: 'mock-case' })
        if (version !== contextVersion.value || endpointId !== selectedEndpointId.value) return
        await loadMockCases()
        notifyError(err, t('api_mock.conflict_detected'))
      } else {
        notifyError(err, t('api_mock.mock_case_save_failed'))
      }
    } finally {
      if (version === contextVersion.value) savingCase.value = false
    }
  }

  const onDeleteCase = async (caseId: string) => {
    deletingCase.value = true
    const version = contextVersion.value
    const endpointId = selectedEndpointId.value
    try {
      await api.delete(`/workspaces/${wsId.value}/api-mock/mock-cases/${caseId}`)
      if (version !== contextVersion.value || endpointId !== selectedEndpointId.value) return
      await loadMockCases()
      if (version !== contextVersion.value || endpointId !== selectedEndpointId.value) return
      notifySuccess(t('api_mock.mock_case_deleted'))
    } catch (err) {
      if (version !== contextVersion.value) return
      notifyError(err, t('api_mock.mock_case_delete_failed'))
    } finally {
      if (version === contextVersion.value) deletingCase.value = false
    }
  }

  const onCreateEntity = async (payload: { name: string; description: string | null; schema_json: Record<string, unknown>; endpoint_id: string | null }) => {
    if (!selectedTaskId.value) return
    if (isProjectSwaggerMutationLocked.value) {
      notifyProjectSwaggerLocked()
      return
    }
    const version = contextVersion.value
    try {
      await api.post(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/entities`, {
        name: payload.name,
        description: payload.description,
        schema_json: payload.schema_json,
        endpoint_id: payload.endpoint_id,
      })
      if (version !== contextVersion.value) return
      await loadEntities()
      if (version !== contextVersion.value) return
      notifySuccess(t('api_mock.entity_saved'))
    } catch (err) {
      if (version !== contextVersion.value) return
      if (isAutoMockProjectLockError(err)) {
        notifyProjectSwaggerLocked()
        await loadActiveJobs()
        return
      }
      notifyError(err, t('api_mock.entity_save_failed'))
    }
  }

  const onUpdateEntity = async (payload: { id: string; row_version: number; name: string; description: string | null; schema_json: Record<string, unknown>; endpoint_id: string | null }) => {
    if (!selectedTaskId.value) return
    if (isProjectSwaggerMutationLocked.value) {
      notifyProjectSwaggerLocked()
      return
    }
    const version = contextVersion.value
    try {
      await api.put(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/entities/${payload.id}`, {
        row_version: payload.row_version,
        name: payload.name,
        description: payload.description,
        schema_json: payload.schema_json,
        endpoint_id: payload.endpoint_id,
      })
      if (version !== contextVersion.value) return
      await loadEntities()
      if (version !== contextVersion.value) return
      notifySuccess(t('api_mock.entity_saved'))
    } catch (err) {
      if (version !== contextVersion.value) return
      if (isAutoMockProjectLockError(err)) {
        notifyProjectSwaggerLocked()
        await loadActiveJobs()
        return
      }
      if (isConflictError(err)) {
        if (version !== contextVersion.value) return
        await loadEntities()
        notifyError(err, t('api_mock.conflict_detected'))
      } else {
        notifyError(err, t('api_mock.entity_save_failed'))
      }
    }
  }

  const onDeleteEntity = async (entityId: string) => {
    if (isProjectSwaggerMutationLocked.value) {
      notifyProjectSwaggerLocked()
      return
    }
    const version = contextVersion.value
    try {
      await api.delete(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/entities/${entityId}`)
      if (version !== contextVersion.value) return
      await loadEntities()
      if (version !== contextVersion.value) return
      notifySuccess(t('api_mock.entity_deleted'))
    } catch (err) {
      if (version !== contextVersion.value) return
      if (isAutoMockProjectLockError(err)) {
        notifyProjectSwaggerLocked()
        await loadActiveJobs()
        return
      }
      notifyError(err, t('api_mock.entity_delete_failed'))
    }
  }

  watch(contextVersion, () => { savingEndpoint.value = false; savingDocument.value = false; savingCase.value = false; deletingCase.value = false }, { flush: 'sync' })

  return { savingEndpoint, savingDocument, savingCase, deletingCase, onSaveEndpoint, onSaveDocument, onCreateCase, onSaveCase, onDeleteCase, onCreateEntity, onUpdateEntity, onDeleteEntity }
}

export type ProjectEditing = ReturnType<typeof useProjectEditing>
