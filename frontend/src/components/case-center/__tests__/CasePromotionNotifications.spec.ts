import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { defineComponent, reactive } from 'vue'
import App from '@/App.vue'
import CasePromotionAction from '../CasePromotionAction.vue'
import api from '@/utils/api'
import { clearWsCursorMemory } from '@/utils/wsCursor'

const mocks = vi.hoisted(() => ({ auth: null as any }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocks.auth }))
vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/utils/ws', () => ({ buildBackendWsUrl: () => 'ws://localhost/notifications' }))
vi.mock('@/components/global-search/GlobalSearchHost.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/ProvisionFloatingWidget.vue', () => ({ default: { template: '<div />' } }))

class Socket {
  static OPEN = 1
  static connections: Socket[] = []
  readyState = 1
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onerror = null
  close = vi.fn()
  send = vi.fn()
  constructor() { Socket.connections.push(this) }
  update(sequence: number) {
    this.onmessage?.({ data: JSON.stringify({ type: 'event', epoch: 'epoch', sequence,
      event_id: `event-${sequence}`, event_type: 'notification',
      payload: { type: 'playbook_promotion_updated', workspace_id: 'ws', job_id: 'job' } }) })
  }
}
const route = defineComponent({ components: { CasePromotionAction }, template: '<CasePromotionAction workspace-id="ws" :case-ids="[]" />' })
beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear(); clearWsCursorMemory(); Socket.connections = []
  vi.stubGlobal('WebSocket', Socket)
  mocks.auth = reactive({ token: 'token', user: { id: 'user' }, isAuthenticated: true, fetchCurrentUser: vi.fn() })
})
afterEach(() => vi.unstubAllGlobals())

it('receives running and completion frames on a route without a notification bell', async () => {
  let state: any = { job_id: 'job', workspace_id: 'ws', status: 'PENDING', progress: 0 }
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes('playbook-promotions')
    ? { items: [state] } : String(url).includes('unread-count') ? { count: 0 } : { items: [] } }))
  const wrapper = mount(App, { global: { plugins: [createPinia()], stubs: {
    RouterView: route, ConfirmActionModal: true, RequirementImportDialog: true,
  } } })
  await flushPromises()
  expect(Socket.connections).toHaveLength(1)
  const socket = Socket.connections[0]!
  socket.onopen?.()
  await flushPromises()
  const action = wrapper.findComponent(CasePromotionAction)
  await action.get('button').trigger('click')
  const dialog = action.findComponent({ name: 'RequirementImportDialog' })
  expect(dialog.props('previewJob').status).toBe('PENDING')
  state = { ...state, status: 'RUNNING', progress: 15 }
  socket.update(1)
  await flushPromises()
  expect(dialog.props('previewJob').progress).toBe(15)
  state = { ...state, status: 'SUCCESS', progress: 100, result: { review_state: 'CONFIRMED', spec_ids: ['spec'] } }
  socket.update(2)
  await flushPromises()
  expect(dialog.props('previewJob').status).toBe('SUCCESS')
  expect(dialog.props('previewJob').progress).toBe(100)
  expect(action.emitted('completed')).toHaveLength(1)
  expect(action.text()).not.toContain('查看晋升结果')
  mocks.auth.token = null; mocks.auth.user = null; mocks.auth.isAuthenticated = false
  await flushPromises()
  expect(socket.close).toHaveBeenCalledOnce()
  wrapper.unmount()
})

it('restores completed results when opening the page after the CLI has finished', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { items: [{ job_id: 'job', status: 'SUCCESS', progress: 100 }] } })
  const wrapper = mount(CasePromotionAction, { props: { workspaceId: 'ws', caseIds: [], requestedJobId: 'job' },
    global: { plugins: [createPinia()], stubs: { ConfirmActionModal: true, RequirementImportDialog: true } } })
  await flushPromises()
  expect(wrapper.findComponent({ name: 'RequirementImportDialog' }).props('previewJob').status).toBe('SUCCESS')
  expect(api.post).not.toHaveBeenCalled()
  wrapper.unmount()
})
