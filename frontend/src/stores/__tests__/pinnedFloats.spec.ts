import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePinnedFloatsStore } from '../pinnedFloats'
import type { SearchItem } from '@/types/search'

describe('pinnedFloats store', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  const mockSearchItem: SearchItem = {
    entity_key: 'task-123',
    kind: 'task',
    workspace_name: '测试工作区',
    task_name: '优化用户界面',
    created_at: '2026-09-15T12:00:00Z',
    snippet_basis: 'keyword',
    snippet: [
      { text: '测试', match: true },
      { text: '任务详情内容', match: false },
    ],
    target: {
      route_name: 'taskChat',
      params: { wsId: 'ws-1', taskId: 'task-123' },
      query: {},
    },
  }

  const mockMessageItem: SearchItem = {
    entity_key: 'msg-456',
    kind: 'message',
    workspace_name: '测试工作区',
    task_name: '优化用户界面',
    message_id: 'msg-456',
    role: 'user',
    creator_id: 'user-1',
    creator_display_name: '张三',
    creator_avatar_url: null,
    creator_avatar_svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"></svg>',
    created_at: '2026-09-15T12:05:00Z',
    snippet_basis: 'semantic',
    snippet: [{ text: '请问这个功能如何使用？', match: true }],
    target: {
      route_name: 'taskChat',
      params: { wsId: 'ws-1', taskId: 'task-123' },
      query: { messageId: 'msg-456' },
    },
  }

  it('pins and unpins search items correctly', () => {
    const store = usePinnedFloatsStore()
    expect(store.items).toHaveLength(0)

    store.pin(mockSearchItem)
    expect(store.items).toHaveLength(1)
    expect(store.isPinned('task-123')).toBe(true)
    expect(store.items[0].kind).toBe('task')
    expect(store.items[0].taskName).toBe('优化用户界面')
    expect(store.items[0].snippetText).toBe('测试任务详情内容')

    store.togglePin(mockMessageItem)
    expect(store.items).toHaveLength(2)
    expect(store.isPinned('msg-456')).toBe(true)

    // 用户发言钉住时保留创建者身份（头像 + 用户名），供胶囊与浮窗展示
    const pinnedMessage = store.items.find((i) => i.id === 'msg-456')
    expect(pinnedMessage?.role).toBe('user')
    expect(pinnedMessage?.creatorName).toBe('张三')
    expect(pinnedMessage?.creatorAvatarSvg).toContain('<svg')
    expect(pinnedMessage?.creatorAvatarUrl).toBeNull()

    store.togglePin(mockMessageItem)
    expect(store.items).toHaveLength(1)
    expect(store.isPinned('msg-456')).toBe(false)

    store.unpin('task-123')
    expect(store.items).toHaveLength(0)
  })

  it('manages minimize, bounds and dockTop updates', () => {
    const store = usePinnedFloatsStore()
    store.pin(mockSearchItem)

    expect(store.items[0].minimized).toBe(false)
    store.toggleMinimize('task-123')
    expect(store.items[0].minimized).toBe(true)

    store.setMinimized('task-123', false)
    expect(store.items[0].minimized).toBe(false)

    store.updatePosition('task-123', { x: 100, y: 150 })
    expect(store.items[0].position).toEqual({ x: 100, y: 150 })

    store.updateSize('task-123', { width: 500, height: 600 })
    expect(store.items[0].size).toEqual({ width: 500, height: 600 })

    store.updateDockTop('task-123', 300)
    expect(store.items[0].dockTop).toBe(300)
  })
})
