import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import ChatMessageContent from '../ChatMessageContent.vue'
import api from '@/utils/api'
import zh from '@/locales/zh.json'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn() } }))

const imageMessage = () => ({
  id: 'screenshot-message',
  role: 'user',
  content: '',
  metadata: { chat_images: [{ id: 'attachment', filename: 'screen.png', media_type: 'image/png' }] },
})

describe('shared chat image attachments', () => {
  afterEach(() => {
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

  it('shows an image-only message and keeps the loaded image through a history refresh', async () => {
    const createObjectURL = vi.fn(() => 'blob:chat-image')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = createObjectURL
      static revokeObjectURL = revokeObjectURL
    })
    vi.mocked(api.get).mockResolvedValue({ data: new Blob(['image'], { type: 'image/png' }) })
    const wrapper = mount(ChatMessageContent, {
      props: { msg: imageMessage(), authorLabel: 'User', timeLabel: '18:00', imageScope: { workspaceId: 'w1', taskId: 't1' } },
      global: { plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })] },
    })
    await flushPromises()
    expect(wrapper.get('img[alt="screen.png"]').attributes('src')).toBe('blob:chat-image')
    expect(api.get).toHaveBeenCalledWith('/workspaces/w1/tasks/t1/chat-images/attachment', expect.objectContaining({ responseType: 'blob' }))

    await wrapper.setProps({ msg: imageMessage() })
    await flushPromises()
    expect(api.get).toHaveBeenCalledTimes(1)
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(wrapper.get('img[alt="screen.png"]').attributes('src')).toBe('blob:chat-image')

    wrapper.unmount()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:chat-image')
  })

  it('renders attached images above the message text', async () => {
    const wrapper = mount(ChatMessageContent, {
      props: {
        msg: { ...imageMessage(), content: 'diagnostic notes' },
        authorLabel: 'User',
        timeLabel: '18:00',
        imageScope: { workspaceId: 'w1', taskId: 't1' },
      },
      global: { plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })] },
    })
    await flushPromises()
    const [first, second] = Array.from(wrapper.get('.message-bubble').element.children)
    expect(first.classList.contains('message-images')).toBe(true)
    expect(second.classList.contains('message-markdown')).toBe(true)
    wrapper.unmount()
  })
})
