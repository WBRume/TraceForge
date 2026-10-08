import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

import { usePinnedCards } from '../cards/usePinnedCards'

const confirmationMessage = (id: string, interactionId: string, kind = 'text') => ({
  id,
  role: 'assistant',
  content: `confirm-${id}`,
  session_generation: 1,
  metadata: { confirmation: { interaction_id: interactionId, kind, options: ['a', 'b'], job_id: 'j1' } },
})

const createStore = (getMessages: () => any[]) => {
  const task = ref({ status: 'CODING', session_generation: 1 })
  const jobs = ref<any[]>([{ id: 'j1', status: 'RUNNING', session_generation: 1 }])
  const store = usePinnedCards({ getMessages, getJobs: () => jobs.value, getCurrentTask: () => task.value })
  return { store, task, jobs }
}

describe('usePinnedCards', () => {
  it.each(['answered', 'cancelled', 'approved', 'rejected', 'closed'])('closes a %s provider interaction while its job keeps running, including after reload', (status) => {
    const messages: any[] = [confirmationMessage('m1', 'i1')]
    const { store } = createStore(() => messages)
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value).toHaveLength(1)
    messages.push({ id: 'r1', role: 'assistant', content: `provider-${status}`, metadata: {
      confirmation_resolution: { interaction_id: 'i1', status, answer: { q0: 'A' } },
    } })
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value).toHaveLength(0)
    expect((store.cards.value[0] as any).answer).toBe(`provider-${status}`)
    const reloaded = createStore(() => messages).store
    reloaded.syncConfirmationCards()
    expect(reloaded.activeHitlCards.value).toHaveLength(0)
  })

  it.each(['failed', 'sending', 'processing', 'conflict', 'pending', 'unknown'])('does not treat a %s local submission as an accepted answer', (status) => {
    const messages: any[] = [confirmationMessage('m1', 'i1'),
      { role: 'user', content: 'late', delivery_status: status, metadata: { interaction_id: 'i1' } },
    ]
    const { store } = createStore(() => messages)
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value).toHaveLength(1)
  })
  it('restores a questionnaire and its job from persisted confirmation metadata', () => {
    const fields = [{ key: 'build', type: 'string', title: '构建工具' }]
    const message = confirmationMessage('m1', 'i1', 'form')
    Object.assign(message.metadata.confirmation, { fields, job_id: 'j1' })
    const { store } = createStore(() => [message])
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value[0]).toMatchObject({ hitl_type: 'form', fields, job_id: 'j1' })
    store.markAnsweredForJob('j1', 'RUNNING')
    expect(store.activeHitlCards.value).toHaveLength(1)
  })
  it('builds HITL cards from confirmation messages and drops answered ones', () => {
    let messages: any[] = [confirmationMessage('m1', 'i1')]
    const { store } = createStore(() => messages)

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
    const { store } = createStore(() => messages)
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
    const { store } = createStore(() => [])
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

  it('does not reopen stopped questions when history is rebuilt or the store is recreated', () => {
    const message = confirmationMessage('m1', 'i1', 'form')
    const { store, jobs } = createStore(() => [message])
    store.syncConfirmationCards()
    store.markAnsweredForJob('j1', 'INTERRUPTED')
    jobs.value = [{ id: 'j1', status: 'INTERRUPTED', session_generation: 1 }]
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value).toHaveLength(0)
    expect(store.findHitlByCardId('confirmation-m1')).toBeUndefined()
    store.clear()
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value).toHaveLength(0)
    const restored = createStore(() => [message])
    restored.jobs.value = []
    restored.store.syncConfirmationCards()
    expect(restored.store.activeHitlCards.value).toHaveLength(0)
  })

  it('shows only the new generation after initialization and closes it on another stop', () => {
    let messages = [confirmationMessage('m1', 'i1', 'form')]
    const { store, task, jobs } = createStore(() => messages)
    store.syncConfirmationCards()
    store.markAnsweredForJob('j1', 'INTERRUPTED')
    store.clear()
    task.value = { status: 'CODING', session_generation: 2 }
    jobs.value = [{ id: 'j2', status: 'RUNNING', session_generation: 2 }]
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value).toHaveLength(0)
    messages = [...messages, {
      ...confirmationMessage('m2', 'i2', 'form'), session_generation: 2,
      metadata: { confirmation: { interaction_id: 'i2', kind: 'form', options: [], job_id: 'j2' } },
    }]
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value.map(card => card.interaction_id)).toEqual(['i2'])
    jobs.value = [{ id: 'j2', status: 'INTERRUPTED', session_generation: 2 }]
    store.markAnsweredForJob('j2', 'INTERRUPTED')
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value).toHaveLength(0)
  })

  it('closes all questions belonging to a terminal job and preserves closure across resync', () => {
    const { store } = createStore(() => [confirmationMessage('m1', 'i1'), confirmationMessage('m2', 'i2')])
    store.syncConfirmationCards()
    store.markAnsweredForJob('j1', 'CANCELLED')
    expect(store.activeHitlCards.value).toHaveLength(0)
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value).toHaveLength(0)
  })

  it('waits for the owning job snapshot and reacts to job or task interruption without message changes', () => {
    const { store, jobs, task } = createStore(() => [confirmationMessage('m1', 'i1')])
    jobs.value = []
    store.syncConfirmationCards()
    expect(store.activeHitlCards.value).toHaveLength(0)
    jobs.value = [{ id: 'j1', status: 'RUNNING', session_generation: 1 }]
    expect(store.activeHitlCards.value).toHaveLength(1)
    task.value.status = 'INTERRUPTED'
    expect(store.activeHitlCards.value).toHaveLength(0)
  })
})
