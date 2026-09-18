import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import SharedTaskSessionView from '@/views/SharedTaskSessionView.vue'
import {
  ShareApiError,
  clearShareSession,
  setShareToken,
} from '@/services/shareApi'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/share/session', component: SharedTaskSessionView },
    { path: '/login', component: { template: '<div class="login-page" />' } },
    { path: '/workspaces/:wsId/chat/:taskId', component: { template: '<div />' } },
  ],
})

vi.mock('@/services/shareApi', async () => {
  const actual = await vi.importActual<typeof import('@/services/shareApi')>('@/services/shareApi')
  return {
    ...actual,
    shareExchange: vi.fn(),
    shareResolve: vi.fn(),
    fetchSharedHistory: vi.fn(),
    submitShareSuggestion: vi.fn(),
  }
})

import {
  shareExchange,
  fetchSharedHistory,
  submitShareSuggestion,
} from '@/services/shareApi'

const mountView = async (
  url = '/share/session',
  token: string | null = null,
  options: { authToken?: string | null } = {},
) => {
  setActivePinia(createPinia())
  if (options.authToken) {
    // 已登录访客场景：exchange 携带登录态
    const { useAuthStore } = await import('@/stores/auth')
    useAuthStore().token = options.authToken
  }
  if (token) {
    // 内存路由不产生真实 hash；用 sessionStorage 预置（生产中首次进入
    // 由 fragment 读取后写入，页面刷新走同一路径）
    setShareToken(token)
  }
  router.push(url)
  await router.isReady()
  const wrapper = mount(SharedTaskSessionView, {
    global: {
      plugins: [i18n, router],
    },
  })
  await flushPromises()
  return wrapper
}

const exchangeResponse = (overrides: Record<string, unknown> = {}) => ({
  view_mode: 'READ_ONLY',
  access_token: 'access-token-1',
  access_expires_at: '2026-09-18T12:30:00Z',
  visitor_id: 'visitor-1',
  share_id: 'share-abc',
  task_name: '分享的任务',
  instruction_text: null,
  expires_at: '2026-09-25T00:00:00Z',
  redirect_path: null,
  ...overrides,
})

