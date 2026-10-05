import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TaskResourcePicker from '../TaskResourcePicker.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import api from '@/utils/api'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

describe('TaskResourcePicker', () => {
  let enabled: boolean
  beforeEach(() => {
    vi.clearAllMocks()
    window.sddDesktop = { runtime: 'electron' } as NonNullable<Window['sddDesktop']>
    enabled = true
    vi.mocked(api.get).mockImplementation(async (url: string) => ({
      data: url.endsWith('/agent-backends')
        ? { effective_agent_backend: 'opencode' }
        : { enabled, items: [
          { id: 'saved', name: '我的本地服务', backend: 'opencode', profile_revision: 3, verification: null },
          { id: 'other-engine', name: 'DSH', backend: 'dsh', profile_revision: 1 },
        ] },
    }))
  })
  afterEach(() => { delete window.sddDesktop })

  it.each(['electron', 'tauri'] as const)('allows %s to select a local resource with its profile revision', async (runtime) => {
    window.sddDesktop = { runtime } as NonNullable<Window['sddDesktop']>
    const wrapper = mount(TaskResourcePicker, { props: { workspaceId: 'ws' } })
    await flushPromises()

    // 默认停留在服务器执行
    expect(wrapper.emitted('change')?.at(-1)).toEqual([{ location: 'SERVER' }])
    expect(wrapper.findComponent(BaseSelect).exists()).toBe(false)

    const localButton = wrapper.findAll('.exec-seg-item')[1]
    expect(localButton.attributes('disabled')).toBeUndefined()
    await localButton.trigger('click')

    expect(localButton.classes()).toContain('active')
    expect(wrapper.getComponent(BaseSelect).props('options')).toEqual([
      { label: '我的本地服务', value: 'saved' },
    ])
    expect(wrapper.emitted('change')?.at(-1)).toEqual([
      { location: 'LOCAL', resource_id: 'saved', profile_revision: 3 },
    ])
    expect(api.post).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps the local segment disabled when the server has not enabled local resources', async () => {
    enabled = false
    const wrapper = mount(TaskResourcePicker, { props: { workspaceId: 'ws' } })
    await flushPromises()

    const localButton = wrapper.findAll('.exec-seg-item')[1]
    expect(localButton.attributes('disabled')).toBeDefined()
    expect(wrapper.findComponent(BaseSelect).exists()).toBe(false)
    wrapper.unmount()
  })

  it('hides the execution picker in browsers while retaining server execution', async () => {
    delete window.sddDesktop
    const wrapper = mount(TaskResourcePicker, { props: { workspaceId: 'ws' } })
    await flushPromises()
    expect(wrapper.find('.resource-picker').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
    expect(api.get).not.toHaveBeenCalled()
    expect(wrapper.emitted('change')?.at(-1)).toEqual([{ location: 'SERVER' }])
    await wrapper.setProps({ workspaceId: 'other-ws' })
    expect(wrapper.emitted('change')?.at(-1)).toEqual([{ location: 'SERVER' }])
    expect(api.get).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
