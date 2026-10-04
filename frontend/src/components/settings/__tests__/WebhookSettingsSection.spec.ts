import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import WebhookSettingsSection from '../WebhookSettingsSection.vue'
import api from '@/utils/api'
import i18n from '@/i18n'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }))
const config = { enabled: false, url: '', delivery_location: 'server', events: ['AI_HITL_SUSPENDED', 'AI_RUN_FINISHED', 'AI_RUN_ERROR'] }
const mountSection = (props: any) => mount(WebhookSettingsSection, { props, global: { plugins: [i18n] } })

beforeEach(() => {
  vi.mocked(api.get).mockResolvedValue({ data: structuredClone(config) }); vi.mocked(api.put).mockResolvedValue({ data: config })
})
afterEach(() => { delete window.sddDesktop })

describe('webhook settings', () => {
  it('separates runtime and business subscriptions and saves the selected scope', async () => {
    const wrapper = mountSection({ scope: 'workspace', workspaceId: 'w1' })
    await flushPromises()
    const groups = wrapper.findAll('fieldset')
    expect(groups[0].findAll('input').map(input => (input.element as HTMLInputElement).checked)).toEqual([true, true, true, false])
    expect(groups[0].text()).toContain('AI 本轮执行被发起人主动中断')
    expect(groups[0].text()).toContain('AI 执行异常或被他人中断')
    expect(groups[0].text()).toContain('异常及他人中断立即提醒发起人')
    expect(groups[1].findAll('input').map(input => (input.element as HTMLInputElement).checked)).toEqual([false, false, false])
    expect(groups[1].text()).toContain('任务被人工初始化')
    expect(groups[1].text()).toContain('任务被人工手动标记失败')
    expect(wrapper.find('.switch-toggle input').exists()).toBe(true)
    expect(wrapper.text()).toContain('启用事件广播')
    expect(wrapper.text()).not.toContain('消息格式')
    await wrapper.find('input[type=url]').setValue('http://127.0.0.1:9000/hook')
    for (const input of groups[1].findAll('input')) await input.setValue(true)
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(api.put).toHaveBeenCalledWith('/workspaces/w1/task-webhook', { ...config, url: 'http://127.0.0.1:9000/hook', events: [...config.events, 'TASK_INITIALIZED', 'TASK_COMPLETED', 'TASK_FAILED'] })
    expect(wrapper.text()).toContain('Webhook 配置已保存'); wrapper.unmount()
  })
  it('subscribes to interruption as a runtime event without a task cancellation state', async () => {
    const wrapper = mountSection({ scope: 'personal' })
    await flushPromises()
    await wrapper.find('input[type=url]').setValue('http://127.0.0.1:9000/hook')
    await wrapper.findAll('fieldset')[0].findAll('input')[3].setValue(true)
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(api.put).toHaveBeenCalledWith('/users/me/task-webhook', expect.objectContaining({ events: [...config.events, 'AI_RUN_INTERRUPTED'] }))
    wrapper.unmount()
  })
  it('sends a desktop test through the native bridge without requiring focus', async () => {
    const send = vi.fn().mockResolvedValue({ ok: true }); window.sddDesktop = { webhooks: { send } } as any
    vi.mocked(api.get).mockResolvedValue({ data: { ...config, url: 'http://127.0.0.1:9000/pet', delivery_location: 'desktop' } })
    const request = { url: 'http://127.0.0.1:9000/pet', body: { event_type: 'WEBHOOK_TEST' }, event_id: 'test-1' }
    vi.mocked(api.post).mockResolvedValue({ data: { request } })
    const wrapper = mountSection({ scope: 'personal' }); await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('发送测试消息'))!.trigger('click'); await flushPromises()
    expect(send).toHaveBeenCalledWith(request); expect(wrapper.text()).toContain('测试消息已送达'); wrapper.unmount()
  })
  it('switches delivery location using scene cards in personal settings', async () => {
    window.sddDesktop = { webhooks: { send: vi.fn() } } as any
    const wrapper = mountSection({ scope: 'personal' })
    await flushPromises()
    expect(wrapper.text()).toContain('仅自己生效')
    expect(wrapper.text()).toContain('用于触发本地脚本或桌宠')
    expect(wrapper.text()).toContain('公网 Webhook / 消息通道')
    expect(wrapper.text()).toContain('本地回环代理 / 脚本联动')
    expect(wrapper.text()).not.toContain('站外广播不受页面或窗口焦点影响')
    expect(wrapper.text()).not.toContain('通信软件或本地外设')
    const cards = wrapper.findAll('.scene-card')
    expect(cards[0].classes()).toContain('active')
    await cards[1].trigger('click')
    expect(cards[1].classes()).toContain('active')
    await wrapper.find('input[type=url]').setValue('http://127.0.0.1:8080/hook')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(api.put).toHaveBeenCalledWith('/users/me/task-webhook', expect.objectContaining({ delivery_location: 'desktop', url: 'http://127.0.0.1:8080/hook' }))
    wrapper.unmount()
  })
  it('renders workspace banner and does not render payload preview or scene cards in workspace settings', async () => {
    const wrapper = mountSection({ scope: 'workspace', workspaceId: 'w2' })
    await flushPromises()
    expect(wrapper.text()).toContain('团队全员广播')
    expect(wrapper.text()).toContain('工作区级服务端统一投递')
    expect(wrapper.text()).toContain('覆盖当前工作区内所有成员触发的 AI 任务生命周期与人工操作事件')
    expect(wrapper.text()).not.toContain('推送数据结构示例')
    expect(wrapper.findAll('.scene-card').length).toBe(0)
    wrapper.unmount()
  })
  it('supports batch select and clear for event subscription groups', async () => {
    const wrapper = mountSection({ scope: 'personal' })
    await flushPromises()
    const batchButtons = wrapper.findAll('.btn-batch-select')
    expect(batchButtons.length).toBe(2)
    await batchButtons[1].trigger('click')
    const group2Inputs = wrapper.findAll('fieldset')[1].findAll('.custom-checkbox')
    expect(group2Inputs.every(input => (input.element as HTMLInputElement).checked)).toBe(true)
    await batchButtons[1].trigger('click')
    expect(group2Inputs.every(input => !(input.element as HTMLInputElement).checked)).toBe(true)
    wrapper.unmount()
  })
})
