import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatAiJob, ChatStatusCard, HitlCard, PinnedCard } from '../types'
import { isJobExecuting } from '../jobs/useChatJobs'

/**
 * 置顶富文本卡片区（独立于对话流）：HITL 交互卡 + 引擎状态卡。
 * 问题内容来自 confirmation 消息；交互资格由当前会话代次与所属作业运行态共同决定，
 * 引擎状态卡由 WS status 事件与活跃 job 快照驱动。
 */
export function usePinnedCards(options: {
  getMessages: () => any[]
  getJobs: () => ChatAiJob[]
  getCurrentTask: () => { status?: string; session_generation?: number | null } | null | undefined
}) {
  const { t } = useI18n()

  const cards = ref<PinnedCard[]>([])

  const canInteract = (card: HitlCard) => {
    const task = options.getCurrentTask()
    if (!task || ['INTERRUPTED', 'DONE', 'FAILED', 'BASELINED'].includes(String(task.status))) return false
    if (card.session_generation == null || task.session_generation == null
      || Number(card.session_generation) !== Number(task.session_generation)) return false
    return options.getJobs().some(job => job.id === card.job_id && isJobExecuting(job.status)
      && (job.session_generation == null || Number(job.session_generation) === Number(task.session_generation)))
  }
  // 历史中的问题不代表仍可回答；仅当前会话中仍执行的所属作业可以展示交互。
  const activeHitlCards = computed(() => cards.value.filter((c): c is HitlCard => (
    c.type === 'hitl' && !c.answered && canInteract(c)
  )))
  const statusCards = computed(() => cards.value.filter((c): c is ChatStatusCard => c.type === 'status'))

  const clear = () => {
    cards.value = []
  }

  const dropStatusCards = () => {
    cards.value = cards.value.filter(card => card.type !== 'status')
  }

  const dropByTypes = (types: string[]) => {
    cards.value = cards.value.filter(card => !types.includes(card.type))
  }

  const setStatusCards = (next: ChatStatusCard[]) => {
    dropStatusCards()
    cards.value.push(...next)
  }

  const pushStatusCard = (card: ChatStatusCard) => {
    cards.value.push(card)
  }

  const hasStatusCard = () => cards.value.some(card => card.type === 'status')

  const findHitlByCardId = (cardId: string) => activeHitlCards.value.find(card => card.id === cardId)

  const findPendingHitlByJobId = (jobId: string) => activeHitlCards.value.find(card => card.job_id === jobId)

  /**
   * 作业结束或中断时收起确认卡；RUNNING 快照不能代表用户已答复。
   */
  const markAnsweredForJob = (jobId: string, status: string) => {
    if (!['SUCCESS', 'FAILED', 'CANCELLED', 'REVERTED', 'INTERRUPTED'].includes(status)) return
    for (const card of cards.value) {
      if (card.type !== 'hitl' || card.job_id !== jobId || card.answered) continue
      card.answered = true
      if (card.answer) continue
      if (status === 'FAILED') card.answer = t('chat.hitl_answer_failed')
      else if (status === 'CANCELLED') card.answer = t('chat.hitl_answer_cancelled')
      else if (status === 'SUCCESS') card.answer = t('chat.hitl_answer_done')
      else card.answer = t('chat.hitl_answer_submitted')
    }
  }

  /** 从会话消息重建 HITL 卡片：确认消息存在则建卡/更新，确认消息消失则撤卡。 */
  const syncConfirmationCards = () => {
    const messages = options.getMessages()
    const confirmations = messages.filter((message) => (
      message?.role === 'assistant'
      && message?.metadata?.confirmation?.interaction_id
    ))
    const confirmationIds = new Set(confirmations.map(message => (
      String(message.metadata.confirmation.interaction_id)
    )))
    cards.value = cards.value.filter(card => (
      card.type !== 'hitl' || confirmationIds.has(String((card as HitlCard).interaction_id || ''))
    ))
    for (const message of confirmations) {
      const confirmation = message.metadata.confirmation
      const interactionId = String(confirmation.interaction_id)
      const answer = messages.find((candidate) => (
        candidate?.role === 'user'
        && (!candidate.delivery_status || candidate.delivery_status === 'sent')
        && String(candidate?.metadata?.interaction_id || '') === interactionId
      ))
      const resolution = messages.find((candidate) => (
        candidate?.role === 'assistant'
        && String(candidate?.metadata?.confirmation_resolution?.interaction_id || '') === interactionId
      ))
      const existing = cards.value.find((card): card is HitlCard => card.type === 'hitl' && card.interaction_id === interactionId)
      const nextCard: HitlCard = {
        id: `confirmation-${message.id}`,
        type: 'hitl',
        interaction_id: interactionId,
        message_id: String(message.id),
        hitl_type: String(confirmation.kind || 'text'),
        prompt: String(message.content || ''),
        options: Array.isArray(confirmation.options) ? confirmation.options : [],
        fields: Array.isArray(confirmation.fields) ? confirmation.fields : [],
        context: String(message.metadata.context || ''),
        job_id: String(confirmation.job_id || message.metadata.job_id || ''),
        session_generation: message.session_generation ?? null,
        answered: Boolean(resolution) || Boolean(answer) || Boolean(existing?.answered),
        answer: resolution?.content || answer?.content || existing?.answer || '',
        tempInput: existing?.tempInput || '',
        created_at: message.created_at || new Date().toISOString(),
      }
      if (existing) Object.assign(existing, nextCard)
      else cards.value.push(nextCard)
    }
  }

  return {
    cards,
    activeHitlCards,
    statusCards,
    clear,
    dropStatusCards,
    dropByTypes,
    setStatusCards,
    pushStatusCard,
    hasStatusCard,
    findHitlByCardId,
    findPendingHitlByJobId,
    markAnsweredForJob,
    syncConfirmationCards,
  }
}
