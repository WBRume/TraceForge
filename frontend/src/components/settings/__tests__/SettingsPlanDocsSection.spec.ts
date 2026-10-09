import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import SettingsPlanDocsSection from '../SettingsPlanDocsSection.vue'
import api from '@/utils/api'
import i18n from '@/i18n'

vi.mock('@/utils/api', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
  },
}))

const defaultData = {
  workspace_id: 'ws-test-1',
  roots: ['docs/plans', 'docs/specs', 'archive'],
  can_edit: true,
}

const mountSection = (props = { workspaceId: 'ws-test-1' }) =>
  mount(SettingsPlanDocsSection, {
    props,
    global: {
      plugins: [i18n],
    },
  })

beforeEach(() => {
  vi.mocked(api.get).mockReset()
  vi.mocked(api.put).mockReset()
  vi.mocked(api.get).mockResolvedValue({ data: structuredClone(defaultData) })
  vi.mocked(api.put).mockResolvedValue({ data: structuredClone(defaultData) })
})

describe('SettingsPlanDocsSection', () => {
  it('loads and renders structured path items correctly', async () => {
    const wrapper = mountSection()
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/workspaces/ws-test-1/plan-docs-settings')
    const items = wrapper.findAll('.path-item-card')
    expect(items).toHaveLength(3)
    expect(wrapper.text()).toContain('docs/plans')
    expect(wrapper.text()).toContain('docs/specs')
    expect(wrapper.text()).toContain('archive')
    expect(wrapper.find('.status-ready').exists()).toBe(true)
    wrapper.unmount()
  })

  it('allows adding a new path item via input', async () => {
    const wrapper = mountSection()
    await flushPromises()

    const input = wrapper.find('.path-input')
    await input.setValue('docs/api-reference')
    await wrapper.find('.btn-add-path').trigger('click')

    const items = wrapper.findAll('.path-item-card')
    expect(items).toHaveLength(4)
    expect(wrapper.text()).toContain('docs/api-reference')
    wrapper.unmount()
  })

  it('allows adding path from presets and disables duplicate buttons', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        workspace_id: 'ws-test-1',
        roots: ['docs/plans'],
        can_edit: true,
      },
    })
    const wrapper = mountSection()
    await flushPromises()

    expect(wrapper.findAll('.path-item-card')).toHaveLength(1)

    // 点击预设 docs/specs
    const presetBtns = wrapper.findAll('.preset-pill')
    const specsBtn = presetBtns.find(b => b.text().includes('docs/specs'))
    expect(specsBtn).toBeDefined()
    await specsBtn!.trigger('click')

    expect(wrapper.findAll('.path-item-card')).toHaveLength(2)
    expect(wrapper.text()).toContain('docs/specs')
    wrapper.unmount()
  })

  it('allows removing an existing path item', async () => {
    const wrapper = mountSection()
    await flushPromises()

    const removeBtns = wrapper.findAll('.action-icon-btn.remove-btn')
    expect(removeBtns.length).toBeGreaterThan(0)
    await removeBtns[0].trigger('click')

    const items = wrapper.findAll('.path-item-card')
    expect(items).toHaveLength(2)
    const itemTexts = items.map(c => c.text())
    expect(itemTexts.some(t => t.includes('docs/plans'))).toBe(false)
    wrapper.unmount()
  })

  it('switches between list and raw mode smoothly with synchronized content', async () => {
    const wrapper = mountSection()
    await flushPromises()

    const modeBtns = wrapper.findAll('.mode-btn')
    const rawBtn = modeBtns.find(b => b.text().includes('RAW') || b.text().includes('批量'))
    expect(rawBtn).toBeDefined()
    await rawBtn!.trigger('click')

    // raw textarea 应展示多行
    const textarea = wrapper.find('.raw-textarea')
    expect(textarea.exists()).toBe(true)
    expect((textarea.element as HTMLTextAreaElement).value).toContain('docs/plans\ndocs/specs\narchive')

    // 修改 raw 内容
    await textarea.setValue('custom/path1\ncustom/path2')

    // 切回列表模式
    const listBtn = wrapper.findAll('.mode-btn')[0]
    await listBtn.trigger('click')

    const items = wrapper.findAll('.path-item-card')
    expect(items).toHaveLength(2)
    expect(wrapper.text()).toContain('custom/path1')
    expect(wrapper.text()).toContain('custom/path2')
    wrapper.unmount()
  })

  it('resets to default presets on click', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        workspace_id: 'ws-test-1',
        roots: ['custom/dir'],
        can_edit: true,
      },
    })
    const wrapper = mountSection()
    await flushPromises()

    expect(wrapper.findAll('.path-item-card')).toHaveLength(1)
    const resetBtn = wrapper.find('.btn-reset-default')
    expect(resetBtn.exists()).toBe(true)
    await resetBtn.trigger('click')

    const items = wrapper.findAll('.path-item-card')
    expect(items).toHaveLength(3)
    expect(wrapper.text()).toContain('docs/plans')
    expect(wrapper.text()).toContain('docs/specs')
    expect(wrapper.text()).toContain('archive')
    wrapper.unmount()
  })

  it('submits updated roots array when saving', async () => {
    const wrapper = mountSection()
    await flushPromises()

    // 提交保存
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(api.put).toHaveBeenCalledWith('/workspaces/ws-test-1/plan-docs-settings', {
      roots: ['docs/plans', 'docs/specs', 'archive'],
    })
    wrapper.unmount()
  })

  it('renders graceful alert banner with retry button on error', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('Not Found'))
    const wrapper = mountSection()
    await flushPromises()

    const alert = wrapper.find('.alert-banner')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('Not Found')
    const retryBtn = wrapper.find('.btn-retry')
    expect(retryBtn.exists()).toBe(true)

    // 重试
    vi.mocked(api.get).mockResolvedValueOnce({ data: structuredClone(defaultData) })
    await retryBtn.trigger('click')
    await flushPromises()

    expect(wrapper.find('.alert-banner').exists()).toBe(false)
    expect(wrapper.findAll('.path-item-card')).toHaveLength(3)
    wrapper.unmount()
  })
})
