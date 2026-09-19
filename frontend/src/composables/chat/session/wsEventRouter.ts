import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { ChatAiJob } from '../types'

/**
 * WS 事件路由：把任务频道的传输事件映射到各领域操作。
 * 这里是「传输 → 领域」的唯一汇聚点；case 保持薄，副作用（滚动、防抖刷新）
 * 通过注入的回调触发，路由本身不持有状态。
 */
export function createTaskWsEventRouter(deps: {
  task: {
    getTaskId: () => string
    patchSessionGeneration: (generation: number) => void
    syncTaskStatus: (status: string) => void
    getCurrentSessionGeneration: () => number
    getCurrentTaskStatus: () => string
  }
  messages: {
    upsert: (message: any) => void
    findByIdentity: (identity: string) => any
    removeByIds: (ids: Set<string>) => void
  }
  terminalLogs: {
    appendToolUse: (payload: any) => void
    appendToolResult: (payload: any) => void
    appendLog: (payload: any) => void
    clear: () => void
  }
  cards: {
    syncConfirmationCards: () => void
    dropStatusCards: () => void
    pushStatusCard: (card: any) => void
    clear: () => void
  }
  engine: {
    engineRunning: { value: boolean }
    syncFromJobs: () => void
    applyThinkingFrame: (payload: any) => void
    resetThinking: () => void
  }
  resultsSummary: {
    appendResult: (payload: any) => void
  }
  submissions: {
    busy: () => boolean
    put: (receipt: any) => void
    removeMessages: (taskId: string, messageIds: Set<string>) => void
  }
  ingestJob: (job: ChatAiJob) => void
  refreshActiveJobs: (taskId: string) => Promise<boolean>
  applyTaskSessionPayload: (payload: any) => void
  specBootstrapApplyUpdate: (payload: any) => void
  shareSuggestionNudge: (payload: any) => void
  preinputHandleEvent: (type: string, payload: any) => void
  skillsMergeTraceEvent: (event: any) => void
  skillsScheduleUsageRefresh: () => void
  onSessionGenerationBump: () => void
  contextWindowScheduleRefresh: () => void
  scrollTo: (target: 'chat' | 'terminal') => void
  isHistoryAnchored: () => boolean
  getRouteMessageId: () => string
}) {
  const { t } = useI18n()

  /** WS 消息载荷 → 气泡统一形状（与 REST 历史映射字段一致，message_type 直接读取）。 */
  const toChatMessage = (payload: any, deliveryStatus: string) => ({
    id: payload.id || Date.now().toString(),
    role: payload.role,
    content: payload.content,
    created_at: payload.created_at || new Date().toISOString(),
    message_type: payload.message_type || 'text',
    creator_id: payload.creator_id || null,
    creator_display_name: payload.creator_display_name || null,
    creator_is_workspace_expert: Boolean(payload.creator_is_workspace_expert),
    creator_avatar_url: payload.creator_avatar_url || null,
    creator_avatar_svg: payload.creator_avatar_svg || null,
    client_message_id: payload.client_message_id || null,
    decision_id: payload.decision_id || null,
    metadata: payload.metadata || null,
    session_turn_id: payload.session_turn_id || null,
    session_generation: payload.session_generation ?? null,
    can_undo: payload.can_undo,
    delivery_status: deliveryStatus,
  })

  const syncSessionGeneration = (payload: any) => {
    const taskId = deps.task.getTaskId()
    if (
      taskId
      && String(payload?.task_id || taskId) === taskId
      && payload?.session_generation !== undefined
    ) {
      deps.task.patchSessionGeneration(Number(payload.session_generation || 0))
    }
  }

  const handleWsMessage = (msg: any) => {
    const { type, payload } = msg

    switch (type) {
      case 'chat_message': {
        // 自然语言对话气泡 (user / assistant text) 与定位结果卡片
        syncSessionGeneration(payload)
        deps.messages.upsert(toChatMessage(payload, 'sent'))
        deps.cards.syncConfirmationCards()
        if (!deps.isHistoryAnchored()) deps.scrollTo('chat')
        deps.contextWindowScheduleRefresh()
        break
      }

      case 'chat_message_ack': {
        const status = String(payload.status || '').toLowerCase()
        const clientMessageId = String(payload.client_message_id || '').trim()
        syncSessionGeneration(payload)
        const messagePatch = {
          id: payload.id || payload.chat_message_id || (clientMessageId ? `local-${clientMessageId}` : Date.now().toString()),
          role: payload.role || 'user',
          content: payload.content || '',
          created_at: payload.created_at || new Date().toISOString(),
          message_type: payload.message_type || 'text',
          creator_id: payload.creator_id || null,
          creator_display_name: payload.creator_display_name || null,
          creator_is_workspace_expert: Boolean(payload.creator_is_workspace_expert),
          client_message_id: clientMessageId || null,
          decision_id: payload.decision_id || null,
          metadata: payload.metadata || null,
          session_turn_id: payload.session_turn_id || null,
          session_generation: payload.session_generation ?? null,
          can_undo: payload.can_undo,
          delivery_status: status === 'accepted' || status === 'duplicate' ? 'sent' : status,
        }
        if (clientMessageId) {
          const existing = deps.messages.findByIdentity(`client:${clientMessageId}`)
          if (existing) {
            deps.messages.upsert({
              ...messagePatch,
              content: messagePatch.content || existing.content,
              created_at: payload.created_at || existing.created_at,
            })
          } else if (messagePatch.content) {
            deps.messages.upsert(messagePatch)
          }
          deps.cards.syncConfirmationCards()
        }
        if (status === 'failed' || status === 'conflict') {
          ElMessage.error(payload.message || 'Message was not sent. Please retry.')
          if (status === 'failed') {
            deps.engine.syncFromJobs()
            const taskId = deps.task.getTaskId()
            if (taskId) void deps.refreshActiveJobs(taskId)
          }
        }
        break
      }

      case 'pre_input_update':
      case 'pre_input_submitted':
      case 'pre_input_error': {
        deps.preinputHandleEvent(type, payload)
        break
      }

      case 'hitl_rejected': {
        // HITL 回复被拒（如一键总结进行中互斥）：明确告知用户，不中断连接
        ElMessage.warning(payload?.message || 'HITL response rejected, please wait and retry')
        break
      }

      case 'thinking': {
        // AI 思考过程 → 思考面板 (不进入对话气泡)
        deps.engine.applyThinkingFrame(payload)
        deps.contextWindowScheduleRefresh()
        break
      }

      case 'tool_use': {
        // 工具调用 → 终端面板 (不进入对话气泡)
        deps.terminalLogs.appendToolUse(payload)
        deps.scrollTo('terminal')
        deps.skillsScheduleUsageRefresh()
        deps.contextWindowScheduleRefresh()
        break
      }

      case 'tool_result': {
        // 工具执行结果 → 终端面板
        deps.terminalLogs.appendToolResult(payload)
        deps.scrollTo('terminal')
        deps.contextWindowScheduleRefresh()
        break
      }

      case 'skill_runtime_event': {
        deps.skillsMergeTraceEvent(payload)
        deps.contextWindowScheduleRefresh()
        break
      }

      case 'log': {
        // 原始日志 → 终端面板
        deps.terminalLogs.appendLog(payload)
        deps.scrollTo('terminal')
        break
      }

      case 'chat_job_update': {
        const job = payload?.job as ChatAiJob | undefined
        if (job?.id) {
          deps.ingestJob(job)
        }
        break
      }

      case 'chat_submission_update': {
        // 事务 outbox 事件直接应用：回执按版本合并，EXECUTING 事件同时携带
        // 正式用户消息与 Job；不做 REST 反查，也不重刷 history / ai-jobs。
        if (String(payload?.task_id || '') !== deps.task.getTaskId()) break
        if (payload?.session_generation !== undefined
          && Number(payload.session_generation || 0) < deps.task.getCurrentSessionGeneration()) break
        const receipt = payload?.receipt
        if (!receipt?.client_message_id) break
        deps.submissions.put(receipt)
        if (payload.message) {
          deps.messages.upsert({
            ...toChatMessage(payload.message, 'sent'),
            id: payload.message.id || `local-${receipt.client_message_id}`,
            client_message_id: payload.message.client_message_id || receipt.client_message_id,
          })
          deps.cards.syncConfirmationCards()
          if (!deps.isHistoryAnchored()) deps.scrollTo('chat')
        }
        if (payload.job) {
          deps.ingestJob(payload.job)
        }
        break
      }

      case 'chat_job_done':
      case 'chat_job_failed': {
        const job = payload?.job as ChatAiJob | undefined
        if (job?.id) {
          deps.ingestJob(job)
          if (job.status === 'FAILED') {
            ElMessage.error(job.error_message || t('chat.ai_job_failed_default'))
          }
        }
        deps.contextWindowScheduleRefresh()
        break
      }

      case 'task_interrupted': {
        deps.applyTaskSessionPayload(payload)
        deps.engine.engineRunning.value = false
        deps.cards.dropStatusCards()
        deps.contextWindowScheduleRefresh()
        break
      }

      case 'task_resumed': {
        deps.applyTaskSessionPayload(payload)
        deps.engine.engineRunning.value = true
        deps.contextWindowScheduleRefresh()
        break
      }

      case 'task_session_reverted': {
        if (String(payload?.task_id || '') !== deps.task.getTaskId()) break
        deps.onSessionGenerationBump()
        const removedIds = new Set<string>(
          (Array.isArray(payload?.removed_message_ids) ? payload.removed_message_ids : []).map((id: any) => String(id)),
        )
        deps.submissions.removeMessages(deps.task.getTaskId(), removedIds)
        if (deps.isHistoryAnchored() && removedIds.has(deps.getRouteMessageId())) {
          ElMessage.warning('定位的消息已被撤销，请回到最新')
        }
        deps.messages.removeByIds(removedIds)
        deps.terminalLogs.clear()
        deps.cards.clear()
        deps.engine.resetThinking()
        deps.engine.engineRunning.value = false
        if (payload?.session_generation !== undefined) {
          deps.task.patchSessionGeneration(Number(payload.session_generation || 0))
        }
        if (payload?.task_status) {
          deps.task.syncTaskStatus(String(payload.task_status))
        }
        deps.contextWindowScheduleRefresh()
        break
      }

      case 'spec_bootstrap_update': {
        deps.specBootstrapApplyUpdate(payload)
        break
      }

      case 'share_suggestion_update': {
        deps.shareSuggestionNudge(payload)
        break
      }

      case 'status': {
        // 阶段状态 → 置顶卡片
        const nextTaskStatus = (payload.status === 'INIT' || payload.status === 'RUNNING')
          ? 'CODING'
          : payload.status
        deps.engine.engineRunning.value = payload.status === 'INIT' || payload.status === 'RUNNING'
        deps.cards.dropStatusCards()
        deps.cards.pushStatusCard({
          id: Date.now().toString(),
          type: 'status',
          status: payload.status,
          message: payload.message,
          model: payload.model,
          created_at: new Date().toISOString(),
        })
        if (deps.task.getTaskId()) {
          deps.task.syncTaskStatus(nextTaskStatus)
        }
        break
      }

      case 'result': {
        // 执行结果 → 汇总卡片 + 标记引擎停止
        deps.engine.syncFromJobs()
        deps.cards.dropStatusCards()
        deps.resultsSummary.appendResult(payload)

        // 更新任务状态（自动执行异常保留为 INTERRUPTED 以便继续会话；
        // FAILED 只能由用户通过失败复盘显式标记。）
        if (deps.task.getTaskId() && !deps.engine.engineRunning.value && !deps.submissions.busy()) {
          const currentStatus = deps.task.getCurrentTaskStatus()
          const terminalStatus = ['DONE', 'FAILED', 'BASELINED'].includes(currentStatus)
          const nextStatus = terminalStatus ? currentStatus : (payload.success ? 'IDLE' : 'INTERRUPTED')
          deps.task.syncTaskStatus(nextStatus)
        }
        deps.contextWindowScheduleRefresh()
        break
      }
    }
  }

  return {
    handleWsMessage,
  }
}