describe('SharedTaskSessionView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    clearShareSession()
    sessionStorage.clear()
    router.replace('/').catch(() => {})
  })

  it('renders read-only history as session bubbles', async () => {
    vi.mocked(shareExchange).mockResolvedValue(exchangeResponse() as never)
    vi.mocked(fetchSharedHistory).mockResolvedValue({
      messages: [
        {
          message_id: 'm-1',
          role: 'user',
          content: '你好',
          safe_message_type: 'text',
          created_at: '2026-09-18T10:00:00Z',
          safe_card_summary: null,
        },
        {
          message_id: 'm-2',
          role: 'assistant',
          content: '收到',
          safe_message_type: 'text',
          created_at: '2026-09-18T10:01:00Z',
          safe_card_summary: null,
        },
        {
          message_id: 'm-3',
          role: 'assistant',
          content: '原始内部结构',
          safe_message_type: 'unsupported',
          created_at: '2026-09-18T10:02:00Z',
          safe_card_summary: '计划卡片摘要',
        },
      ],
      has_more: false,
      next_cursor: null,
    } as never)

    const wrapper = await mountView('/share/session', 'raw-token-xyz')

    expect(shareExchange).toHaveBeenCalledWith('raw-token-xyz')
    expect(wrapper.find('.shared-task-name').text()).toBe('分享的任务')
    expect(wrapper.find('.shared-readonly-badge').exists()).toBe(true)

    // 会话气泡：用户右对齐 / 助手左对齐；未适配卡片走摘要
    const bubbles = wrapper.findAll('.message-wrapper')
    expect(bubbles).toHaveLength(3)
    expect(bubbles[0].classes()).toContain('role-user')
    expect(bubbles[1].classes()).toContain('role-assistant')
    expect(bubbles[0].find('.message-bubble').text()).toContain('你好')
    expect(bubbles[2].find('.shared-msg-unsupported').text()).toBe('计划卡片摘要')
    // 未登录：显示登录引导
    expect(wrapper.find('.shared-login-hint').exists()).toBe(true)
    wrapper.unmount()
  })

  it('hides login hint when the visitor is authenticated', async () => {
    vi.mocked(shareExchange).mockResolvedValue(exchangeResponse() as never)
    vi.mocked(fetchSharedHistory).mockResolvedValue({
      messages: [],
      has_more: false,
      next_cursor: null,
    } as never)

    const wrapper = await mountView('/share/session', 'authed-token', { authToken: 'user-token' })
    expect(wrapper.find('.shared-login-hint').exists()).toBe(false)
    wrapper.unmount()
  })

  it('loads older messages upward when has_more', async () => {
    vi.mocked(shareExchange).mockResolvedValue(exchangeResponse() as never)
    vi.mocked(fetchSharedHistory)
      .mockResolvedValueOnce({
        messages: [{
          message_id: 'm-2', role: 'assistant', content: '新消息',
          safe_message_type: 'text', created_at: '2026-09-18T10:01:00Z', safe_card_summary: null,
        }],
        has_more: true,
        next_cursor: 'cursor-1',
      } as never)
      .mockResolvedValueOnce({
        messages: [{
          message_id: 'm-1', role: 'user', content: '旧消息',
          safe_message_type: 'text', created_at: '2026-09-18T10:00:00Z', safe_card_summary: null,
        }],
        has_more: false,
        next_cursor: null,
      } as never)

    const wrapper = await mountView('/share/session', 'paged-token')
    expect(wrapper.find('.shared-load-more').exists()).toBe(true)
    expect(wrapper.findAll('.message-wrapper')).toHaveLength(1)

    await wrapper.find('.shared-load-more').trigger('click')
    await flushPromises()

    // 旧消息 prepend 到顶部
    const texts = wrapper.findAll('.message-bubble').map((n) => n.text())
    expect(texts).toEqual(['旧消息', '新消息'])
    expect(wrapper.find('.shared-load-more').exists()).toBe(false)
    wrapper.unmount()
  })

  it('refreshes history incrementally when the WS nudge fires', async () => {
    let exchangeCount = 0
    vi.mocked(shareExchange).mockImplementation(async () => {
      exchangeCount += 1
      return exchangeResponse() as never
    })
    vi.mocked(fetchSharedHistory)
      .mockResolvedValueOnce({
        messages: [{
          message_id: 'm-1', role: 'user', content: '第一条',
          safe_message_type: 'text', created_at: '2026-09-18T10:00:00Z', safe_card_summary: null,
        }],
        has_more: false,
        next_cursor: null,
      } as never)
      .mockResolvedValueOnce({
        messages: [
          {
            message_id: 'm-1', role: 'user', content: '第一条',
            safe_message_type: 'text', created_at: '2026-09-18T10:00:00Z', safe_card_summary: null,
          },
          {
            message_id: 'm-2', role: 'assistant', content: '实时新增',
            safe_message_type: 'text', created_at: '2026-09-18T10:05:00Z', safe_card_summary: null,
          },
        ],
        has_more: false,
        next_cursor: null,
      } as never)

    const wrapper = await mountView('/share/session', 'ws-token')
    expect(wrapper.findAll('.message-wrapper')).toHaveLength(1)

    // 模拟 WS nudge：通过组件暴露的 refresh 触发（生产由 onmessage 调用）
    await (wrapper.vm as unknown as { refreshHistory: () => Promise<void> }).refreshHistory()
    await flushPromises()

    const texts = wrapper.findAll('.message-bubble').map((n) => n.text())
    expect(texts).toEqual(['第一条', '实时新增'])
    wrapper.unmount()
  })

  it('renders INPUT_ONLY view with instruction and submits with idempotency key', async () => {
    vi.mocked(shareExchange).mockResolvedValue(exchangeResponse({
      view_mode: 'INPUT_ONLY',
      instruction_text: '请描述你的问题',
    }) as never)
    vi.mocked(submitShareSuggestion).mockResolvedValue({
      submission_id: 'sg-1',
      client_submission_id: 'sub-1',
      created_at: '2026-09-18T10:05:00Z',
      status: 'PENDING',
    } as never)

    const wrapper = await mountView('/share/session', 'raw-token-input')

    expect(wrapper.find('.shared-instruction').text()).toBe('请描述你的问题')
    expect(wrapper.find('.shared-history').exists()).toBe(false)

    await wrapper.find('.shared-content-input').setValue('访客的建议内容')
    await wrapper.find('.shared-submit-btn').trigger('click')
    await flushPromises()

    expect(submitShareSuggestion).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(submitShareSuggestion).mock.calls[0][0]
    expect(payload.content).toBe('访客的建议内容')
    expect(payload.client_submission_id).toBeTruthy()
    expect(wrapper.text()).toContain('已提交，等待分享者采纳')
    wrapper.unmount()
  })

  it('shows the unavailable state for a revoked (deleted) share', async () => {
    vi.mocked(shareExchange).mockRejectedValue(
      new ShareApiError(404, 'SHARE_NOT_FOUND', 'not found')
    )

    const wrapper = await mountView('/share/session', 'revoked-token')

    expect(wrapper.find('.shared-unavailable').exists()).toBe(true)
    expect(wrapper.text()).toContain('链接不存在或已失效')
    wrapper.unmount()
  })

  it('shows not-found state when no token is present', async () => {
    const wrapper = await mountView('/share/session')

    expect(wrapper.find('.shared-unavailable').exists()).toBe(true)
    expect(wrapper.text()).toContain('链接不存在或已失效')
    expect(shareExchange).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('reloads history when the cursor goes stale (SHARE_HISTORY_STALE)', async () => {
    vi.mocked(shareExchange).mockResolvedValue(exchangeResponse() as never)
    vi.mocked(fetchSharedHistory)
      .mockRejectedValueOnce(new ShareApiError(409, 'SHARE_HISTORY_STALE', 'stale'))
      .mockResolvedValueOnce({
        messages: [{
          message_id: 'm-1',
          role: 'user',
          content: '刷新后的内容',
          safe_message_type: 'text',
          created_at: '2026-09-18T10:00:00Z',
          safe_card_summary: null,
        }],
        has_more: false,
        next_cursor: null,
      } as never)

    const wrapper = await mountView('/share/session', 'stale-token')

    expect(fetchSharedHistory).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.msg-content').text()).toBe('刷新后的内容')
    expect(wrapper.find('.shared-stale-hint').exists()).toBe(true)
    wrapper.unmount()
  })

  it('redirects logged-in members with task access via server path', async () => {
    vi.mocked(shareExchange).mockResolvedValue(exchangeResponse({
      view_mode: 'NORMAL_REDIRECT',
      redirect_path: '/workspaces/ws-1/chat/task-1',
    }) as never)

    await mountView('/share/session', 'member-token')

    expect(router.currentRoute.value.path).toBe('/workspaces/ws-1/chat/task-1')
  })
})
