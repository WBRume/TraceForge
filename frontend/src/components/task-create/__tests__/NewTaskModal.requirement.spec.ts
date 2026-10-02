import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import NewTaskModal from '../NewTaskModal.vue'
import { useProvisioningStore } from '@/stores/provisioning'
const api = vi.hoisted(() => ({ get:vi.fn(), post:vi.fn() }))
vi.mock('@/utils/api', () => ({ default:api }))
vi.mock('vue-i18n', () => ({ useI18n:() => ({ t:(key:string) => key }) }))
vi.mock('element-plus', () => ({ ElMessage:{ error:vi.fn(), warning:vi.fn() } }))
const leaf = { id:'child', title:'Payment checks', status:'READY', child_count:0, can_link_task:true,
  body:'# Payment document\nValidate payments.', acceptance_criteria:['Reject expired tokens'], source_metadata:{ task_prompt:'Implement payment checks' } }
beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  api.get.mockReset()
  api.post.mockReset()
  api.post.mockResolvedValue({ data:{ job_id:'requirement-job', task_id:'created-task' } })
  api.get.mockImplementation(async (url:string) => ({ data: url.endsWith('/requirements/child') ? { requirement:leaf }
    : url.endsWith('/requirement-options') ? { items:[leaf], total:1 } : { repositories:[], items:[], options:[] } }))
})
afterEach(() => { useProvisioningStore().clearPendingTaskSpec('requirement-job'); vi.useRealTimers() })
describe('requirement task creation flow', () => {
  it('submits the inherited prompt and binds a staged document to the provisioning job', async () => {
    const wrapper = mount(NewTaskModal, { props:{ show:true, wsId:'ws', initialRequirement:leaf }, global:{ mocks:{ $t:(key:string) => key } } })
    await flushPromises()
    expect(wrapper.find('.primary-input').element).toHaveProperty('value', leaf.title)
    expect(wrapper.find('.file-name').text()).toBe('Payment checks.md')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/workspaces/ws/tasks', expect.objectContaining({ name:leaf.title, description:'Implement payment checks', requirement_id:'child' }))
    expect(wrapper.emitted('created')?.[0]?.[0]).toMatchObject({ expectSpecUpload:true, expectDiagnosisDocs:false })
    const store = useProvisioningStore()
    expect(store.consumePendingTaskSpec('requirement-job')).toMatchObject({ workspaceId:'ws', taskId:'created-task', file:{ name:'Payment checks.md' } })
    expect(store.consumePendingTaskDocs('requirement-job')).toBeNull()
    wrapper.unmount()
  })
  it('requires picking a child when task creation starts in a parent requirement view', async () => {
    const wrapper = mount(NewTaskModal, { props:{ show:true, wsId:'ws', initialRequirement:{ id:'parent', title:'Payments', status:'READY', child_count:1, can_link_task:false } }, global:{ mocks:{ $t:(key:string) => key } } })
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    expect(wrapper.find('.requirement-picker-sidebar.open').exists()).toBe(true)
    expect(api.get).toHaveBeenCalledWith('/workspaces/ws/workspace-assets/requirement-options', expect.objectContaining({ params:expect.objectContaining({ scope:'children', parent_id:'parent' }) }))
    await wrapper.find('form').trigger('submit')
    expect(api.post).not.toHaveBeenCalled()
    await wrapper.find('.requirement-picker-sidebar input').setValue('Payment')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    expect(api.get).toHaveBeenLastCalledWith('/workspaces/ws/workspace-assets/requirement-options', expect.objectContaining({ params:expect.objectContaining({ scope:'children', parent_id:'parent', q:'Payment' }) }))
    await wrapper.find('.requirement-node-button').trigger('click')
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/workspaces/ws/tasks', expect.objectContaining({ requirement_id:'child', description:'Implement payment checks' }))
    wrapper.unmount()
  })
})
