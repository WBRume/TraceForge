import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatStatusCard, HitlCard, PinnedCard } from '../types'

/**
 * 置顶富文本卡片区（独立于对话流）：HITL 交互卡 + 引擎状态卡。
 * HITL 卡片的事实源是会话消息中的 confirmation 元数据（syncConfirmationCards），
 * 引擎状态卡由 WS status 事件与活跃 job 快照驱动。
 */
export function usePinnedCards(options: {
  getMessages: () => any[]
}) {
  const { t } = useI18n()

  const cards = ref<PinnedCard[]>([])

  const activeHitlCards = computed(() => cards.value.filter((c): c is HitlCard => c.type === 'hitl' && !c.answered))
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

  const findHitlByCardId = (cardId: string) => cards.value.find(card => card.type === 'hitl' && card.id === cardId) as HitlCard | undefined

  const findPendingHitlByJobId = (jobId: string) => cards.value.find(card => card.type === 'hitl' && card.job_id === jobId && !card.answered) as HitlCard | undefined

  /**
   * job 状态推进时收敛对应 HITL 卡：非 WAITING_HITL 即视为已答复。
   * 终态给出确定文案，进行中给出已提交文案。
   */
  const markAnsweredForJob = (jobId: string, status: string) => {
    const card = findPendingHitlByJobId(jobId)
    if (!card) return
    card.answered = true
    if (card.answer) return
    if (status === 'FAILED') card.answer = t('chat.hitl_answer_failed')
    else if (status === 'CANCELLED') card.answer = t('chat.hitl_answer_cancelled')
    else if (status === 'SUCCESS') card.answer = t('chat.hitl_answer_done')
    else card.answer = t('chat.hitl_answer_submitted')
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
        && String(candidate?.metadata?.interaction_id || '') === interactionId
      ))
      const existing = cards.value.find(card => card.type === 'hitl' && (card as HitlCard).interaction_id === interactionId)
      const nextCard: HitlCard = {
        id: `confirmation-${message.id}`,
        type: 'hitl',
        interaction_id: interactionId,
        message_id: String(message.id),
        hitl_type: String(confirmation.kind || 'text'),
        prompt: String(message.content || ''),
        options: Array.isArray(confirmation.options) ? confirmation.options : [],
        context: String(message.metadata.context || ''),
        job_id: String(message.metadata.job_id || ''),
        answered: Boolean(answer),
        answer: answer?.content || '',
        tempInput: '',
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
