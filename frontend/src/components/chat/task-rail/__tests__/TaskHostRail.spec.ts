import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { useTaskRailStore } from '@/stores/taskRail'
import TaskHostRail from '../TaskHostRail.vue'
const fetchOptions = vi.hoisted(() => vi.fn())
vi.mock('@/services/requirementOptions', () => ({ fetchRequirementOptions:fetchOptions }))
vi.mock('vue-i18n', () => ({ useI18n:() => ({ t:(key:string) => key }) }))
const requirements = Array.from({ length:120 }, (_, index) => ({ id:`req-${index}`, title:`Requirement ${index}`, status:'READY', source_ref:`REQ-${index}` }))

beforeEach(() => { localStorage.clear(); setActivePinia(createPinia()); fetchOptions.mockResolvedValue({ items:requirements.slice(0, 2), total:120 }) })

describe('global task host rail', () => {
  it('always presents six slots and exchanges a historical requirement without increasing its height', async () => {
    const rail = useTaskRailStore()
    rail.setContext('workspace', 'user')
    const wrapper = mount(TaskHostRail, { props:{ workspaceId:'workspace', collapsed:true } })
    await flushPromises()
    expect(wrapper.findAll('.rail-button')).toHaveLength(6)
    expect(wrapper.findAll('.requirement-slot')).toHaveLength(2)
    rail.selectRequirement(requirements[119]!)
    await flushPromises()
    expect(wrapper.findAll('.rail-button')).toHaveLength(6)
    expect(wrapper.find('.requirement-slot.active').attributes('title')).toContain('Requirement 119')
    await wrapper.findAll('.rail-button')[0]!.trigger('click')
    expect(rail.view).toBe('all')
    wrapper.unmount()
  })

  it('hides empty active slots completely and never renders identifier fragments', async () => {
    fetchOptions.mockResolvedValue({ items:[], total:0 })
    const rail = useTaskRailStore()
    rail.setContext('empty-workspace', 'user')
    const wrapper = mount(TaskHostRail, { props:{ workspaceId:'empty-workspace', collapsed:true } })
    await flushPromises()
    expect(wrapper.findAll('.rail-button')).toHaveLength(4)
    expect(wrapper.findAll('.requirement-slot')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('—')
    rail.selectRequirement({ id:'1125-not-useful', title:'权限管理', status:'DRAFT', source_ref:'d46469cd-f4cc-4bf0-838c-01a0000ff511' })
    await flushPromises()
    expect(wrapper.findAll('.rail-button')).toHaveLength(5)
    expect(wrapper.find('.requirement-mark').text()).toBe('权限')
    expect(wrapper.text()).not.toContain('1125')
    expect(wrapper.text()).not.toContain('d46469cd')
    wrapper.unmount()
  })

  it('preserves two pins when a third requirement temporarily occupies a slot, and isolates users and workspaces', async () => {
    const rail = useTaskRailStore()
    rail.setContext('workspace', 'user')
    await rail.loadSlots()
    rail.togglePin(requirements[0]!)
    rail.togglePin(requirements[1]!)
    rail.selectRequirement(requirements[119]!)
    expect(rail.slots.map((item) => item?.id)).toEqual(['req-0', 'req-119'])
    rail.selectView('all')
    expect(rail.slots.map((item) => item?.id)).toEqual(['req-0', 'req-1'])
    rail.setContext('workspace-2', 'user')
    expect(rail.view).toBe('all')
    expect(rail.pinnedIds).toEqual([])
    rail.setContext('workspace', 'user')
    expect(rail.pinnedIds).toEqual(['req-0', 'req-1'])
    rail.setContext('workspace', 'other-user')
    expect(rail.pinnedIds).toEqual([])
  })
})
