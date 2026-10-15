import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import BasicInfoStep, { type WorkspaceBasicInfo } from '../BasicInfoStep.vue'

vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

function mountStep(path = '') {
  const wrapper = mount(BasicInfoStep, {
    props: {
      modelValue: { name: '', description: '', project_path: path },
      workspaceBase: '',
      'onUpdate:modelValue': (value: WorkspaceBasicInfo) => wrapper.setProps({ modelValue: value }),
    },
    global: { mocks: { $t: (key: string) => key } },
  })
  return wrapper
}

describe('BasicInfoStep remote root configuration', () => {
  it('fills the path when the root configuration arrives after the name', async () => {
    const wrapper = mountStep()
    await wrapper.findAll('input')[0]!.setValue('Remote workspace')
    await wrapper.setProps({ workspaceBase: '/opt/traceforge/workspace' })
    expect(wrapper.findAll('input')[1]!.element.value).toBe('/opt/traceforge/workspace/Remote workspace')
    wrapper.unmount()
  })

  it('preserves a manually entered path when configuration arrives', async () => {
    const wrapper = mountStep()
    await wrapper.findAll('input')[0]!.setValue('Remote workspace')
    await wrapper.findAll('input')[1]!.setValue('/opt/traceforge/workspace/custom')
    await wrapper.setProps({ workspaceBase: '/opt/traceforge/workspace' })
    expect(wrapper.findAll('input')[1]!.element.value).toBe('/opt/traceforge/workspace/custom')
    wrapper.unmount()
  })

  it('preserves an existing path after returning from the repository step', async () => {
    const wrapper = mountStep('/opt/traceforge/workspace/custom')
    await wrapper.setProps({ modelValue: { name: 'Remote workspace', description: '', project_path: '/opt/traceforge/workspace/custom' } })
    await wrapper.setProps({ workspaceBase: '/opt/traceforge/workspace' })
    expect(wrapper.findAll('input')[1]!.element.value).toBe('/opt/traceforge/workspace/custom')
    wrapper.unmount()
  })
})
