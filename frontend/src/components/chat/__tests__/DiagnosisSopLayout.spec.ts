import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import DiagnosisSopLayout from '../diagnosis-playbook/DiagnosisSopLayout.vue'
import type { GuideSession } from '@/types/diagnosisPlaybook'

const guide = (): GuideSession => ({ task_id: 'task', version: 3, session_generation: 1, active_phase: 'HYPOTHESIZE', completed: false,
  guide: { title: '死锁排查', version: '1', context: {}, steps: [] }, error: null,
  confirmations: { PROBE: { user_id: 'u', report_digest: 'digest' } },
  hypotheses: [{ id: 'H1', claim: '锁顺序相反', prediction: '互相等待', falsifier: '单向等待', evidence: [{ reference: 'log:14', observation: '事务互锁' }], state: 'PROPOSED', verdict: 'SUPPORTED', verdict_reason: '日志与预测一致' }],
  reports: { HYPOTHESIZE: { phase: 'HYPOTHESIZE', findings: '两个事务互锁', evidence: [{ reference: 'log:14', observation: '事务互锁' }], code: 'assert deadlock()', language: 'python', outcome: 'NOT_RUN', ready_for_review: true, job_id: 'job' } },
})
const props = () => ({ enabled: true, guide: guide(), run: null, busy: false, running: false, error: '', tail: '', canContinue: false })
it('links navigation, real evidence and human approval while preserving chat input', async () => {
  const wrapper = mount(DiagnosisSopLayout, { props: props(), slots: { default: '<textarea aria-label="发送消息" />' } })
  expect(wrapper.find('.sop-conversation textarea').exists()).toBe(true)
  expect(wrapper.findAll('.nav-item')[2]!.attributes('disabled')).toBeDefined()
  await wrapper.find('.hypothesis').trigger('click')
  expect(wrapper.find('.sop-workspace').text()).toContain('互相等待')
  expect(wrapper.find('.sop-workspace').text()).toContain('log:14')
  const advance = () => wrapper.find('.primary')
  expect(advance().attributes('disabled')).toBeDefined()
  await wrapper.findAll('button').find(b => b.text() === '确认根因')!.trigger('click')
  expect(wrapper.emitted('guideCommand')?.[0]).toEqual(['approve_hypothesis', 'H1'])
  const state = guide()
  state.hypotheses[0]!.state = 'APPROVED'
  await wrapper.setProps({ guide: state })
  expect(advance().attributes('disabled')).toBeUndefined()
  await advance().trigger('click')
  expect(wrapper.emitted('guideCommand')?.[1]).toEqual(['advance', undefined])
  await wrapper.setProps({ running: true })
  expect(advance().attributes('disabled')).toBeDefined()
  wrapper.unmount()
})
it('keeps ordinary tasks as a single conversation', () => {
  const wrapper = mount(DiagnosisSopLayout, { props: { ...props(), enabled: false }, slots: { default: '<textarea />' } })
  expect(wrapper.find('.sop-layout').exists()).toBe(false)
  expect(wrapper.find('.ordinary-conversation textarea').exists()).toBe(true)
  wrapper.unmount()
})

it('offers root confirmation immediately on stage entry without selecting a tree node', async () => {
  const state = guide()
  state.hypotheses = [1, 2, 3].map(i => ({ ...state.hypotheses[0]!, id: `H${i}`, claim: `假说${i}` }))
  const wrapper = mount(DiagnosisSopLayout, { props: { ...props(), guide: state } })
  expect(wrapper.findAll('.hypothesis-review')).toHaveLength(3)
  expect(wrapper.findAll('.hypothesis').every(node => node.text().includes('候选根因'))).toBe(true)
  expect(wrapper.find('.primary').attributes('disabled')).toBeDefined()
  const confirm = wrapper.find('[aria-label="假说 H2"] button')
  expect(confirm.attributes('disabled')).toBeUndefined()
  await confirm.trigger('click')
  expect(wrapper.emitted('guideCommand')?.[0]).toEqual(['approve_hypothesis', 'H2'])
  const confirmed = { ...state, hypotheses: state.hypotheses.map(h => h.id === 'H2' ? { ...h, state: 'APPROVED' as const } : h) }
  await wrapper.setProps({ guide: confirmed })
  expect(wrapper.find('.primary').attributes('disabled')).toBeUndefined()
  expect(wrapper.findAll('.hypothesis')[1]!.text()).toContain('已确认')
  await wrapper.findAll('.hypothesis')[0]!.trigger('click')
  expect(wrapper.findAll('.hypothesis-review')).toHaveLength(1)
  await wrapper.findAll('.nav-item')[1]!.trigger('click')
  expect(wrapper.findAll('.hypothesis-review')).toHaveLength(3)
  wrapper.unmount()
})

