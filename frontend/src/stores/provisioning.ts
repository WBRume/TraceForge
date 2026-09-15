import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import api from '@/utils/api'

type PendingTaskSpecUpload = {
  workspaceId: string
  taskId: string
  file: File
}

type PendingTaskDocsUpload = {
  workspaceId: string
  taskId: string
  files: File[]
}

export type ProvisionJobStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'

export type ProvisionJobView = {
  jobId: string
  taskId: string
  workspaceId: string
  taskName: string
  status: ProvisionJobStatus
  stage: string
  progress: number
  message: string
  errorMessage: string
  cancelRequested: boolean
  /** job SUCCESS 且任务状态已确认走到 PENDING（可进入会话） */
  ready: boolean
  /** 轮询终态：SUCCESS / FAILED（含被取消）或连续拉取失败 */
  terminal: boolean
}

type ProvisionJobApiPayload = {
  job_id?: string | null
  job_type?: string | null
  status?: string | null
  stage?: string | null
  progress?: number | null
  message?: string | null
  error_message?: string | null
  cancel_requested?: boolean | null
  workspace_id?: string | null
  task_id?: string | null
  task_name?: string | null
  context_json?: { task_name?: string | null } | null
}

const pendingSpecByJob = new Map<string, PendingTaskSpecUpload>()
const pendingDocsByJob = new Map<string, PendingTaskDocsUpload>()

const POLL_INTERVAL_MS = 1200
const MAX_CONSECUTIVE_FETCH_ERRORS = 10
const TASK_PENDING_POLL_ATTEMPTS = 20
const TASK_PENDING_POLL_INTERVAL_MS = 500
const EXPAND_PREF_KEY = 'provisionWidgetExpanded'

const asJobId = (value: unknown): string => String(value || '').trim()

