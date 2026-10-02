import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import TaskRequirementLinkDrawer from '../TaskRequirementLinkDrawer.vue'
import zh from '@/locales/zh.json'

const assets = vi.hoisted(() => ({ linkRequirementTask: vi.fn() }))
vi.mock('@/composables/useWorkspaceAssets', () => ({
  useWorkspaceAssets: () => ({ ...assets, loading: { value: false }, error: { value: null } }),
}))
const requirement = { id: 'leaf', title: '权限检查', status: 'READY', can_link_task: true }
const mountDrawer = (requirements: typeof requirement[] = []) => mount(TaskRequirementLinkDrawer, {
  props: { workspaceId: 'ws', taskId: 'task', taskName: '定位任务', requirements },
  global: {
    plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })],
    stubs: { Teleport: true, RequirementPickerSidebar: { template: '<button class="choose" @click="$emit(\'select\', requirement)">选择</button>', data: () => ({ requirement }) } },
  },
})

describe('Completed diagnosis requirement linking', () => {
  beforeEach(() => assets.linkRequirementTask.mockReset())

  it('uses the existing association API and emits only after a successful save', async () => {
    const wrapper = mountDrawer()
    expect(wrapper.get('.btn-primary').attributes('disabled')).toBeDefined()
    await wrapper.get('.choose').trigger('click')
    assets.linkRequirementTask.mockResolvedValueOnce(null)
    await wrapper.get('.btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('linked')).toBeUndefined()
    assets.linkRequirementTask.mockResolvedValueOnce({ requirement })
    await wrapper.get('.btn-primary').trigger('click')
    await flushPromises()
    expect(assets.linkRequirementTask).toHaveBeenLastCalledWith('ws', 'leaf', { task_id: 'task', relation_type: 'RELATES_TO' })
    expect(wrapper.emitted('linked')).toEqual([[requirement]])
    wrapper.unmount()
  })

  it('prevents a duplicate requirement association', async () => {
    const wrapper = mountDrawer([requirement])
    await wrapper.get('.choose').trigger('click')
    expect(wrapper.get('.btn-primary').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.btn-primary').text()).toBe('已关联')
    expect(assets.linkRequirementTask).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
