import { describe, expect, it, vi } from 'vitest'
import { mount, shallowMount } from '@vue/test-utils'
import CompleteCloseoutForm from '../CompleteCloseoutForm.vue'
import FailCloseoutForm from '../FailCloseoutForm.vue'
import TaskCloseoutPanel from '../TaskCloseoutPanel.vue'
vi.mock('vue-i18n', () => ({ useI18n:() => ({ t:(key:string) => key }) }))
const global = { mocks:{ $t:(key:string) => key } }
describe('closeout requirement and optional evidence', () => {
  it('selects a requirement in diagnosis completion without adding it to development closeout', async () => {
    const selectedRequirement = { id:'leaf', title:'Diagnosed requirement', status:'READY' }
    const wrapper = mount(CompleteCloseoutForm, { props:{ taskType:'DIAGNOSIS', selectedRequirement }, global })
    await wrapper.find('.closeout-requirement-entry').trigger('click')
    expect(wrapper.emitted('toggle-requirement-picker')).toHaveLength(1)
    await wrapper.find('textarea').setValue('Root cause confirmed')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({ requirement_id:'leaf', completion_summary:'Root cause confirmed' })
    await wrapper.setProps({ taskType:'DEVELOPMENT' })
    expect(wrapper.find('.closeout-requirement-entry').exists()).toBe(false)
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[1]?.[0]).toMatchObject({ requirement_id:undefined })
    wrapper.unmount()
  })
  it('submits failure without attachments while requiring a failure summary', async () => {
    const wrapper = mount(FailCloseoutForm, { global })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')).toBeUndefined()
    await wrapper.find('textarea').setValue('Environment could not reproduce the issue')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]).toEqual([expect.objectContaining({ failure_summary:'Environment could not reproduce the issue' }), []])
    expect(wrapper.findAll('label.required').some((label) => label.text().includes('failure_evidence'))).toBe(false)
    wrapper.unmount()
  })

  it('uses diagnosis methods and resets the selected method when task type changes', async () => {
    const wrapper = mount(CompleteCloseoutForm, { props: { taskType: 'DIAGNOSIS' }, global })
    expect(wrapper.text()).toContain('chat.closeout.diagnosis.landing_method')
    expect(wrapper.find('textarea').attributes('placeholder')).toContain('diagnosis.completion_summary_placeholder')
    await wrapper.find('.select-trigger').trigger('click')
    const options = wrapper.findAll('.option-item')
    expect(options.map(option => option.text())).toEqual([
      'chat.closeout.diagnosis.landing.ai_diagnosed',
      'chat.closeout.diagnosis.landing.human_assisted_diagnosis',
      'chat.closeout.diagnosis.landing.human_diagnosed',
      'chat.closeout.diagnosis.landing.ai_clue_only',
    ])
    await options[0]!.trigger('click')
    await wrapper.find('textarea').setValue('Root cause confirmed with logs')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({ landing_method: 'AI_DIAGNOSED' })
    await wrapper.setProps({ taskType: 'DEVELOPMENT' })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[1]?.[0]).toMatchObject({ landing_method: 'HUMAN_ADJUSTED' })
    expect(wrapper.text()).not.toContain('chat.closeout.diagnosis.')
    wrapper.unmount()
  })

  it('submits investigation stages and blockers without leaking development categories', async () => {
    const wrapper = mount(FailCloseoutForm, { props: { taskType: 'DIAGNOSIS' }, global })
    const selects = wrapper.findAll('.base-select')
    await selects[0]!.find('.select-trigger').trigger('click')
    expect(selects[0]!.text()).not.toContain('failure_stage_options.coding')
    const reproduction = selects[0]!.findAll('.option-item').find(option => option.text().endsWith('.reproduction'))!
    await reproduction.trigger('click')
    await selects[1]!.find('.select-trigger').trigger('click')
    expect(selects[1]!.text()).not.toContain('failure_reason_options.compile_error')
    const reason = selects[1]!.findAll('.option-item').find(option => option.text().endsWith('.not_reproducible'))!
    await reason.trigger('click')
    await wrapper.find('textarea').setValue('Cannot reproduce with available logs')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]).toEqual([{
      failure_stage: 'REPRODUCTION', failure_reason: 'NOT_REPRODUCIBLE', failure_summary: 'Cannot reproduce with available logs',
    }, []])
    await wrapper.setProps({ taskType: 'DEVELOPMENT' })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[1]?.[0]).toMatchObject({ failure_stage: 'CODING', failure_reason: 'OTHER' })
    wrapper.unmount()
  })

  it('passes the diagnosis task type to both panel forms', async () => {
    const wrapper = shallowMount(TaskCloseoutPanel, {
      props: { show: true, mode: 'fail', workspaceId: 'ws', taskId: 'task', taskType: 'DIAGNOSIS' },
      global: { ...global, stubs: { Teleport: true } },
    })
    expect(wrapper.findComponent(FailCloseoutForm).props('taskType')).toBe('DIAGNOSIS')
    await wrapper.setProps({ mode: 'complete' })
    expect(wrapper.findComponent(CompleteCloseoutForm).props('taskType')).toBe('DIAGNOSIS')
    wrapper.unmount()
  })
})
