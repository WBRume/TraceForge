import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import CollaborationHistory from '@/components/collaboration/CollaborationHistory.vue'
import CodeComparison from '@/components/collaboration/CodeComparison.vue'

const api = vi.hoisted(() => ({ humanChanges: vi.fn(), humanChange: vi.fn(), object: vi.fn() }))
vi.mock('@/services/collaborationApi', () => ({ collaborationApi: () => api }))
vi.mock('@/components/collaboration/CodeComparison.vue', () => ({ default: { props: ['path', 'leftHash', 'rightHash', 'leftLabel', 'rightLabel', 'readText'], template: '<div>{{path}}</div>' } }))
const file = (repo: string) => ({ task_repository_id: repo, repo_slug: repo, branch_name: repo === 'api' ? 'release' : 'main', path: 'same.txt',
  before: { path: 'same.txt', sha256: `${repo}-before`, size: 4, mode: '100644' }, after: { path: 'same.txt', sha256: `${repo}-after`, size: 8, mode: '100644' } })
const detail = { id: 'record', base_snapshot_id: 'base', input_snapshot_id: 'input', created_at: '2026-10-12T17:48:49', files: [file('api'), file('web')] }
function open(handoffId?: string) {
  return mount(CollaborationHistory, { props: { workspaceId: 'w', taskId: 't', handoffId }, global: { plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })] } })
}
beforeEach(() => {
  vi.clearAllMocks()
  api.humanChanges.mockResolvedValue({ items: [{ id: 'record', created_at: detail.created_at, actor_name: 'Driver', changed_files_count: 2 }], total: 1, page_size: 20 })
  api.humanChange.mockResolvedValue(detail)
  api.object.mockResolvedValue(new TextEncoder().encode('test').buffer)
})
it('opens the latest immutable human change and distinguishes same paths in two repositories', async () => {
  const wrapper = open(); await flushPromises()
  const compare = () => wrapper.findComponent(CodeComparison)
  expect(compare().props()).toMatchObject({ path: 'api/same.txt', leftHash: 'api-before', rightHash: 'api-after' })
  await wrapper.findAll('nav button')[1]!.trigger('click')
  expect(compare().props()).toMatchObject({ path: 'web/same.txt', leftHash: 'web-before', rightHash: 'web-after' })
  expect(compare().props('leftLabel')).toContain('云端已确认版本')
  expect(await compare().props('readText')!('web-after')).toBe('test')
  expect(api.object).toHaveBeenCalledWith('web-after')
  wrapper.unmount()
})
it('opens a task-detail record directly and reports unavailable content instead of an empty diff', async () => {
  const wrapper = open('record'); await flushPromises()
  expect(api.humanChanges).not.toHaveBeenCalled()
  api.object.mockRejectedValue(new Error('object missing'))
  await expect(wrapper.findComponent(CodeComparison).props('readText')!('api-before')).rejects.toThrow('object missing')
  wrapper.unmount()
})
it('discards a late response when a different historical record is opened', async () => {
  let resolve!: (value: unknown) => void
  api.humanChange.mockReturnValueOnce(new Promise(done => { resolve = done }))
  const wrapper = open('old'); await flushPromises()
  await wrapper.setProps({ handoffId: 'new' }); await flushPromises()
  resolve({ ...detail, files: [file('stale')] }); await flushPromises()
  expect(wrapper.findComponent(CodeComparison).props('path')).toBe('api/same.txt')
  wrapper.unmount()
})
