import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { featureConfigApi, type FeatureConfig, type Capability } from '@/services/featureConfigApi'
import zh from '@/locales/zh.json'

vi.mock('@/services/featureConfigApi', () => ({
  featureConfigApi: { configs: vi.fn(), capabilities: vi.fn(), test: vi.fn(), save: vi.fn() },
}))
vi.mock('element-plus', () => ({ ElMessage: { success: vi.fn(), warning: vi.fn() } }))
const i18n = createI18n({ legacy: false, locale: 'zh', messages: { zh } })
const configuration: FeatureConfig = { feature: 'speech', title: '语音输入', revision: 4, configured: true, fields: [
  { key: 'api_key', label: '百炼 API Key', kind: 'secret', value: 'sk-0********abcd', has_value: true,
    source: 'database', options: [], minimum: 0, maximum: 4096, hint: '' },
] }
const search: FeatureConfig = { feature: 'search', title: '全局搜索', revision: 0, configured: false, fields: [] }
const status: Capability = { feature: 'speech', title: '语音输入', status: 'READY', mode: 'api',
  explanation: '识别服务已就绪', guidance: '', facts: {}, checked_at: '' }
let wrapper: VueWrapper | undefined
let ServiceCapabilityMatrix: typeof import('../ServiceCapabilityMatrix.vue')['default']
const render = () => {
  wrapper = mount(ServiceCapabilityMatrix, {
    slots: { mgmt: '<p>项目管理设置</p>', root: '<p>工作区根目录设置</p>' },
    global: { plugins: [i18n], stubs: {
      SearchIndexManagement: { template: '<section aria-label="向量索引管理">向量索引管理</section>' },
      'el-tooltip': true,
    } },
  })
  return wrapper
}
beforeEach(async () => {
  vi.resetAllMocks()
  vi.resetModules()
  ServiceCapabilityMatrix = (await import('../ServiceCapabilityMatrix.vue')).default
  vi.mocked(featureConfigApi.configs).mockResolvedValue({ data: { items: [configuration, search] } } as never)
  vi.mocked(featureConfigApi.capabilities).mockResolvedValue({ data: { items: [status] } } as never)
  vi.mocked(featureConfigApi.test).mockResolvedValue({ data: status } as never)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.useRealTimers() })

const button = (view: VueWrapper, text: string) => view.findAll('button').find(item => item.isVisible() && item.text() === text)!
const tab = (view: VueWrapper, text: string) => view.findAll('[role="tab"]').find(item => item.text().includes(text))!

describe('inline system configuration', () => {
  it('keeps the inline password form usable when probes fail, without posting masks', async () => {
    vi.mocked(featureConfigApi.capabilities).mockRejectedValue(new Error('probe unavailable'))
    const view = render()
    await flushPromises()
    expect(tab(view, '语音输入').text()).toContain('降级运行')
    const input = view.get('input[type="password"]')
    expect(input.isVisible()).toBe(true)
    expect((input.element as HTMLInputElement).value).toBe('')
    expect(input.attributes('placeholder')).toBe('sk-0********abcd')
    expect(view.findAll('button').some(item => item.text() === '显示' || item.text() === '恢复环境凭据')).toBe(false)
    expect(view.find('[role="dialog"]').exists()).toBe(false)
    await button(view, '测试连接 / 探测').trigger('click')
    await flushPromises()
    expect(featureConfigApi.test).toHaveBeenCalledWith('speech', { revision: 4, values: {} })
  })

  it('aligns capabilities, indexes and basic settings in the same page navigation and keeps drafts', async () => {
    const view = render()
    await flushPromises()
    expect(view.findAll('[role="tablist"]')).toHaveLength(1)
    expect(view.findAll('[role="tab"]')).toHaveLength(7)
    await view.get('input[type="password"]').setValue('draft-secret')
    await tab(view, '全局搜索').trigger('click')
    expect(view.get('[aria-label="向量索引管理"]').isVisible()).toBe(true)
    await tab(view, '工作区根目录').trigger('click')
    expect(view.get('#config-panel-root').isVisible()).toBe(true)
    expect(view.get('#config-panel-root').text()).toContain('工作区根目录设置')
    await tab(view, '语音输入').trigger('click')
    expect((view.get('input[type="password"]').element as HTMLInputElement).value).toBe('draft-secret')
  })

  it('updates health on periodic and manual refresh without replacing credential drafts', async () => {
    vi.useFakeTimers()
    const view = render()
    await flushPromises()
    await view.get('input[type="password"]').setValue('draft-secret')
    await vi.advanceTimersByTimeAsync(30000)
    expect(featureConfigApi.configs).toHaveBeenCalledOnce()
    expect(featureConfigApi.capabilities).toHaveBeenCalledTimes(2)
    vi.mocked(featureConfigApi.capabilities).mockRejectedValue(new Error('probe unavailable'))
    await button(view, '刷新探测').trigger('click')
    await flushPromises()
    expect(tab(view, '语音输入').text()).toContain('降级运行')
    expect((view.get('input[type="password"]').element as HTMLInputElement).value).toBe('draft-secret')
  })

  it('uses direct clear and undo actions without submitting the stored preview', async () => {
    const view = render()
    await flushPromises()
    await button(view, '清除凭据').trigger('click')
    expect(view.get('#config-panel-speech').text()).toContain('保存后清除凭据')
    await button(view, '测试连接 / 探测').trigger('click')
    await flushPromises()
    expect(featureConfigApi.test).toHaveBeenLastCalledWith('speech', { revision: 4, values: { api_key: '' } })
    await button(view, '撤销').trigger('click')
    await button(view, '测试连接 / 探测').trigger('click')
    await flushPromises()
    expect(featureConfigApi.test).toHaveBeenLastCalledWith('speech', { revision: 4, values: {} })
  })

  it('saves entered credentials, clears the input and keeps the current section open', async () => {
    const view = render()
    await flushPromises()
    vi.mocked(featureConfigApi.save).mockResolvedValue({
      data: { config: { ...configuration, revision: 5 }, applied: true, message: '' },
    } as never)
    const input = view.get('input[type="password"]')
    await input.setValue('replacement-secret')
    await view.get('#config-panel-speech form').trigger('submit')
    await flushPromises()
    expect(featureConfigApi.save).toHaveBeenCalledWith('speech', { revision: 4, values: { api_key: 'replacement-secret' } })
    expect((input.element as HTMLInputElement).value).toBe('')
    expect(view.get('#config-tab-speech').attributes('aria-selected')).toBe('true')
    expect(featureConfigApi.capabilities).toHaveBeenCalledTimes(2)
    await button(view, '测试连接 / 探测').trigger('click')
    await flushPromises()
    expect(featureConfigApi.test).toHaveBeenLastCalledWith('speech', { revision: 5, values: {} })
  })

  it('supports keyboard navigation to the same inline sections', async () => {
    const view = render()
    await flushPromises()
    await tab(view, '语音输入').trigger('keydown', { key: 'ArrowRight' })
    expect(view.get('#config-tab-search').attributes('aria-selected')).toBe('true')
    await view.get('#config-tab-search').trigger('keydown', { key: 'End' })
    expect(view.get('#config-panel-root').isVisible()).toBe(true)
  })
})
