import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import SessionContextPanel from '../SessionContextPanel.vue'
import ChatMessageBubble from '@/components/chat/ChatMessageBubble.vue'
import api from '@/utils/api'
import i18n from '@/i18n'
import { formatMessageTime } from '@/composables/chat/message/presenters'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn() } }))
vi.mock('@/stores/taskAwareness', () => ({ useTaskAwarenessStore: () => ({ outputs: {} }) }))

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

const mountPanel = async (messages: Record<string, unknown>[]) => {
  vi.mocked(api.get).mockResolvedValue({ data: { messages } })
  const wrapper = mount(SessionContextPanel, {
    props: { workspaceId: 'ws-1', taskId: 'task-1', taskName: '多人协作' },
    global: { plugins: [i18n] },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

describe('pinned session message presentation', () => {
  it('preserves sender identities and uses the main conversation metadata order without actions', async () => {
    const expert = {
      id: 'expert', role: 'user', content: '专家建议', creator_id: 'expert-1',
      creator_display_name: '张三', creator_is_workspace_expert: true,
      creator_avatar_svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><circle cx="10" cy="10" r="8"/></svg>',
      created_at: '2026-10-04T10:30:00+08:00',
    }
    const panel = await mountPanel([
      { id: 'member', role: 'user', content: '我的问题', creator_id: 'member-1', creator_display_name: '李四' },
      expert,
      { ...expert, id: 'ai', role: 'assistant', content: 'AI 回复' },
      { id: 'unknown', role: 'user', content: '旧消息' },
      { id: 'system', role: 'system', content: '系统记录' },
    ])
    expect(panel.findAll('.message-author').map(node => node.text())).toEqual(['李四', '张三', 'AI 助手', '未知用户', '系统'])
    expect(panel.findAll('.message-expert-badge')).toHaveLength(1)
    expect(panel.findAll('.avatar-svg svg')).toHaveLength(1)
    expect(panel.find('button').exists()).toBe(false)

    const main = mount(ChatMessageBubble, {
      props: {
        msg: expert,
        vm: {
          messageAuthorLabel: () => '张三', formatMessageTime,
          isMessageWorkspaceExpert: () => true, isMessageFromCurrentUser: () => false,
          canMarkMessageAsDecision: () => false,
        },
      },
      global: { plugins: [i18n] },
    })
    wrappers.push(main)
    const floated = panel.find('[data-message-id="expert"]')
    expect(floated.find('.message-meta').text()).toBe(main.find('.message-meta').text())
    expect(floated.find('.message-bubble').text()).toBe(main.find('.message-bubble').text())
    const order = Array.from(floated.find('.message-meta').element.children).map(node => node.classList[0])
    expect(order).toEqual(['message-time', 'message-author', 'message-expert-badge', 'user-avatar'])
    expect(main.find('.message-copy-btn').exists()).toBe(true)
  })

  it('retains collaboration authors and modifier attribution from history', async () => {
    const panel = await mountPanel([{
      id: 'collab', role: 'user', content: '共同整理的问题', creator_id: 'member-1', creator_display_name: '李四',
      metadata: {
        pre_input_id: 'pre-1', participants: [{ user_id: 'member-1' }, { user_id: 'member-2' }],
        segments: [{ created_by: 'member-1', created_by_name: '李四', updated_by: 'member-2', updated_by_name: '张三', modified: true, text: '补充后的问题' }],
      },
    }])
    expect(panel.find('.collab-count').text()).toBe('2')
    expect(panel.find('.message-bubble').text()).toBe('补充后的问题')
    expect(panel.find('[title="李四（张三 修改）"]').exists()).toBe(true)
    expect(panel.find('button').exists()).toBe(false)
  })
})
