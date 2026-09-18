import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTaskRuntimePanels } from '@/composables/useTaskRuntimePanels'
import { isJobExecuting } from '../jobs/useChatJobs'
import type { ChatAiJob, ChatStatusCard } from '../types'

/**
 * 引擎运行态：engineRunning 标志 + AI 思考面板 + 按任务隔离的运行面板快照
 * （切换会话时持久化/恢复，避免同视图内往返丢失运行状态）。
 * 「全部 job 结束后收敛运行面板」的策略也在这里（convergeFromJobs）。
 */
export function useEngineState(options: {
  getStatusCards: () => ChatStatusCard[]
  onStatusCardPush: (card: ChatStatusCard) => void
  onStatusCardsDrop: () => void
  hasExecutingJob: () => boolean
}) {
  const { t } = useI18n()
  const panels = useTaskRuntimePanels()

  const engineRunning = ref(false)

  // AI thinking panel: delta/snapshot frame protocol state
  const thinkingContent = ref('')
  const showThinking = ref(false)
  const thinkingExpanded = ref(false)
  const thinkingSequence = ref(0)

  const resetThinking = () => {
    thinkingContent.value = ''
    showThinking.value = false
    thinkingExpanded.value = false
    thinkingSequence.value = 0
  }

  /** thinking WS 帧：sequence 乱序丢弃；delta 追加，snapshot 整体替换。 */
  const applyThinkingFrame = (payload: any) => {
    const sequence = Number(payload?.sequence ?? 0)
    if (sequence > 0 && sequence <= thinkingSequence.value) {
      return
    }
    thinkingSequence.value = sequence
    const wasThinkingVisible = showThinking.value
    const delta = typeof payload?.delta === 'string' ? payload.delta : null
    if (delta !== null) {
      thinkingContent.value += delta
    } else {
      thinkingContent.value = String(payload?.content || '')
    }
    showThinking.value = true
    if (!wasThinkingVisible) {
      thinkingExpanded.value = false
    }
  }

  /** 引擎运行态跟随活跃 job 表：有执行中 job 即视为运行。 */
  const syncFromJobs = () => {
    engineRunning.value = options.hasExecutingJob()
  }

  /** 离开会话前保存运行面板（执行中才值得保存，否则清除残留快照）。 */
  const persistForTask = (taskId: string) => {
    if (!taskId) return
    if (!engineRunning.value && !options.hasExecutingJob()) {
      panels.clear(taskId)
      return
    }
    panels.save(taskId, {
      statusCards: options.getStatusCards(),
      thinkingContent: thinkingContent.value,
      showThinking: showThinking.value,
      thinkingExpanded: thinkingExpanded.value,
    })
  }

  /** 进入会话时恢复运行面板；返回其中的状态卡交给调用方写入卡片存储。 */
  const restoreForTask = (taskId: string): ChatStatusCard[] => {
    const snapshot = panels.restore(taskId)
    thinkingContent.value = snapshot?.thinkingContent || ''
    showThinking.value = Boolean(snapshot?.showThinking && snapshot.thinkingContent)
    thinkingExpanded.value = snapshot?.thinkingExpanded || false
    engineRunning.value = Boolean(snapshot)
    return snapshot?.statusCards || []
  }

  /**
   * 用活跃 job 列表种子运行态：执行中保持状态卡片与 engineRunning，
   * 全部结束则收敛（清状态卡、思考面板与快照）。
   */
  const convergeFromJobs = (taskId: string, items: ChatAiJob[]): boolean => {
    const executingJobs = items.filter(job => isJobExecuting(job.status))
    if (!executingJobs.length) {
      engineRunning.value = false
      options.onStatusCardsDrop()
      resetThinking()
      panels.clear(taskId)
      return true
    }
    if (!options.getStatusCards().length) {
      const job = executingJobs.find(item => Boolean(item.session_id)) || executingJobs[0]
      const isSessionStarted = Boolean(job.session_id) && !job.context_json?.job_kind
      options.onStatusCardPush({
        id: `job-status-${job.id}`,
        type: 'status',
        status: isSessionStarted ? 'INIT' : 'RUNNING',
        message: isSessionStarted ? t('chat.agent_session_started') : (job.message || t('chat.ai_job_running')),
        model: String(job.context_json?.model || '').trim() || null,
        created_at: job.started_at || job.created_at || new Date().toISOString(),
      })
    }
    return true
  }

  return {
    engineRunning,
    thinkingContent,
    showThinking,
    thinkingExpanded,
    applyThinkingFrame,
    resetThinking,
    syncFromJobs,
    persistForTask,
    restoreForTask,
    convergeFromJobs,
  }
}

export type EngineState = ReturnType<typeof useEngineState>
