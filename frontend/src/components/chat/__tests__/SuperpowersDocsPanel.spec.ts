import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import SuperpowersDocsPanel from '@/components/chat/SuperpowersDocsPanel.vue'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))

vi.mock('@/utils/api', () => ({ default: apiMock }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

const indexCalls = () => apiMock.get.mock.calls
  .filter(([url]) => String(url).endsWith('/superpowers-docs'))

const mountPanel = (props: { wsId: string; taskId: string; visible?: boolean; readonly?: boolean }) => mount(SuperpowersDocsPanel, {
  props,
  global: { mocks: { $t: (key: string) => key } },
})

describe('SuperpowersDocsPanel lazy loading', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.put.mockReset()
    apiMock.get.mockResolvedValue({
      data: { task_id: 't1', root_relative_path: 'docs/superpowers', plans: [], specs: [] },
    })
  })

  it('does not request the index while the panel is hidden', async () => {
    mountPanel({ wsId: 'w', taskId: 't1', visible: false })
    await flushPromises()
    expect(indexCalls()).toHaveLength(0)
  })

  it('loads the index once the panel becomes visible', async () => {
    const wrapper = mountPanel({ wsId: 'w', taskId: 't1', visible: false })
    await flushPromises()
    expect(indexCalls()).toHaveLength(0)

    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(indexCalls()).toHaveLength(1)

    await wrapper.setProps({ visible: false })
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(indexCalls()).toHaveLength(2)
  })

  it('reloads the index for a new task while visible', async () => {
    const wrapper = mountPanel({ wsId: 'w', taskId: 't1', visible: true })
    await flushPromises()
    expect(indexCalls()).toHaveLength(1)

    await wrapper.setProps({ taskId: 't2' })
    await flushPromises()
    expect(indexCalls()).toHaveLength(2)
    expect(String(indexCalls()[1]?.[0])).toContain('/tasks/t2/superpowers-docs')
  })
})
