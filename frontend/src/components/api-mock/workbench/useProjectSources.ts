import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import type { ApiMockJob } from '@/types/apiMock'
import type { ProjectContext } from './useProjectContext'
import type { ProjectJobs } from './useProjectJobs'
import type { WorkbenchNotifications } from './notifications'

export function useProjectSources(context: ProjectContext, notifications: WorkbenchNotifications, jobs: ProjectJobs, refresh: ProjectContext["refreshProjectContext"]) {
  const { wsId, selectedTaskId } = context
  const { isProjectSwaggerMutationLocked, waitForJobDone, loadActiveJobs, isAutoMockRunning, observedJobs, acceptJobState, AUTO_MOCK_JOB_TYPE, fetchJobSnapshot, activeJob, toActiveJobState } = jobs

  const { notifyProjectSwaggerLocked, isAutoMockProjectLockError, notifyError, notifySuccess } = notifications

  const { contextVersion, endpointIdentity, selectedEndpoint, selectedEndpointId, project } = context

  const { t } = useI18n()

  const syncBusy = ref(false)

  const importBusy = ref(false)

  const cancelJobBusy = ref(false)

  const autoMockStartBusy = ref(false)

  const onSync = async () => {
    if (!selectedTaskId.value) return
    if (isProjectSwaggerMutationLocked.value) {
      notifyProjectSwaggerLocked()
      return
    }
    const version = contextVersion.value
    syncBusy.value = true
    try {
      const res = await api.post(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/sync`)
      if (version !== contextVersion.value) return
      if (!await waitForJobDone(res.data.job_id, 'SYNC_TASK_SOURCE', t('api_mock.sync_queued'))) return
      if (version !== contextVersion.value) return
      await refresh({ preserveKey: endpointIdentity(selectedEndpoint.value) })
    } catch (err) {
      if (version !== contextVersion.value) return
      if (isAutoMockProjectLockError(err)) {
        notifyProjectSwaggerLocked()
        await loadActiveJobs()
        return
      }
      notifyError(err, t('api_mock.sync_failed'))
    } finally {
      if (version === contextVersion.value) syncBusy.value = false
    }
  }

  const onImportSwagger = async (payload: { source_name?: string; raw_content?: string; file?: File | null }) => {
    if (!selectedTaskId.value) return
    if (isProjectSwaggerMutationLocked.value) {
      notifyProjectSwaggerLocked()
      return
    }
    const version = contextVersion.value
    importBusy.value = true
    try {
      const formData = new FormData()
      if (payload.source_name) formData.append('source_name', payload.source_name)
      if (payload.raw_content) formData.append('raw_content', payload.raw_content)
      if (payload.file) {
        formData.append('file', payload.file, payload.file.name)
      }

      const res = await api.post(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/swagger/import`, formData)
      if (version !== contextVersion.value) return
      if (!await waitForJobDone(res.data.job_id, 'IMPORT_SWAGGER', t('api_mock.import_queued'))) return
      if (version !== contextVersion.value) return
      await refresh({ preserveKey: endpointIdentity(selectedEndpoint.value) })
    } catch (err) {
      if (version !== contextVersion.value) return
      if (isAutoMockProjectLockError(err)) {
        notifyProjectSwaggerLocked()
        await loadActiveJobs()
        return
      }
      notifyError(err, t('api_mock.import_failed'))
    } finally {
      if (version === contextVersion.value) importBusy.value = false
    }
  }

  const onStartAutoMock = async () => {
    if (!selectedTaskId.value || !selectedEndpointId.value) return
    if (isAutoMockRunning.value) {
      ElMessage({
        type: 'warning',
        message: t('api_mock.ai_auto_mock_running'),
        duration: 2200,
        grouping: true,
      })
      return
    }
    const version = contextVersion.value
    const endpointId = selectedEndpointId.value
    autoMockStartBusy.value = true
    try {
      const res = await api.post(
        `/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/endpoints/${endpointId}/auto-mock`,
      )
      if (version !== contextVersion.value) return
      const jobId = String(res.data?.job_id || '').trim()
      if (!observedJobs.value[jobId]) acceptJobState({
        id: jobId,
        job_type: AUTO_MOCK_JOB_TYPE,
        status: 'PENDING',
        progress: 0,
        message: String(res.data?.message || t('api_mock.ai_auto_mock_running')),
        result_json: { target_endpoint_id: endpointId },
      })
      if (version !== contextVersion.value) return
      notifySuccess(t('api_mock.ai_auto_mock_started'))
      await fetchJobSnapshot(jobId, wsId.value, selectedTaskId.value)
    } catch (err) {
      if (version !== contextVersion.value) return
      if (isAutoMockProjectLockError(err)) {
        ElMessage({
          type: 'warning',
          message: t('api_mock.ai_auto_mock_locked_project_swagger_mutation'),
          duration: 2600,
          grouping: true,
        })
        await loadActiveJobs()
        return
      }
      notifyError(err, t('api_mock.ai_auto_mock_start_failed'))
    } finally {
      if (version === contextVersion.value) autoMockStartBusy.value = false
    }
  }

  const onCancelActiveJob = async () => {
    if (!selectedTaskId.value || !activeJob.value?.id) return
    cancelJobBusy.value = true
    const version = contextVersion.value
    try {
      const res = await api.post(
        `/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/jobs/${activeJob.value.id}/cancel`,
      )
      if (version !== contextVersion.value) return
      const parsedJob = toActiveJobState(res.data as ApiMockJob)
      if (parsedJob) {
        acceptJobState(parsedJob)
      }
      if (version !== contextVersion.value) return
      notifySuccess(t('api_mock.cancel_requested'))
    } catch (err) {
      if (version !== contextVersion.value) return
      notifyError(err, t('api_mock.cancel_failed'))
    } finally {
      if (version === contextVersion.value) cancelJobBusy.value = false
    }
  }

  const onActivateSource = async (sourceVersionId: string) => {
    if (!selectedTaskId.value) return
    if (isProjectSwaggerMutationLocked.value) {
      notifyProjectSwaggerLocked()
      return
    }
    const version = contextVersion.value
    try {
      const preserveKey = endpointIdentity(selectedEndpoint.value)
      await api.post(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/sources/activate`, {
        source_version_id: sourceVersionId,
      })
      if (version !== contextVersion.value) return
      notifySuccess(t('api_mock.source_switched'))
      await refresh({ preserveKey })
    } catch (err) {
      if (version !== contextVersion.value) return
      if (isAutoMockProjectLockError(err)) {
        notifyProjectSwaggerLocked()
        await loadActiveJobs()
        return
      }
      notifyError(err, t('api_mock.switch_source_failed'))
    }
  }

  const onUpdateProxy = async (payload: { proxy_enabled: boolean; proxy_base_url: string }) => {
    if (!selectedTaskId.value) return
    const version = contextVersion.value
    try {
      await api.put(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}`, payload)
      if (version !== contextVersion.value) return
      if (project.value) {
        project.value.proxy_enabled = payload.proxy_enabled
        project.value.proxy_base_url = payload.proxy_base_url
      }
      if (version !== contextVersion.value) return
      notifySuccess(t('api_mock.proxy_saved'))
    } catch (err) {
      if (version !== contextVersion.value) return
      notifyError(err, t('api_mock.proxy_save_failed'))
    }
  }

  watch(contextVersion, () => { syncBusy.value = false; importBusy.value = false; cancelJobBusy.value = false; autoMockStartBusy.value = false }, { flush: 'sync' })

  return { syncBusy, importBusy, cancelJobBusy, autoMockStartBusy, onSync, onImportSwagger, onStartAutoMock, onCancelActiveJob, onActivateSource, onUpdateProxy }
}

export type ProjectSources = ReturnType<typeof useProjectSources>
