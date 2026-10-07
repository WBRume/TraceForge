import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import SearchIndexManagement from '../SearchIndexManagement.vue'
import api from '@/utils/api'
import zh from '@/locales/zh.json'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('element-plus', () => ({ ElMessage: { success: vi.fn(), error: vi.fn() } }))
const i18n = createI18n({ legacy: false, locale: 'zh', messages: { zh } })
const response = () => ({ data: {
  profiles: [{ id: 'profile-id', revision: 2, model_id: 'BAAI/bge-m3', dimension: 1024, status: 'tested' }],
  targets: [{ target_id: 'target-id', status: 'building', verified: false }],
} })
let wrapper: VueWrapper | undefined
const render = () => {
  wrapper = mount(SearchIndexManagement, { props: { revision: 1 }, global: { plugins: [i18n] } })
  return wrapper
}
const button = (view: VueWrapper, name: string) => view.findAll('button').find(item => item.text() === name)!
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.get).mockResolvedValue(response())
  vi.mocked(api.post).mockResolvedValue({ data: {} })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('search index operations', () => {
  it('retains model testing, build, verification and guarded activation in the search section', async () => {
    const view = render()
    await flushPromises()
    expect(view.text()).toContain('BAAI/bge-m3')
    expect(button(view, zh.system_config.embedding_activate).attributes('disabled')).toBeDefined()
    await button(view, zh.system_config.embedding_test).trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenLastCalledWith('/admin/search/embedding/profile-id/test')
    await button(view, zh.system_config.embedding_build).trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenLastCalledWith('/admin/search/embedding/profile-id/build')
    const verified = response()
    verified.data.targets[0]!.verified = true
    vi.mocked(api.get).mockResolvedValue(verified)
    await button(view, zh.system_config.embedding_verify).trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenLastCalledWith('/admin/search/targets/target-id/verify')
    await button(view, zh.system_config.embedding_activate).trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenLastCalledWith('/admin/search/targets/target-id/activate')
    expect(view.emitted('changed')).toHaveLength(4)
  })

  it('reloads index state after saving new search parameters and when no model exists', async () => {
    const view = render()
    await flushPromises()
    vi.mocked(api.get).mockResolvedValue({ data: { profiles: [], targets: [] } })
    await view.setProps({ revision: 2 })
    await flushPromises()
    expect(api.get).toHaveBeenCalledTimes(2)
    expect(view.text()).toContain('尚无向量模型配置')
    expect(button(view, zh.system_config.embedding_test).attributes('disabled')).toBeDefined()
    expect(button(view, zh.system_config.embedding_build).attributes('disabled')).toBeDefined()
  })
})
