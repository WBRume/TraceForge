import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import type { ApiMockJob } from '@/types/apiMock'
import type { ActiveJobState, ApiMockJobListResponse } from './types'
import type { ProjectContext } from './useProjectContext'
import type { WorkbenchNotifications } from './notifications'

export function useProjectJobs(context: ProjectContext, notifications: WorkbenchNotifications) {
  const { wsId, selectedTaskId } = context
  const { selectedEndpointId, selectedMockCaseId, loadMockCases, contextVersion } = context

  const { notifySuccess } = notifications

  const { t } = useI18n()

  const AUTO_MOCK_JOB_TYPE = 'AUTO_GENERATE_MOCK_CASES'

  const activeJob = ref<ActiveJobState | null>(null)

  const activeAutoMockJob = ref<ActiveJobState | null>(null)

  const handledAutoMockDoneJobIds = new Set<string>()

  const observedJobs = ref<Record<string, ActiveJobState>>({})

  const isAutoMockRunning = computed(() => {
    const status = activeAutoMockJob.value?.status || ''
    return status === 'PENDING' || status === 'RUNNING'
  })

  const autoMockTargetEndpointId = computed(() => {
    const payload = activeAutoMockJob.value?.result_json
    if (!payload || typeof payload !== 'object') return ''
    return String((payload as Record<string, unknown>).target_endpoint_id || '').trim()
  })

  const isCurrentEndpointAutoMockLocked = computed(
    () => isAutoMockRunning.value && !!selectedEndpointId.value && autoMockTargetEndpointId.value === selectedEndpointId.value,
  )

  const isProjectSwaggerMutationLocked = computed(() => isAutoMockRunning.value)

  const normalizeJobStatus = (value: unknown): ActiveJobState['status'] => {
    const status = String(value || '').toUpperCase()
    if (status === 'RUNNING' || status === 'SUCCESS' || status === 'FAILED' || status === 'PENDING') {
      return status
    }
    return 'PENDING'
  }

  const sanitizeJobResultJson = (value: unknown): Record<string, unknown> | null => {
    if (!value || typeof value !== 'object') return null
    return { ...(value as Record<string, unknown>) }
  }

  const toActiveJobState = (value: unknown): ActiveJobState | null => {
    if (!value || typeof value !== 'object') return null
    const job = value as Record<string, unknown>
    const id = String(job.id || '').trim()
    const jobType = String(job.job_type || '').trim()
    if (!id || !jobType) return null
    return {
      id,
      job_type: jobType,
      status: normalizeJobStatus(job.status),
      progress: Number(job.progress || 0),
      message: typeof job.message === 'string' ? job.message : null,
      result_json: sanitizeJobResultJson(job.result_json),
    }
  }

  const mergeIncomingJobState = (incoming: ActiveJobState) => {
    const current = activeJob.value
    if (!current) {
      activeJob.value = incoming
      return
    }
    if (current.id === incoming.id) {
      activeJob.value = incoming
      return
    }
    const currentDone = current.status === 'SUCCESS' || current.status === 'FAILED'
    if (currentDone) {
      activeJob.value = incoming
    }
  }

  const mergeIncomingAutoMockJobState = (incoming: ActiveJobState) => {
    if (incoming.job_type !== AUTO_MOCK_JOB_TYPE) return
    if (incoming.status === 'PENDING' || incoming.status === 'RUNNING') {
      activeAutoMockJob.value = incoming
      return
    }
    if (activeAutoMockJob.value?.id === incoming.id) {
      activeAutoMockJob.value = null
    }
  }

  const acceptJobState = (incoming: ActiveJobState) => {
    const previous = observedJobs.value[incoming.id]
    if (previous?.status === 'SUCCESS' || previous?.status === 'FAILED') return
    observedJobs.value = { ...observedJobs.value, [incoming.id]: incoming }
    mergeIncomingJobState(incoming)
    mergeIncomingAutoMockJobState(incoming)
    if (incoming.status === 'SUCCESS' || incoming.status === 'FAILED') handleAutoMockJobCompletion(incoming)
  }

  const handleAutoMockJobCompletion = (parsedJob: ActiveJobState) => {
    if (parsedJob.job_type !== AUTO_MOCK_JOB_TYPE) return
    if (parsedJob.status !== 'SUCCESS' && parsedJob.status !== 'FAILED') return

    if (!handledAutoMockDoneJobIds.has(parsedJob.id)) {
      handledAutoMockDoneJobIds.add(parsedJob.id)
      if (parsedJob.status === 'SUCCESS') {
        const payload = parsedJob.result_json || {}
        const created = Number((payload as Record<string, unknown>).created_count || 0)
        const updated = Number((payload as Record<string, unknown>).updated_count || 0)
        notifySuccess(
          t('api_mock.ai_auto_mock_done_summary', {
            created: Number.isFinite(created) ? created : 0,
            updated: Number.isFinite(updated) ? updated : 0,
          }),
        )
      } else {
        ElMessage({
          type: 'error',
          message: parsedJob.message || t('api_mock.ai_auto_mock_failed'),
          duration: 2600,
          grouping: true,
        })
      }
    }

    const targetEndpointId = String((parsedJob.result_json?.target_endpoint_id as string) || '').trim()
    if (targetEndpointId && targetEndpointId === selectedEndpointId.value) {
      selectedMockCaseId.value = ''
      void loadMockCases()
    }
  }

  const loadActiveJobs = async () => {
    if (!selectedTaskId.value) {
      activeJob.value = null
      activeAutoMockJob.value = null
      return []
    }
    const version = contextVersion.value
    const workspaceId = wsId.value
    const taskId = selectedTaskId.value
    const trackedIds = Object.values(observedJobs.value)
      .filter((job) => job.status === 'PENDING' || job.status === 'RUNNING').map((job) => job.id)
    const res = await api.get(`/workspaces/${workspaceId}/api-mock/projects/${taskId}/jobs`, {
      params: {
        active_only: true,
        limit: 50,
      },
    })
    if (version !== contextVersion.value) return []
    const items = ((res.data as ApiMockJobListResponse)?.items || [])
      .map((item) => toActiveJobState(item))
      .filter((item): item is ActiveJobState => Boolean(item))
    for (const job of items) acceptJobState(job)
    // Active-only lists omit jobs completed while disconnected. Recover those once.
    await Promise.all(trackedIds.filter((id) => !items.some((job) => job.id === id))
      .map((id) => fetchJobSnapshot(id, workspaceId, taskId)))
    return items
  }

  const fetchJobSnapshot = async (jobId: string, workspaceId: string, taskId: string) => {
    const version = contextVersion.value
    const res = await api.get(`/workspaces/${workspaceId}/api-mock/projects/${taskId}/jobs/${jobId}`)
    if (version !== contextVersion.value) return null
    const parsedJob = toActiveJobState(res.data as ApiMockJob)
    if (parsedJob) {
      acceptJobState(parsedJob)
    }
    return parsedJob
  }

  const waitForJobDone = async (jobId: string, jobType: ActiveJobState['job_type'], queuedMessage: string) => {
    const version = contextVersion.value
    if (!observedJobs.value[jobId]) {
      acceptJobState({ id: jobId, job_type: jobType, status: 'PENDING', progress: 0,
        message: queuedMessage, result_json: null })
    }
    return new Promise<boolean>((resolve, reject) => {
      const finish = (error?: Error, completed = false) => {
        stop()
        window.clearTimeout(timer)
        if (error) reject(error)
        else resolve(completed)
      }
      const check = () => {
        if (version !== contextVersion.value) return finish()
        const job = observedJobs.value[jobId]
        if (job?.status === 'SUCCESS') {
          notifySuccess(t('api_mock.job_success'))
          finish(undefined, true)
        } else if (job?.status === 'FAILED') {
          finish(new Error(job.result_json?.cancelled ? t('api_mock.job_cancelled') :
            (job.message || t('api_mock.job_failed'))))
        }
      }
      const stop = watch([() => observedJobs.value[jobId], contextVersion], check, { flush: 'sync' })
      const timer = window.setTimeout(() => finish(new Error(t('api_mock.job_timeout'))), 6 * 60 * 1000)
      check()
      if (observedJobs.value[jobId]?.status === 'PENDING' || observedJobs.value[jobId]?.status === 'RUNNING') {
        // Covers a job that completed before the POST response / subscription.
        void fetchJobSnapshot(jobId, wsId.value, selectedTaskId.value).catch(() => {
          // The existing WS connection / reconnect snapshot will recover state.
        })
      }
    })
  }

  watch(contextVersion, () => {
      observedJobs.value = {}; activeJob.value = null; activeAutoMockJob.value = null; handledAutoMockDoneJobIds.clear()
    }, { flush: 'sync' })

  return { AUTO_MOCK_JOB_TYPE, activeJob, activeAutoMockJob, observedJobs, isAutoMockRunning, autoMockTargetEndpointId, isCurrentEndpointAutoMockLocked, isProjectSwaggerMutationLocked, normalizeJobStatus, sanitizeJobResultJson, toActiveJobState, mergeIncomingJobState, mergeIncomingAutoMockJobState, acceptJobState, handleAutoMockJobCompletion, loadActiveJobs, fetchJobSnapshot, waitForJobDone }
}

export type ProjectJobs = ReturnType<typeof useProjectJobs>