it('keeps root confirmation disabled without evidence or while the agent is running', async () => {
  const state = guide()
  state.hypotheses[0]!.evidence = []
  state.hypotheses[0]!.verdict = 'UNTESTED'
  const wrapper = mount(DiagnosisSopLayout, { props: { ...props(), guide: state } })
  expect(wrapper.find('.hypothesis-review').text()).not.toContain('确认根因')
  expect(wrapper.find('.hypothesis').text()).toContain('待验证')
  await wrapper.setProps({ guide: guide(), running: true })
  expect(wrapper.find('.hypothesis-review button').attributes('disabled')).toBeDefined()
  wrapper.unmount()
})

it('shows refuted results and reasons without offering root confirmation or manual exclusion', async () => {
  const state = guide()
  state.hypotheses = [
    { ...state.hypotheses[0]!, id: 'H1', verdict: 'REFUTED', verdict_reason: '直接查询正常，预测不成立' },
    { ...state.hypotheses[0]!, id: 'H2' },
    { ...state.hypotheses[0]!, id: 'H3', verdict: 'REFUTED', verdict_reason: '响应对象独立，预测不成立' },
  ]
  const wrapper = mount(DiagnosisSopLayout, { props: { ...props(), guide: state } })
  for (const id of ['H1', 'H3']) {
    const card = wrapper.find(`[aria-label="假说 ${id}"]`)
    expect(card.text()).toContain('已证伪')
    expect(card.text()).toContain('预测不成立')
    expect(card.findAll('button')).toHaveLength(0)
  }
  expect(wrapper.find('[aria-label="假说 H2"]').text()).toContain('确认根因')
  expect(wrapper.findAll('.hypothesis')[0]!.text()).toContain('已证伪')
  await wrapper.setProps({ guide: { ...state, hypotheses: state.hypotheses.map(h => ({ ...h, verdict: 'REFUTED' as const })) } })
  expect(wrapper.find('.review-hint').text()).toContain('暂无有证据支持的候选根因')
  expect(wrapper.find('.primary').attributes('disabled')).toBeDefined()
  wrapper.unmount()
})

it('shows incoming hypotheses without resetting the active stage and exposes automatic execution', async () => {
  const initial = guide()
  initial.active_phase = 'PROBE'
  initial.hypotheses = []
  const wrapper = mount(DiagnosisSopLayout, { props: { ...props(), guide: initial } })
  expect(wrapper.find('.sop-nav').text()).toContain('暂无假说')
  await wrapper.setProps({ guide: guide() })
  expect(wrapper.find('.sop-nav [aria-current="step"]').text()).toContain('假说与实验')
  expect(wrapper.findAll('.hypothesis')).toHaveLength(1)
  const toggle = wrapper.find('[role="switch"]')
  expect(wrapper.find('.automation-control').exists()).toBe(false)
  expect(toggle.element.closest('.toolbar-actions')).not.toBeNull()
  await toggle.setValue(true)
  expect(wrapper.emitted('guideCommand')?.[0]).toEqual(['enable_auto', undefined])
  await wrapper.setProps({ guide: { ...guide(), auto_run: true }, running: true })
  expect(toggle.attributes('disabled')).toBeUndefined()
  await toggle.setValue(false)
  expect(wrapper.emitted('guideCommand')?.[1]).toEqual(['disable_auto', undefined])
  wrapper.unmount()
})

