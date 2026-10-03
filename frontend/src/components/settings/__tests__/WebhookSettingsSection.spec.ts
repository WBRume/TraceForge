import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import WebhookSettingsSection from '../WebhookSettingsSection.vue'
import api from '@/utils/api'
vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }))
const config = { enabled: false, url: '', delivery_location: 'server', events: ['AI_HITL_SUSPENDED', 'AI_RUN_FINISHED', 'AI_RUN_ERROR'] }
beforeEach(() => {
  vi.mocked(api.get).mockResolvedValue({ data: structuredClone(config) }); vi.mocked(api.put).mockResolvedValue({ data: config })
})
afterEach(() => { delete window.sddDesktop })
describe('webhook settings', () => {
  it('separates runtime and business subscriptions and saves the selected scope', async () => {
    const wrapper = mount(WebhookSettingsSection, { props: { scope: 'workspace', workspaceId: 'w1' } })
    await flushPromises()
    const groups = wrapper.findAll('fieldset')
    expect(groups[0].findAll('input').map(input => (input.element as HTMLInputElement).checked)).toEqual([true, true, true, false])
    expect(groups[0].text()).toContain('AI 本轮执行被人工中断')
    expect(groups[1].findAll('input').map(input => (input.element as HTMLInputElement).checked)).toEqual([false, false, false])
    expect(groups[1].text()).toContain('任务被人工初始化')
    expect(groups[1].text()).toContain('任务被人工手动标记失败')
    expect(groups[1].text()).not.toContain('取消')
    expect(wrapper.text()).toContain('标准 JSON Webhook')
    expect(wrapper.text()).not.toContain('消息格式')
    await wrapper.find('input[type=url]').setValue('http://127.0.0.1:9000/hook')
    for (const input of groups[1].findAll('input')) await input.setValue(true)
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(api.put).toHaveBeenCalledWith('/workspaces/w1/task-webhook', { ...config, url: 'http://127.0.0.1:9000/hook', events: [...config.events, 'TASK_INITIALIZED', 'TASK_COMPLETED', 'TASK_FAILED'] })
    expect(wrapper.text()).toContain('Webhook 配置已保存'); wrapper.unmount()
  })
  it('subscribes to interruption as a runtime event without a task cancellation state', async () => {
    const wrapper = mount(WebhookSettingsSection, { props: { scope: 'personal' } })
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
    const wrapper = mount(WebhookSettingsSection, { props: { scope: 'personal' } }); await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('发送测试消息'))!.trigger('click'); await flushPromises()
    expect(send).toHaveBeenCalledWith(request); expect(wrapper.text()).toContain('测试消息已送达'); wrapper.unmount()
  })
})