export const useProvisioningStore = defineStore('provisioning', () => {
  // ── 任务准备浮窗状态（跨路由/刷新存活；刷新后由 restoreFromServer 恢复）──
  const jobs = ref<Record<string, ProvisionJobView>>({})
  const expanded = ref(localStorage.getItem(EXPAND_PREF_KEY) === '1')
  // 终态变化时自增，ChatView 等页面 watch 它来刷新任务列表
  const taskListRefreshToken = ref(0)
  const restored = ref(false)

  let timer: number | null = null
  const inFlight = new Set<string>()
  const fetchErrors = new Map<string, number>()

  const jobList = computed(() => Object.values(jobs.value))
  const hasActiveJobs = computed(() => jobList.value.some((job) => !job.terminal))

  watch(expanded, (value) => {
    localStorage.setItem(EXPAND_PREF_KEY, value ? '1' : '0')
  })

  // ── 创建时暂存的 spec / 诊断文档（job 成功后上传）──
  const setPendingTaskSpec = (jobId: string, payload: PendingTaskSpecUpload) => {
    const normalizedJobId = asJobId(jobId)
    if (!normalizedJobId) return
    pendingSpecByJob.set(normalizedJobId, payload)
  }

  const consumePendingTaskSpec = (jobId: string): PendingTaskSpecUpload | null => {
    const normalizedJobId = asJobId(jobId)
    if (!normalizedJobId) return null
    const payload = pendingSpecByJob.get(normalizedJobId) || null
    if (payload) {
      pendingSpecByJob.delete(normalizedJobId)
    }
    return payload
  }

  const clearPendingTaskSpec = (jobId: string) => {
    const normalizedJobId = asJobId(jobId)
    if (!normalizedJobId) return
    pendingSpecByJob.delete(normalizedJobId)
  }

  /** 问题定位任务：暂存待上传的需求/日志文档（任务创建完成后上传） */
  const setPendingTaskDocs = (jobId: string, payload: PendingTaskDocsUpload) => {
    const normalizedJobId = asJobId(jobId)
    if (!normalizedJobId || !payload.files || payload.files.length === 0) return
    pendingDocsByJob.set(normalizedJobId, payload)
  }

  const consumePendingTaskDocs = (jobId: string): PendingTaskDocsUpload | null => {
    const normalizedJobId = asJobId(jobId)
    if (!normalizedJobId) return null
    const payload = pendingDocsByJob.get(normalizedJobId) || null
    if (payload) {
      pendingDocsByJob.delete(normalizedJobId)
    }
    return payload
  }

  const clearPendingTaskDocs = (jobId: string) => {
    const normalizedJobId = asJobId(jobId)
    if (!normalizedJobId) return
    pendingDocsByJob.delete(normalizedJobId)
  }

  const clearPendingUploads = (jobId: string) => {
    clearPendingTaskSpec(jobId)
    clearPendingTaskDocs(jobId)
  }

  // ── 浮窗 job 跟踪 ──
  const upsertJobFromPayload = (payload: ProvisionJobApiPayload): ProvisionJobView | null => {
    const jobId = asJobId(payload?.job_id)
    if (!jobId) return null
    const existing = jobs.value[jobId]
    const status = (String(payload?.status || '').toUpperCase() as ProvisionJobStatus) || existing?.status || 'PENDING'
    const view: ProvisionJobView = {
      jobId,
      taskId: asJobId(payload?.task_id) || existing?.taskId || '',
      workspaceId: asJobId(payload?.workspace_id) || existing?.workspaceId || '',
      taskName: String(payload?.task_name || payload?.context_json?.task_name || existing?.taskName || ''),
      status,
      stage: String(payload?.stage || existing?.stage || ''),
      progress: Math.max(0, Math.min(Number(payload?.progress ?? existing?.progress ?? 0), 100)),
      message: String(payload?.message || existing?.message || ''),
      errorMessage: String(payload?.error_message || existing?.errorMessage || ''),
      cancelRequested: Boolean(payload?.cancel_requested) || Boolean(existing?.cancelRequested),
      ready: existing?.ready || false,
      terminal: existing?.terminal || false,
    }
    jobs.value = { ...jobs.value, [jobId]: view }
    return view
  }

  const ensureTimer = () => {
    if (timer !== null) return
    timer = window.setInterval(() => {
      for (const job of Object.values(jobs.value)) {
        if (!job.terminal) {
          void fetchJob(job.jobId)
        }
      }
    }, POLL_INTERVAL_MS)
  }

  const stopTimerIfIdle = () => {
    if (timer === null) return
    if (Object.values(jobs.value).some((job) => !job.terminal)) return
    window.clearInterval(timer)
    timer = null
  }

  /** 任务资源 job SUCCESS 后，确认任务状态真正从 PROVISIONING 走到 PENDING */
  const waitForTaskPending = async (workspaceId: string, taskId: string): Promise<boolean> => {
    if (!workspaceId || !taskId) return false
    for (let attempt = 0; attempt < TASK_PENDING_POLL_ATTEMPTS; attempt++) {
      try {
        const res = await api.get(`/workspaces/${workspaceId}/tasks/${taskId}`)
        const status = String(res.data?.status || '')
        if (status === 'PENDING') return true
        if (['FAILED', 'DONE', 'BASELINED'].includes(status)) return false
      } catch (err: unknown) {
        // 任务已被回滚删除（取消/失败）时直接结束
        if ((err as { response?: { status?: number } })?.response?.status === 404) return false
      }
      await new Promise((resolve) => window.setTimeout(resolve, TASK_PENDING_POLL_INTERVAL_MS))
    }
    return false
  }

  const uploadPendingFiles = async (job: ProvisionJobView) => {
    const pendingSpec = consumePendingTaskSpec(job.jobId)
    if (pendingSpec) {
      const formData = new FormData()
      formData.append('file', pendingSpec.file)
      try {
        await api.post(
          `/workspaces/${pendingSpec.workspaceId}/tasks/${pendingSpec.taskId}/upload-spec`,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' } },
        )
      } catch (err) {
        console.warn('Pending spec upload failed', err)
      }
    }

    const pendingDocs = consumePendingTaskDocs(job.jobId)
    if (pendingDocs && pendingDocs.files.length > 0) {
      for (const file of pendingDocs.files) {
        const formData = new FormData()
        formData.append('file', file)
        try {
          await api.post(
            `/workspaces/${pendingDocs.workspaceId}/tasks/${pendingDocs.taskId}/upload-diagnosis-doc`,
            formData,
            { headers: { 'Content-Type': 'multipart/form-data' } },
          )
        } catch (err) {
          console.warn('Pending diagnosis doc upload failed', err)
        }
      }
    }
  }

  const finalizeSuccess = async (job: ProvisionJobView) => {
    await uploadPendingFiles(job)
    const taskReady = await waitForTaskPending(job.workspaceId, job.taskId)
    const current = jobs.value[job.jobId]
    if (current) {
      jobs.value = {
        ...jobs.value,
        [job.jobId]: {
          ...current,
          ready: taskReady,
          errorMessage: taskReady ? '' : 'task_status_not_ready',
          terminal: true,
        },
      }
    }
    clearPendingUploads(job.jobId)
    taskListRefreshToken.value += 1
  }

  const fetchJob = async (jobId: string) => {
    const normalizedJobId = asJobId(jobId)
    if (!normalizedJobId || inFlight.has(normalizedJobId)) return
    inFlight.add(normalizedJobId)
    try {
      const res = await api.get(`/provision-jobs/${normalizedJobId}`)
      const payload = res.data as ProvisionJobApiPayload
      const view = upsertJobFromPayload(payload)
      fetchErrors.delete(normalizedJobId)
      if (!view) return

      const isCancelledJob = String(view.stage || '').toUpperCase() === 'CANCELLED'
      if (view.status === 'SUCCESS') {
        const current = jobs.value[normalizedJobId]
        if (current && !current.ready && !current.terminal) {
          await finalizeSuccess(view)
        }
        stopTimerIfIdle()
      } else if (view.status === 'FAILED') {
        const current = jobs.value[normalizedJobId]
        if (current) {
          jobs.value = {
            ...jobs.value,
            [normalizedJobId]: {
              ...current,
              terminal: true,
              errorMessage: isCancelledJob ? '' : String(payload?.error_message || payload?.message || current.errorMessage || 'failed_fallback'),
            },
          }
        }
        clearPendingUploads(normalizedJobId)
        taskListRefreshToken.value += 1
        stopTimerIfIdle()
      }
    } catch (err: unknown) {
      const notFound = (err as { response?: { status?: number } })?.response?.status === 404
      const errors = (fetchErrors.get(normalizedJobId) || 0) + 1
      fetchErrors.set(normalizedJobId, errors)
      if (notFound || errors >= MAX_CONSECUTIVE_FETCH_ERRORS) {
        const current = jobs.value[normalizedJobId]
        if (current) {
          jobs.value = {
            ...jobs.value,
            [normalizedJobId]: {
              ...current,
              terminal: true,
              errorMessage: current.errorMessage || (notFound ? 'job_not_found' : 'load_failed'),
            },
          }
        }
        clearPendingUploads(normalizedJobId)
        taskListRefreshToken.value += 1
        stopTimerIfIdle()
      }
    } finally {
      inFlight.delete(normalizedJobId)
    }
  }

  /** 任务创建成功后接入浮窗跟踪（展开面板） */
  const startWatching = (payload: { jobId: string; taskId: string; workspaceId: string; taskName?: string }) => {
    const jobId = asJobId(payload?.jobId)
    if (!jobId) return
    jobs.value = {
      ...jobs.value,
      [jobId]: {
        jobId,
        taskId: asJobId(payload?.taskId),
        workspaceId: asJobId(payload?.workspaceId),
        taskName: String(payload?.taskName || jobs.value[jobId]?.taskName || ''),
        status: 'PENDING',
        stage: 'QUEUED',
        progress: 0,
        message: '',
        errorMessage: '',
        cancelRequested: false,
        ready: false,
        terminal: false,
      },
    }
    expanded.value = true
    ensureTimer()
    void fetchJob(jobId)
  }

  /** 应用启动时恢复：拉取当前用户（创建人）名下未终态的任务创建 job */
  const restoreFromServer = async () => {
    if (restored.value) return
    restored.value = true
    try {
      const res = await api.get('/provision-jobs/active')
      const items = Array.isArray(res.data) ? res.data : []
      for (const payload of items as ProvisionJobApiPayload[]) {
        const view = upsertJobFromPayload(payload)
        if (view && !view.terminal) {
          void fetchJob(view.jobId)
        }
      }
      if (Object.keys(jobs.value).length > 0) {
        ensureTimer()
      }
    } catch (err) {
      restored.value = false
      console.warn('Failed to restore provisioning jobs', err)
    }
  }

  const minimize = () => {
    expanded.value = false
  }

  const expand = () => {
    expanded.value = true
  }

  /** 取消任务创建：后台工作流在下一个检查点终止并回滚（清理目录 + 删除任务记录） */
  const cancel = async (jobId: string) => {
    const normalizedJobId = asJobId(jobId)
    const current = jobs.value[normalizedJobId]
    if (current) {
      jobs.value = {
        ...jobs.value,
        [normalizedJobId]: { ...current, cancelRequested: true },
      }
    }
    await api.post(`/provision-jobs/${normalizedJobId}/cancel`)
    void fetchJob(normalizedJobId)
  }

  /** 关闭浮窗中的终态任务卡片（取消/失败后任务已被服务端删除） */
  const dismiss = (jobId: string) => {
    const normalizedJobId = asJobId(jobId)
    if (!normalizedJobId) return
    const next = { ...jobs.value }
    delete next[normalizedJobId]
    jobs.value = next
    fetchErrors.delete(normalizedJobId)
    clearPendingUploads(normalizedJobId)
    taskListRefreshToken.value += 1
    stopTimerIfIdle()
  }

  return {
    jobs,
    jobList,
    expanded,
    hasActiveJobs,
    taskListRefreshToken,
    restored,
    setPendingTaskSpec,
    consumePendingTaskSpec,
    clearPendingTaskSpec,
    setPendingTaskDocs,
    consumePendingTaskDocs,
    clearPendingTaskDocs,
    startWatching,
    restoreFromServer,
    minimize,
    expand,
    cancel,
    dismiss,
  }
})
