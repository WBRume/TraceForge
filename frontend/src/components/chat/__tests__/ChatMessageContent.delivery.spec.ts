import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import ChatMessageContent from '../ChatMessageContent.vue'
import zh from '@/locales/zh.json'

describe('message preparation failure', () => {
  it('stays silent during preparation and shows the durable failure on that message', async () => {
    const msg = { id: 'pending', role: 'user', content: '检查代码', delivery_status: 'preparing' }
    const wrapper = mount(ChatMessageContent, {
      props: { msg, authorLabel: 'User', timeLabel: '18:00' },
      global: { plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })] },
    })
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('button').exists()).toBe(false)
    await wrapper.setProps({ msg: { ...msg, delivery_status: 'failed', delivery_error: '快照准备失败，本次消息未执行' } })
    expect(wrapper.get('[role="alert"]').text()).toBe('快照准备失败，本次消息未执行')
    expect(wrapper.get('.msg-content').text()).toBe('检查代码')
    await wrapper.setProps({ msg: { ...msg, delivery_status: 'sent' } })
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
