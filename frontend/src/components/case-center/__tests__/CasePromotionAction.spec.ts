import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import CasePromotionAction from '../CasePromotionAction.vue'
import api from '@/utils/api'
import { createPinia, setActivePinia } from 'pinia'
import { useProvisioningStore } from '@/stores/provisioning'
vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/router', () => ({ default: { push: vi.fn() } }))
const job = { job_id: 'job', workspace_id: 'ws', status: 'PENDING', progress: 0 }
beforeEach(() => { localStorage.clear(); setActivePinia(createPinia()); vi.resetAllMocks(); vi.mocked(api.get).mockResolvedValue({ data: { items: [] } }) })
const mountAction = () => mount(CasePromotionAction, { props: { workspaceId: 'ws', caseIds: ['a', 'b'] }, global: { stubs: { ConfirmActionModal: true } } })
it('submits independent background jobs and leaves the promotion action available', async () => {
  vi.mocked(api.post).mockResolvedValueOnce({ data: job }).mockResolvedValueOnce({ data: { ...job, job_id: 'second' } })
  const wrapper = mountAction()
  await flushPromises()
  for (let i = 0; i < 2; i++) {
    await wrapper.get('button').trigger('click')
    const confirm = wrapper.findComponent({ name: 'ConfirmActionModal' })
    expect(confirm.attributes('show')).toBe('true')
    confirm.vm.$emit('confirm')
    await flushPromises()
  }
  const calls = vi.mocked(api.post).mock.calls
  expect(calls).toHaveLength(2)
  expect((calls[0][1] as { idempotency_key: string }).idempotency_key).not.toBe((calls[1][1] as { idempotency_key: string }).idempotency_key)
  expect(useProvisioningStore().jobList).toHaveLength(2)
  expect(wrapper.text()).toContain('2 个晋升任务执行中')
  expect(wrapper.get('button').text()).toContain('晋升诊断规程')
  expect(wrapper.findComponent({ name: 'RequirementImportDialog' }).exists()).toBe(false)
  expect(wrapper.text()).not.toContain('查看晋升进度')
  wrapper.unmount()
})
it('restores all background jobs without binding the action to one job', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { items: [job, { ...job, job_id: 'orphan', status: 'ORPHANED' }] } })
  const wrapper = mountAction(); await flushPromises()
  expect(wrapper.text()).toContain('2 个晋升任务执行中')
  expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
  await wrapper.get('button').trigger('click')
  expect(wrapper.findComponent({ name: 'ConfirmActionModal' }).attributes('show')).toBe('true')
  expect(api.post).not.toHaveBeenCalled()
  wrapper.unmount()
})
it('retries uncertain submission with the same idempotency key and selected snapshot', async () => {
  vi.mocked(api.post).mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ data: job })
  const wrapper = mountAction(); await flushPromises()
  await wrapper.get('button').trigger('click')
  const confirm = wrapper.findComponent({ name: 'ConfirmActionModal' })
  confirm.vm.$emit('confirm'); await flushPromises()
  await wrapper.setProps({ caseIds: ['other'] })
  confirm.vm.$emit('confirm'); await flushPromises()
  const calls = vi.mocked(api.post).mock.calls
  expect(calls[1][1]).toEqual(calls[0][1])
  expect((calls[1][1] as { case_ids: string[] }).case_ids).toEqual(['a', 'b'])
  wrapper.unmount()
})
