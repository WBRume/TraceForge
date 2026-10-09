import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import PlanDocsPanel from '@/components/chat/PlanDocsPanel.vue'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))

vi.mock('@/utils/api', () => ({ default: apiMock }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

const indexCalls = () => apiMock.get.mock.calls
  .filter(([url]) => String(url).endsWith('/plan-docs'))

const mountPanel = (props: { wsId: string; taskId: string; visible?: boolean; readonly?: boolean }) => mount(PlanDocsPanel, {
  props,
  global: { mocks: { $t: (key: string) => key }, stubs: { RouterLink: RouterLinkStub } },
})

describe('PlanDocsPanel lazy loading', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.put.mockReset()
    apiMock.get.mockResolvedValue({
      data: { task_id: 't1', root_relative_path: 'docs/plans', configured: true, baseline_available: true, plans: [], specs: [] },
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
    expect(String(indexCalls()[1]?.[0])).toContain('/tasks/t2/plan-docs')
  })

  it('shows a gentle setup hint without fetching content when unconfigured', async () => {
    apiMock.get.mockResolvedValue({ data: { configured: false, baseline_available: false, root_relative_path: '', plans: [], specs: [] } })
    const wrapper = mountPanel({ wsId: 'w', taskId: 't1' })
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toContain('chat.plan_docs_not_configured')
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.find('.panel-subtitle').exists()).toBe(false)
    expect(apiMock.get).toHaveBeenCalledTimes(1)
    expect(wrapper.getComponent(RouterLinkStub).props('to')).toEqual({ path: '/workspaces/w/settings', query: { section: 'plan_docs' } })
  })

  it('ignores a late index response after switching to an unconfigured workspace', async () => {
    let resolveOld!: (value: unknown) => void
    apiMock.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const wrapper = mountPanel({ wsId: 'w', taskId: 't1' })
    apiMock.get.mockResolvedValue({ data: { configured: false, root_relative_path: '', plans: [], specs: [] } })
    await wrapper.setProps({ wsId: 'other', taskId: 't2' })
    await flushPromises()
    resolveOld({ data: { configured: true, root_relative_path: 'old', plans: [{ name: 'old.md', section_path: 'old.md' }], specs: [] } })
    await flushPromises()
    expect(wrapper.text()).toContain('chat.plan_docs_not_configured')
    expect(wrapper.text()).not.toContain('old.md')
  })

  it('explains an unavailable baseline instead of displaying the full directory', async () => {
    apiMock.get.mockResolvedValue({ data: { configured: true, baseline_available: false, root_relative_path: 'docs', plans: [], specs: [] } })
    const wrapper = mountPanel({ wsId: 'w', taskId: 't1' })
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toBe('chat.plan_docs_baseline_unavailable')
  })
})
