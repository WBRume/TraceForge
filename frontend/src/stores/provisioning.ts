import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import api from '@/utils/api'
import type { RequirementImportBatch } from '@/types/workspaceAssets'

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

/** 预览作业状态含后端收敛态（CANCELLED/TERMINATING/ORPHANED/REVERTED） */
export type ProvisionJobStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED' | 'TERMINATING' | 'ORPHANED' | 'REVERTED'

/** 浮窗跟踪的作业种类：任务创建 / Requirement AI 拆分预览 / AI 导入预览 */
export type ProvisionJobKind = 'provision' | 'requirement_split_preview' | 'requirement_import_preview' | 'playbook_promotion'

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
  /** 作业种类（provision 缺省，兼容既有调用方） */
  kind: ProvisionJobKind
  /** requirement preview 专用：关联需求与结果批次 */
  requirementId: string
  requirementTitle: string
  batch: RequirementImportBatch | null
  /** 预览结果已被「查看预览」消费：浮窗隐藏卡片，store 保留供弹窗绑定 */
  viewed: boolean
  /**
   * 预览作业是否已从弹窗「缩小」到右下角：false 时弹窗自身展示进度，
   * 浮窗不出卡片（provision 作业没有弹窗阶段，恒为 true）
   */
  handedOver: boolean
  promotionPayload?: RequirementPreviewJobApiPayload
  reviewRequired?: boolean
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

type RequirementPreviewJobApiPayload = {
  result?: { review_state?: string }
  job_id?: string | null
  workspace_id?: string | null
  status?: string | null
  progress?: number | null
  message?: string | null
  error?: string | null
  batch?: RequirementImportBatch | null
  job_kind?: string | null
  requirement_id?: string | null
  requirement_title?: string | null
  /** 后端轮询响应目前不携带该字段；保留以兼容未来扩展（本地标记不受影响） */
  cancel_requested?: boolean | null
}

const pendingSpecByJob = new Map<string, PendingTaskSpecUpload>()
const pendingDocsByJob = new Map<string, PendingTaskDocsUpload>()

const POLL_INTERVAL_MS = 1200
const MAX_CONSECUTIVE_FETCH_ERRORS = 10
const TASK_PENDING_POLL_ATTEMPTS = 20
const TASK_PENDING_POLL_INTERVAL_MS = 500
const EXPAND_PREF_KEY = 'provisionWidgetExpanded'

// Requirement preview 作业的前端终态集合：后端 converge 业务终态
// （SUCCESS/FAILED/CANCELLED/REVERTED）+ ORPHANED（死亡未证实等待 reaper 收敛，
// 前端视作不可复绑的死作业，停止轮询即可）。
const PREVIEW_FINAL_STATUSES = new Set(['SUCCESS', 'FAILED', 'CANCELLED', 'REVERTED', 'ORPHANED'])

const asJobId = (value: unknown): string => String(value || '').trim()

