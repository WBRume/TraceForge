import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import CasePromotionAction from '../CasePromotionAction.vue'
import api from '@/utils/api'
import { createPinia, setActivePinia } from 'pinia'
import { useProvisioningStore } from '@/stores/provisioning'
vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
const job = { job_id: 'job', workspace_id: 'ws', status: 'PENDING', progress: 0 }
beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks(); vi.mocked(api.get).mockResolvedValue({ data: { items: [] } }) })
const mountAction = () => mount(CasePromotionAction, { props: { workspaceId: 'ws', caseIds: ['a', 'b'] }, global: { stubs: { ConfirmActionModal: true, RequirementImportDialog: true } } })
it('confirms multiple cases, uses shared progress, and refreshes on WS completion', async () => {
  vi.mocked(api.post).mockResolvedValue({ data: job })
  const wrapper = mountAction()
  await flushPromises()
  await wrapper.get('button').trigger('click')
  const confirm = wrapper.findComponent({ name: 'ConfirmActionModal' })
  expect(confirm.attributes('show')).toBe('true')
  expect(api.post).not.toHaveBeenCalled()
  confirm.vm.$emit('confirm')
  await flushPromises()
  expect(api.post).toHaveBeenCalledWith('/workspaces/ws/cases/playbook-promotions', expect.objectContaining({ case_ids: ['a', 'b'], idempotency_key: expect.any(String) }))
  expect(wrapper.findComponent({ name: 'RequirementImportDialog' }).attributes('mode')).toBe('promotion')
  wrapper.findComponent({ name: 'RequirementImportDialog' }).vm.$emit('minimize')
  await flushPromises()
  expect(useProvisioningStore().getTrackedJob('job')?.handedOver).toBe(true)
  expect(useProvisioningStore().expanded).toBe(true)
  vi.mocked(api.get).mockResolvedValue({ data: { items: [{ ...job, status: 'SUCCESS', progress: 100, result: { review_state: 'CONFIRMED', spec_ids: ['spec'] } }] } })
  window.dispatchEvent(new CustomEvent('playbook-promotion-updated', { detail: { workspace_id: 'ws' } }))
  await flushPromises()
  expect(wrapper.emitted('completed')).toHaveLength(1)
  expect(wrapper.text()).not.toContain('查看晋升结果')
  wrapper.unmount()
})
it('restores active work without submitting again and cancels through the job lifecycle', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { items: [{ ...job, status: 'RUNNING' }] } })
  vi.mocked(api.post).mockResolvedValue({ data: { ...job, status: 'TERMINATING', cancel_requested: true } })
  const wrapper = mountAction()
  await flushPromises()
  expect(wrapper.text()).toContain('查看晋升进度')
  await wrapper.get('button').trigger('click')
  wrapper.findComponent({ name: 'RequirementImportDialog' }).vm.$emit('close')
  await flushPromises()
  expect(api.post).toHaveBeenCalledWith('/workspaces/ws/cases/playbook-promotions/job/cancel')
  wrapper.unmount()
})
