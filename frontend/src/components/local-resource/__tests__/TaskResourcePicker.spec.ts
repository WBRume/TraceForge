import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TaskResourcePicker from '../TaskResourcePicker.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import api from '@/utils/api'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

describe('TaskResourcePicker', () => {
  let enabled: boolean
  beforeEach(() => {
    vi.clearAllMocks()
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

  it('selects a saved resource without requiring the obsolete full verification', async () => {
    const wrapper = mount(TaskResourcePicker, { props: { workspaceId: 'ws' } })
    await flushPromises()
    const select = wrapper.getComponent(BaseSelect)
    expect(select.props('options')).toEqual([
      { label: '服务器资源', value: '' },
      { label: '本地 · 我的本地服务', value: 'saved', disabled: false },
    ])
    await select.vm.$emit('update:modelValue', 'saved')
    expect(wrapper.emitted('change')?.at(-1)).toEqual([
      { location: 'LOCAL', resource_id: 'saved', profile_revision: 3 },
    ])
    expect(api.post).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps local resources disabled when the server has not enabled them', async () => {
    enabled = false
    const wrapper = mount(TaskResourcePicker, { props: { workspaceId: 'ws' } })
    await flushPromises()
    expect(wrapper.getComponent(BaseSelect).props('options')[1].disabled).toBe(true)
    wrapper.unmount()
  })
})
