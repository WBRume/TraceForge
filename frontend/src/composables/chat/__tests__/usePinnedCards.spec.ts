import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

import { usePinnedCards } from '../cards/usePinnedCards'

const confirmationMessage = (id: string, interactionId: string, kind = 'text') => ({
  id,
  role: 'assistant',
  content: `confirm-${id}`,
  metadata: { confirmation: { interaction_id: interactionId, kind, options: ['a', 'b'] } },
})

describe('usePinnedCards', () => {
  it('builds HITL cards from confirmation messages and drops answered ones', () => {
    let messages: any[] = [confirmationMessage('m1', 'i1')]
    const store = usePinnedCards({ getMessages: () => messages })

    store.syncConfirmationCards()
    expect(store.activeHitlCards.value).toHaveLength(1)
    const card = store.activeHitlCards.value[0]
    expect(card.interaction_id).toBe('i1')
    expect(card.id).toBe('confirmation-m1')
    expect(card.options).toEqual(['a', 'b'])

    // 用户回答后（存在带相同 interaction_id 的 user 消息）卡片变为已答复
    messages = [...messages, { id: 'm2', role: 'user', content: 'y', metadata: { interaction_id: 'i1' } }]
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value).toHaveLength(0)
    const answered = store.cards.value.find(item => item.type === 'hitl') as any
    expect(answered.answered).toBe(true)
    expect(answered.answer).toBe('y')

    // 确认消息消失（被撤销等）后卡片撤除
    messages = []
    store.syncConfirmationCards()
    expect(store.cards.value.filter(item => item.type === 'hitl')).toHaveLength(0)
  })

  it('marks the pending card answered with terminal-specific copy when a job settles', () => {
    let messages: any[] = [confirmationMessage('m1', 'i1')]
    const store = usePinnedCards({ getMessages: () => messages })
    store.syncConfirmationCards()
    ;(store.cards.value[0] as any).job_id = 'j1'

    store.markAnsweredForJob('j1', 'FAILED')
    expect(store.findPendingHitlByJobId('j1')).toBeUndefined()
    expect((store.cards.value[0] as any).answer).toBe('chat.hitl_answer_failed')

    // 已答复的卡不会被再次收敛
    store.markAnsweredForJob('j1', 'SUCCESS')
    expect((store.cards.value[0] as any).answer).toBe('chat.hitl_answer_failed')

    // 新的未答复卡按状态获得对应文案
    messages = [confirmationMessage('m2', 'i2')]
    store.syncConfirmationCards()
    ;(store.cards.value[0] as any).job_id = 'j2'
    store.markAnsweredForJob('j2', 'SUCCESS')
    expect((store.cards.value[0] as any).answer).toBe('chat.hitl_answer_done')
  })

  it('manages status cards as a replaceable group', () => {
    const store = usePinnedCards({ getMessages: () => [] })
    store.pushStatusCard({ id: 's1', type: 'status', status: 'RUNNING' })
    store.pushStatusCard({ id: 's2', type: 'status', status: 'INIT' })
    expect(store.statusCards.value).toHaveLength(2)
    expect(store.hasStatusCard()).toBe(true)

    store.setStatusCards([{ id: 's3', type: 'status', status: 'RUNNING' }])
    expect(store.statusCards.value.map(card => card.id)).toEqual(['s3'])

    store.dropStatusCards()
    expect(store.statusCards.value).toHaveLength(0)
    expect(store.hasStatusCard()).toBe(false)
  })
})
