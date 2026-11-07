import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DomainMilestones from '../DomainMilestones.vue'

const started = { run_id: 'run', sequence: 1, call_id: '', tool: 'submit', stage: 'started', timestamp: 1, message: '正在生成', issues: [] }
const validating = { ...started, sequence: 2, timestamp: 2, stage: 'validating', message: '正在校验' }

describe('current domain progress', () => {
  it('replaces the previous phase instead of rendering a history', async () => {
    const wrapper = mount(DomainMilestones, { props: { active: true, events: [started] } })
    expect(wrapper.text()).toBe('正在生成')
    await wrapper.setProps({ events: [validating, started, validating] })
    expect(wrapper.text()).toBe('正在校验')
    expect(wrapper.findAll('[data-stage]')).toHaveLength(1)
  })

  it('hides retained phases after success, failure or cancellation, even without a final milestone', async () => {
    const wrapper = mount(DomainMilestones, { props: { active: true, events: [started, validating] } })
    await wrapper.setProps({ active: false })
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })

  it.each(['persisted', 'failed'])('does not replay a %s event while job completion is in transit', stage => {
    const wrapper = mount(DomainMilestones, { props: { active: true, events: [started, { ...validating, stage }] } })
    expect(wrapper.text()).toBe('')
  })

  it('shows validation details only for the current repair phase', async () => {
    const wrapper = mount(DomainMilestones, { props: { active: true, events: [{ ...started, stage: 'repairing', issues: ['缺少响应定义'] }] } })
    expect(wrapper.find('details').text()).toContain('缺少响应定义')
    await wrapper.setProps({ events: [validating] })
    expect(wrapper.find('details').exists()).toBe(false)
  })
})