/** 后端 job_kind（REQUIREMENT_SPLIT_PREVIEW 等）→ 浮窗 kind；未知返回空串 */
const normalizePreviewKind = (value: unknown): ProvisionJobKind | '' => {
  const kind = String(value || '').trim().toLowerCase()
  if (kind === 'requirement_split_preview' || kind === 'requirement_import_preview' || kind === 'playbook_promotion') {
    return kind
  }
  return ''
}

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
      kind: existing?.kind || 'provision',
      requirementId: existing?.requirementId || '',
      requirementTitle: existing?.requirementTitle || '',
      batch: existing?.batch || null,
      viewed: existing?.viewed || false,
      handedOver: existing?.handedOver ?? true,
    }
    jobs.value = { ...jobs.value, [jobId]: view }
    return view
  }

  const upsertPreviewJobFromPayload = (payload: RequirementPreviewJobApiPayload): ProvisionJobView | null => {
    const jobId = asJobId(payload?.job_id)
    if (!jobId) return null
    const existing = jobs.value[jobId]
    const status = String(payload?.status || existing?.status || 'PENDING').toUpperCase() as ProvisionJobStatus
    const view: ProvisionJobView = {
      jobId,
      taskId: '',
      workspaceId: asJobId(payload?.workspace_id) || existing?.workspaceId || '',
      taskName: '',
      status,
      stage: '',
      progress: Math.max(0, Math.min(Number(payload?.progress ?? existing?.progress ?? 0), 100)),
      message: String(payload?.message || existing?.message || ''),
      errorMessage: String(payload?.error || existing?.errorMessage || ''),
      // preview 轮询响应不携带 cancel_requested；保留本地取消标记，
      // 让「取消中」状态在收敛到 CANCELLED 之前不被轮询覆盖
      cancelRequested: Boolean(payload?.cancel_requested) || Boolean(existing?.cancelRequested),
      ready: false,
      terminal: existing?.terminal || PREVIEW_FINAL_STATUSES.has(status),
      kind: existing?.kind || normalizePreviewKind(payload?.job_kind) || 'requirement_import_preview',
      requirementId: asJobId(payload?.requirement_id) || existing?.requirementId || '',
      requirementTitle: String(payload?.requirement_title || existing?.requirementTitle || ''),
      batch: payload?.batch || existing?.batch || null,
      viewed: existing?.viewed || false,
      // 新建条目默认 true（restore/深链兜底场景没有弹窗在展示）；弹窗内
      // 发起的作业由 trackRequirementPreviewJob 显式置 false，轮询更新保留原值
      handedOver: existing?.handedOver ?? true,
    }
    jobs.value = { ...jobs.value, [jobId]: view }
    return view
  }

  const ensureTimer = () => {
    if (timer !== null) return
    timer = window.setInterval(() => {
      for (const job of Object.values(jobs.value)) {
        if (!job.terminal && job.kind !== 'playbook_promotion') {
          if (job.kind === 'provision') {
            void fetchJob(job.jobId)
          } else {
            void fetchPreviewJob(job.jobId)
          }
        }
      }
    }, POLL_INTERVAL_MS)
  }

  const stopTimerIfIdle = () => {
    if (timer === null) return
    if (Object.values(jobs.value).some((job) => !job.terminal && job.kind !== 'playbook_promotion')) return
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
        kind: 'provision',
        requirementId: '',
        requirementTitle: '',
        batch: null,
        viewed: false,
        handedOver: true,
      },
    }
    expanded.value = true
    ensureTimer()
    void fetchJob(jobId)
  }

  /**
   * Requirement AI 预览作业（拆分/导入）接入浮窗跟踪。
   * 弹窗关闭后作业继续在后台轮询；不展开面板（发起时弹窗自身已有进度 UI）。
   */
  const trackRequirementPreviewJob = (payload: {
    jobId: string
    workspaceId: string
    kind: ProvisionJobKind
    requirementId?: string
    requirementTitle?: string
  }) => {
    const jobId = asJobId(payload?.jobId)
    if (!jobId) return null
    const existing = jobs.value[jobId]
    const view: ProvisionJobView = existing && !existing.terminal ? existing : {
      jobId,
      taskId: '',
      workspaceId: asJobId(payload?.workspaceId),
      taskName: '',
      status: 'PENDING',
      stage: '',
      progress: 0,
      message: '',
      errorMessage: '',
      cancelRequested: false,
      ready: false,
      terminal: false,
      kind: normalizePreviewKind(payload?.kind) || 'requirement_import_preview',
      requirementId: asJobId(payload?.requirementId),
      requirementTitle: String(payload?.requirementTitle || ''),
      batch: null,
      viewed: false,
      // 弹窗内发起：进度先由弹窗展示，点「缩小」后才交到右下角浮窗
      handedOver: false,
    }
    jobs.value = { ...jobs.value, [jobId]: view }
    ensureTimer()
    void fetchPreviewJob(jobId)
    return view
  }

  /** 弹窗点「缩小」：预览作业收起到右下角浮窗（展开面板承接弹窗上下文） */
  const minimizePreviewJob = (jobId: string) => {
    const normalizedJobId = asJobId(jobId)
    const current = jobs.value[normalizedJobId]
    if (!current || current.kind === 'provision') return
    jobs.value = {
      ...jobs.value,
      [normalizedJobId]: { ...current, handedOver: true, viewed: false },
    }
    expanded.value = true
  }

  /** 已完成但尚未查看的预览结果（同需求重复发起「拆分」时直接回绑，免重跑 CLI） */
  const findLatestPreviewResult = (
    requirementId: string,
    kind: ProvisionJobKind,
  ): ProvisionJobView | null => {
    const normalized = asJobId(requirementId)
    if (!normalized) return null
    return (
      Object.values(jobs.value).find(
        (job) =>
          job.kind === kind
          && job.requirementId === normalized
          && job.terminal
          && job.status === 'SUCCESS',
      ) || null
    )
  }

  /**
   * 浮窗/弹窗关闭进行中的预览作业：走任务会话同款 ai-jobs cancel 通道，
   * 后端经统一取消信号终止 CLI（各 backend 由 bridge.cancel 收敛）。
   *
   * 语义：
   * - 请求受理 → 标记 cancelRequested 并保留作业，轮询直到后端收敛
   *   CANCELLED 后自动清理。绝不立即移除：否则「关闭→立刻重开」会误判
   *   为无作业而重复发起新 CLI（旧作业仍在终态收敛/排队，新作业卡 PENDING）。
   * - 404 → 作业不存在，直接移除；其余失败 → 保留作业并交由调用方提示重试。
   */
  const cancelPreviewJob = async (jobId: string): Promise<boolean> => {
    const normalizedJobId = asJobId(jobId)
    const job = jobs.value[normalizedJobId]
    if (!job || job.kind === 'provision') return true
    const markCancelling = () => {
      const current = jobs.value[normalizedJobId]
      if (current) {
        jobs.value = {
          ...jobs.value,
          [normalizedJobId]: { ...current, cancelRequested: true },
        }
      }
    }
    try {
      if (job.kind === 'playbook_promotion') {
        const { data } = await api.post(`/workspaces/${job.workspaceId}/cases/playbook-promotions/${normalizedJobId}/cancel`)
        ingestPromotionJob(data)
        return true
      }
      await api.post(`/workspaces/${job.workspaceId}/ai-jobs/${normalizedJobId}/cancel`)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        dismiss(normalizedJobId)
        return true
      }
      markCancelling()
      return false
    }
    markCancelling()
    return true
  }

  /** 深链恢复：把一次作业查询结果直接并入浮窗（刷新后 store 无记录时用） */
  const ingestPreviewJobPayload = (payload: RequirementPreviewJobApiPayload): ProvisionJobView | null => {
    const view = upsertPreviewJobFromPayload(payload)
    if (view && !view.terminal && view.kind !== 'playbook_promotion') {
      ensureTimer()
    }
    return view
  }

  // Promotion jobs share the floating presentation, but use notification WS invalidations.
  const ingestPromotionJob = (payload: RequirementPreviewJobApiPayload, inDialog = false) => {
    const normalizedJobId = asJobId(payload?.job_id)
    if (!normalizedJobId) return null
    const reviewState = payload.result?.review_state
    if (reviewState === 'CONFIRMED' || reviewState === 'DISCARDED') {
      dismiss(normalizedJobId)
      return null
    }
    const existing = jobs.value[normalizedJobId]
    if (existing?.terminal && !PREVIEW_FINAL_STATUSES.has(String(payload.status))) return existing
    const view = upsertPreviewJobFromPayload({ ...payload, job_kind: 'playbook_promotion', requirement_title: '案例晋升诊断规程' })
    if (view) {
      const next = { ...view, promotionPayload: payload, reviewRequired: reviewState === 'PENDING', ...(inDialog ? { handedOver: false, viewed: false } : {}) }
      jobs.value = { ...jobs.value, [view.jobId]: next }
      return next
    }
    return null
  }
  const promotionReads = new Map<string, number>()
  const refreshPromotionJobs = async (workspaceId?: string) => {
    const workspaces = workspaceId ? [workspaceId] : [...new Set(jobList.value.filter(j => j.kind === 'playbook_promotion').map(j => j.workspaceId))]
    await Promise.all(workspaces.map(async (wsId) => {
      const version = (promotionReads.get(wsId) || 0) + 1
      promotionReads.set(wsId, version)
      try {
        const { data } = await api.get(`/workspaces/${wsId}/cases/playbook-promotions`)
        if (promotionReads.get(wsId) !== version) return
        for (const payload of data.items || []) {
          if (jobs.value[payload.job_id]) ingestPromotionJob(payload)
        }
      } catch { /* Reconnect or opening the dialog retries the snapshot. */ }
    }))
  }

  /** 预览结果已被「查看预览」消费：浮窗隐藏卡片（store 保留供弹窗绑定） */
  const markPreviewJobViewed = (jobId: string) => {
    const normalizedJobId = asJobId(jobId)
    const current = jobs.value[normalizedJobId]
    if (!current || current.kind === 'provision') return
    jobs.value = {
      ...jobs.value,
      [normalizedJobId]: { ...current, viewed: true },
    }
  }

  /** 按 jobId 查浮窗中跟踪的作业（视图绑定预览弹窗用） */
  const getTrackedJob = (jobId: string): ProvisionJobView | null => {
    const normalizedJobId = asJobId(jobId)
    return jobs.value[normalizedJobId] || null
  }

  /** 浮窗中某需求当前非终态的预览作业（去重：同一需求不重复发起） */
  const findActivePreviewJob = (
    requirementId: string,
    kind: ProvisionJobKind,
  ): ProvisionJobView | null => {
    const normalized = asJobId(requirementId)
    if (!normalized) return null
    return (
      Object.values(jobs.value).find(
        (job) => job.kind === kind && job.requirementId === normalized && !job.terminal,
      ) || null
    )
  }

  /** 预览作业轮询：进度更新 + 终态收敛（SUCCESS 存 batch 供弹窗直接展示） */
  const fetchPreviewJob = async (jobId: string) => {
    const normalizedJobId = asJobId(jobId)
    if (!normalizedJobId || inFlight.has(normalizedJobId)) return
    const current = jobs.value[normalizedJobId]
    if (!current || current.kind === 'provision' || current.kind === 'playbook_promotion') return
    inFlight.add(normalizedJobId)
    try {
      const res = await api.get(
        `/workspaces/${current.workspaceId}/workspace-assets/requirements/preview-jobs/${normalizedJobId}`,
      )
      const view = upsertPreviewJobFromPayload(res.data as RequirementPreviewJobApiPayload)
      fetchErrors.delete(normalizedJobId)
      if (!view) return
      if (
        view.terminal
        && (view.status === 'CANCELLED' || view.status === 'ORPHANED' || view.status === 'REVERTED')
      ) {
        // 取消已收敛 / reaper 回收敛死：预览作业没有可查看的结果，自动移除
        // 卡片（SUCCESS/FAILED 保留供弹窗/浮窗查看结果与错误）。终态后轮询
        // 停止，必须在这里清理，否则卡片会永远停留。
        dismiss(normalizedJobId)
        return
      }
      if (view.terminal && view.status === 'FAILED' && !view.errorMessage) {
        jobs.value = {
          ...jobs.value,
          [normalizedJobId]: { ...view, errorMessage: 'failed_fallback' },
        }
      }
      stopTimerIfIdle()
    } catch (err: unknown) {
      const notFound = (err as { response?: { status?: number } })?.response?.status === 404
      const errors = (fetchErrors.get(normalizedJobId) || 0) + 1
      fetchErrors.set(normalizedJobId, errors)
      if (notFound || errors >= MAX_CONSECUTIVE_FETCH_ERRORS) {
        const failed = jobs.value[normalizedJobId]
        if (failed) {
          jobs.value = {
            ...jobs.value,
            [normalizedJobId]: {
              ...failed,
              status: 'FAILED',
              terminal: true,
              errorMessage: failed.errorMessage || (notFound ? 'job_not_found' : 'load_failed'),
            },
          }
        }
        fetchErrors.delete(normalizedJobId)
        stopTimerIfIdle()
      }
    } finally {
      inFlight.delete(normalizedJobId)
    }
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
      if (Object.values(jobs.value).some((job) => job.kind === 'provision' && !job.terminal)) {
        ensureTimer()
      }
    } catch (err) {
      restored.value = false
      console.warn('Failed to restore provisioning jobs', err)
    }
    // Requirement preview 作业独立恢复：端点不可用不影响任务创建浮窗
    try {
      const res = await api.get('/requirement-preview-jobs/active')
      const items = Array.isArray(res.data) ? res.data : []
      for (const payload of items as RequirementPreviewJobApiPayload[]) {
        // 缺少可识别 job_kind 的记录直接跳过，避免误覆盖其他种类的作业视图
        if (!normalizePreviewKind(payload?.job_kind)) continue
        const view = upsertPreviewJobFromPayload(payload)
        if (view && !view.terminal) {
          void fetchPreviewJob(view.jobId)
        }
      }
      if (Object.values(jobs.value).some((job) => job.kind !== 'provision' && job.kind !== 'playbook_promotion' && !job.terminal)) {
        ensureTimer()
      }
    } catch (err) {
      console.warn('Failed to restore requirement preview jobs', err)
    }
    try {
      const { data } = await api.get('/cases/playbook-promotions/active')
      for (const payload of data.items || []) ingestPromotionJob(payload)
    } catch (err) {
      console.warn('Failed to restore playbook promotion jobs', err)
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
    const dismissed = jobs.value[normalizedJobId]
    const next = { ...jobs.value }
    delete next[normalizedJobId]
    jobs.value = next
    fetchErrors.delete(normalizedJobId)
    clearPendingUploads(normalizedJobId)
    // 仅任务创建作业影响任务列表；预览作业的 dismiss 不触发无关刷新
    if (dismissed?.kind === 'provision') {
      taskListRefreshToken.value += 1
    }
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
    trackRequirementPreviewJob,
    minimizePreviewJob,
    findLatestPreviewResult,
    cancelPreviewJob,
    ingestPreviewJobPayload,
    ingestPromotionJob,
    refreshPromotionJobs,
    markPreviewJobViewed,
    getTrackedJob,
    findActivePreviewJob,
    restoreFromServer,
    minimize,
    expand,
    cancel,
    dismiss,
  }
})
