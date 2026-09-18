import { computed, ref, watch } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { Router } from 'vue-router'
import { formatElapsedDuration } from '@/utils/chatFormatters'
import {
  isChatActiveForTask,
  isDiagnosisSummaryActiveForTask,
  isDiagnosisSummaryJob,
  resolveDiagnosisSummaryStartedMs,
} from '@/utils/diagnosisSummary'
import { normalizeDiagnosisPayload, type DiagnosisResultPayload } from '@/types/diagnosis'
import { useMarkdownExport } from '@/composables/useMarkdownExport'
import { formatApiError } from '@/utils/error'
import type { ChatAiJob } from '../types'
import type { Ref } from 'vue'

/**
 * 问题定位（DIAGNOSIS）领域：定位结果加载/编辑、案例创建与跳转、
 * 一键总结 job（以活跃 job 表为唯一事实源，长耗时以 job 发起时刻计时）、结果导出。
 */
export function useDiagnosis(options: {
  getWorkspaceId: () => string
  currentTask: Ref<any>
  currentWorkspace: Ref<any>
  activeChatJobs: Ref<Record<string, ChatAiJob>>
  ingestJob: (job: ChatAiJob) => void
  findMessage: (messageId: string) => any
  router: Router
}) {
  const { t } = useI18n()
  const { exportDiagnosisMarkdown, exportCaseMarkdown } = useMarkdownExport()

  const taskId = () => String(options.currentTask.value?.id || '')
  const isDiagnosisTask = () => String(options.currentTask.value?.task_type || '') === 'DIAGNOSIS'

  const diagnosisResult = ref<any>(null)
  const diagnosisResultLoading = ref(false)
  const diagnosisResultSaving = ref(false)
  const diagnosisCaseCreating = ref(false)
  const diagnosisCaseLink = ref('')
  const diagnosisSummaryJobId = ref('')

  // 「一键总结/重新生成」的 loading 状态以后端真实 job 状态为唯一事实源：
  // 识别 TASK_CHAT 中 job_kind=DIAGNOSIS_SUMMARY 且仍在 PENDING/RUNNING 的任务，
  // 与停止按钮一样跟随 activeChatJobs（由 WebSocket chat_job_update/done/failed 与快照实时驱动）。
  const diagnosisSummarizing = computed<boolean>(() =>
    isDiagnosisSummaryActiveForTask(options.activeChatJobs.value, options.currentTask.value?.id),
  )
  // 会话/总结互斥：会话 job（含排队与 HITL 挂起）进行中时禁止发起一键总结
  const diagnosisChatBusy = computed<boolean>(() =>
    isChatActiveForTask(options.activeChatJobs.value, options.currentTask.value?.id),
  )

  // 长耗时提示：计时基准 = 后端 job 的 created_at（started_at 兜底）——发起时刻，
  // 跨 session 不变；每秒 tick 只刷新「当前时刻」。
  const diagnosisSummaryNowTick = ref(0)
  let diagnosisSummaryElapsedTimer: number | null = null
  const diagnosisSummaryJobStartedMs = computed(() =>
    resolveDiagnosisSummaryStartedMs(options.activeChatJobs.value, options.currentTask.value?.id),
  )
  watch(diagnosisSummarizing, (active) => {
    if (active) {
      diagnosisSummaryNowTick.value = Date.now()
      if (diagnosisSummaryElapsedTimer === null) {
        diagnosisSummaryElapsedTimer = window.setInterval(() => {
          diagnosisSummaryNowTick.value = Date.now()
        }, 1000)
      }
    } else if (diagnosisSummaryElapsedTimer !== null) {
      window.clearInterval(diagnosisSummaryElapsedTimer)
      diagnosisSummaryElapsedTimer = null
    }
  })
  const diagnosisSummarizingElapsed = computed(() => {
    const startedMs = diagnosisSummaryJobStartedMs.value
    if (!startedMs || !diagnosisSummarizing.value) return 0
    return Math.max(0, Math.floor((diagnosisSummaryNowTick.value - startedMs) / 1000))
  })
  const diagnosisSummarizingLabel = computed(() => {
    if (!diagnosisSummarizing.value) return t('diagnosis.summarize_case_button')
    const total = diagnosisSummarizingElapsed.value
    if (total < 5) return t('diagnosis.summarizing')
    return t('diagnosis.summarizing_elapsed', { elapsed: formatElapsedDuration(total) })
  })
  const isDiagnosisAdopted = computed(() => Boolean(
    diagnosisResult.value?.status === 'CONFIRMED' || diagnosisCaseLink.value,
  ))

  const clearTimer = () => {
    if (diagnosisSummaryElapsedTimer !== null) {
      window.clearInterval(diagnosisSummaryElapsedTimer)
      diagnosisSummaryElapsedTimer = null
    }
  }

  const resetForTask = () => {
    diagnosisResult.value = null
    diagnosisCaseLink.value = ''
    diagnosisSummaryJobId.value = ''
    clearTimer()
  }

  const loadDiagnosisResult = async () => {
    const id = taskId()
    if (!id || !isDiagnosisTask()) {
      diagnosisResult.value = null
      diagnosisCaseLink.value = ''
      return
    }
    diagnosisResultLoading.value = true
    try {
      const res = await api.get(`/workspaces/${options.getWorkspaceId()}/tasks/${id}/diagnosis-result`)
      // 尚无结果时后端返回 200 + null（AI 会话收敛后自动反填，卡片由会话消息驱动）
      diagnosisResult.value = res.data || null
    } catch (e: any) {
      if (e?.response?.status === 404) {
        // 兼容旧后端：尚无结果
        diagnosisResult.value = null
        return
      }
      console.warn('Failed to load diagnosis result', e)
    } finally {
      diagnosisResultLoading.value = false
    }
    try {
      const casesRes = await api.get(`/workspaces/${options.getWorkspaceId()}/cases`, {
        params: { source_task_id: id, page: 1, page_size: 1 },
      })
      const linked = (casesRes.data?.items || [])[0]
      diagnosisCaseLink.value = linked?.id || ''
    } catch (e) {
      diagnosisCaseLink.value = ''
    }
  }

  /** 诊断总结 job 到达终态时，立即刷新定位结果卡片与案例链接（WebSocket 即时收敛路径）。 */
  const onJobUpdate = (job: ChatAiJob) => {
    if (!isDiagnosisSummaryJob(job)) return
    const jobTaskId = String(job.task_id || '')
    if (!jobTaskId || jobTaskId !== taskId()) return
    if (job.status === 'SUCCESS' || job.status === 'FAILED' || job.status === 'CANCELLED') {
      void loadDiagnosisResult()
    }
  }

  /** 以后端返回的规范化结果回填气泡，确保编辑后的值真正反映到卡片上 */
  const patchMessageMetadata = (messageId: string, payload: DiagnosisResultPayload) => {
    const message = options.findMessage(messageId)
    if (!message) return
    const normalized = normalizeDiagnosisPayload(payload)
    message.metadata = normalized
    message.content = String(normalized.summary || normalized.root_cause || '')
  }

  const saveDiagnosisResult = async (payload: DiagnosisResultPayload, messageId?: string) => {
    const id = taskId()
    if (!id) return
    diagnosisResultSaving.value = true
    try {
      const res = await api.put(`/workspaces/${options.getWorkspaceId()}/tasks/${id}/diagnosis-result`, payload)
      diagnosisResult.value = res.data
      if (messageId) {
        patchMessageMetadata(messageId, res.data as DiagnosisResultPayload)
      }
      ElMessage.success(t('diagnosis.result_saved'))
    } catch (e) {
      ElMessage.error(formatApiError(e, t('diagnosis.result_save_failed'), t))
      console.error('Failed to save diagnosis result', e)
    } finally {
      diagnosisResultSaving.value = false
    }
  }

  const createDiagnosisCase = async (submitForReview: boolean): Promise<string> => {
    const id = taskId()
    if (!id) return ''
    diagnosisCaseCreating.value = true
    try {
      const res = await api.post(`/workspaces/${options.getWorkspaceId()}/tasks/${id}/case-draft`, {
        submit_for_review: Boolean(submitForReview),
      })
      const caseId = String(res.data?.id || '')
      diagnosisCaseLink.value = caseId
      ElMessage.success(t(submitForReview ? 'diagnosis.case_created_and_submitted' : 'diagnosis.case_created'))
      options.router.push(`/workspaces/${options.getWorkspaceId()}/cases?case=${caseId}`)
      return caseId
    } catch (e: any) {
      if (e?.response?.status === 409) {
        const detail = String(e?.response?.data?.detail || '')
        const match = detail.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i)
        const existingId = match ? match[0] : ''
        if (existingId) {
          diagnosisCaseLink.value = existingId
          ElMessage.info(t('diagnosis.case_already_exists'))
          options.router.push(`/workspaces/${options.getWorkspaceId()}/cases?case=${existingId}`)
          return existingId
        }
      }
      ElMessage.error(formatApiError(e, t('diagnosis.case_create_failed'), t))
      console.error('Failed to create diagnosis case', e)
      return ''
    } finally {
      diagnosisCaseCreating.value = false
    }
  }

  const waitForDiagnosisSummary = async (jobId: string, id: string): Promise<string> => {
    // 轮询后端任务状态直至收敛（SUCCESS / FAILED / CANCELLED）。
    // 不再设 3 分钟硬上限：模型生成多久，加载动效就保持多久。
    // WebSocket chat_job_done/failed 会先行收敛（终态被 ingest 移出 activeChatJobs），
    // 这里作为无 WebSocket / 断线场景的兜底，负责把终态同步回本地状态。
    const terminal = new Set(['SUCCESS', 'FAILED', 'CANCELLED'])
    let terminalStatus = ''
    let missingCount = 0
    while (!terminalStatus) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000))
      try {
        const res = await api.get(
          `/workspaces/${options.getWorkspaceId()}/tasks/${id}/diagnosis-summary/${jobId}`,
        )
        missingCount = 0
        const status = String(res.data?.status || '')
        if (terminal.has(status)) {
          terminalStatus = status
          break
        }
      } catch (e: any) {
        if (e?.response?.status === 404) {
          // job 记录已不存在（如任务被清理）：给几次重试后按失败收敛，避免无限轮询
          missingCount += 1
          if (missingCount >= 3) {
            console.warn('Diagnosis summary job disappeared', { jobId, taskId: id })
            break
          }
        } else {
          console.warn('Failed to poll diagnosis summary status', e)
          // 短时抖动不终止轮询，继续等待终态
        }
      }
    }
    // 无论经哪条路径收敛，都把当前总结 job 同步进 activeChatJobs：
    // 终态会被 ingest 移出列表 → diagnosisSummarizing 自动关闭。
    // 若该 job 已被 WebSocket 终态消息移出，说明已收敛过，跳过重复提示。
    const alreadySynced = !options.activeChatJobs.value[jobId]
    options.ingestJob({
      id: jobId,
      task_id: id,
      status: (terminalStatus || 'FAILED') as ChatAiJob['status'],
      progress: terminalStatus ? 100 : 0,
      message: terminalStatus ? null : t('diagnosis.summary_failed'),
      context_json: { job_kind: 'DIAGNOSIS_SUMMARY' },
      created_at: new Date().toISOString(),
    })
    if (!terminalStatus && !alreadySynced) {
      ElMessage.error(t('diagnosis.summary_failed'))
    }
    // 延迟一拍再拉取，确保定位结果卡片已由后端写入并广播
    await new Promise((resolve) => window.setTimeout(resolve, 1500))
    if (taskId() === id) {
      await loadDiagnosisResult()
    }
    return terminalStatus
  }

  const generateDiagnosisSummary = async (): Promise<boolean> => {
    const id = taskId()
    if (!id || !isDiagnosisTask() || diagnosisSummarizing.value) return false
    if (diagnosisChatBusy.value) {
      ElMessage.warning(t('diagnosis.summary_blocked_by_chat'))
      return false
    }
    if (isDiagnosisAdopted.value) {
      ElMessage.warning(t('diagnosis.case_already_adopted_no_summary'))
      return false
    }
    diagnosisSummaryJobId.value = ''
    try {
      const res = await api.post(`/workspaces/${options.getWorkspaceId()}/tasks/${id}/diagnosis-summary`)
      const jobId = String(res.data?.job_id || '')
      if (!jobId) {
        throw new Error(t('diagnosis.summary_job_missing'))
      }
      diagnosisSummaryJobId.value = jobId
      // 立即播种 PENDING 状态，避免 WebSocket 事件未到达前出现动效空窗；
      // 后续由 chat_job_update / 轮询驱动真实状态。
      options.ingestJob({
        id: jobId,
        task_id: id,
        status: 'PENDING',
        progress: 0,
        message: t('diagnosis.summary_started'),
        context_json: { job_kind: 'DIAGNOSIS_SUMMARY' },
        created_at: new Date().toISOString(),
      } as ChatAiJob)
      ElMessage.success(t('diagnosis.summary_started'))
      await waitForDiagnosisSummary(jobId, id)
      return true
    } catch (e) {
      ElMessage.error(formatApiError(e, t('diagnosis.summary_failed'), t))
      console.error('Failed to generate diagnosis summary', e)
      return false
    }
  }

  const exportDiagnosisResult = async (payload: DiagnosisResultPayload) => {
    if (!payload) return
    const id = taskId()
    const task = options.currentTask.value

    // 若该任务已生成案例，则与会话/案例详情导出一致：优先导出案例内容。
    if (diagnosisCaseLink.value) {
      try {
        const res = await api.get(`/workspaces/${options.getWorkspaceId()}/cases/${diagnosisCaseLink.value}`)
        if (res.data) {
          exportCaseMarkdown(res.data)
          return
        }
      } catch (e) {
        console.warn('Failed to load linked case for export', e)
      }
    }

    const norm = normalizeDiagnosisPayload(payload)
    const taskName = task?.name || ''
    const diagnosisMeta = task?.task_meta_json || {}
    exportDiagnosisMarkdown(norm, taskName, {
      taskId: id,
      problemDescription: String(diagnosisMeta.phenomenon || task?.description || ''),
      productName: String(options.currentWorkspace.value?.products?.[0]?.name || ''),
      productVersion: String(options.currentWorkspace.value?.products?.[0]?.version_no || ''),
      projectName: String(options.currentWorkspace.value?.project?.name || ''),
      repositories: Array.isArray(options.currentWorkspace.value?.repositories) ? options.currentWorkspace.value.repositories : undefined,
    })
  }

  return {
    diagnosisResult,
    diagnosisResultLoading,
    diagnosisResultSaving,
    diagnosisCaseCreating,
    diagnosisCaseLink,
    diagnosisSummaryJobId,
    diagnosisSummarizing,
    diagnosisChatBusy,
    diagnosisSummarizingElapsed,
    diagnosisSummarizingLabel,
    isDiagnosisAdopted,
    loadDiagnosisResult,
    onJobUpdate,
    patchMessageMetadata,
    saveDiagnosisResult,
    createDiagnosisCase,
    generateDiagnosisSummary,
    exportDiagnosisResult,
    resetForTask,
    clearTimer,
  }
}
