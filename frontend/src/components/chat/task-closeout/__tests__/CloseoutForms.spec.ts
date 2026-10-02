import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import CompleteCloseoutForm from '../CompleteCloseoutForm.vue'
import FailCloseoutForm from '../FailCloseoutForm.vue'
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
})
