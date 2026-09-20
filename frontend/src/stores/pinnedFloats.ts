import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import type { SearchItem } from '@/types/search'

export interface PinnedSearchItem {
  id: string
  kind: 'task' | 'message'
  workspaceId: string
  workspaceName: string
  taskId: string
  taskName: string
  messageId?: string
  role?: string
  creatorName?: string | null
  creatorAvatarUrl?: string | null
  creatorAvatarSvg?: string | null
  snippetText: string
  created_at?: string
  minimized: boolean
  position: { x: number; y: number }
  size: { width: number; height: number }
  dockTop: number
}

const STORAGE_KEY = 'tf_pinned_search_floats'

function extractText(item: SearchItem): string {
  if (!item.snippet || !item.snippet.length) return ''
  return item.snippet.map((s) => s.text).join('')
}

function loadInitialItems(): PinnedSearchItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      return parsed.filter((item) => item && typeof item.id === 'string')
    }
  } catch {
    // 忽略异常，降级为空列表
  }
  return []
}

export const usePinnedFloatsStore = defineStore('pinnedFloats', () => {
  const items = ref<PinnedSearchItem[]>(loadInitialItems())

  // 持久化到 localStorage
  watch(
    items,
    (val) => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(val))
      } catch {
        // storage quota exceeded or disabled
      }
    },
    { deep: true }
  )

  const isPinned = (id: string) => items.value.some((item) => item.id === id)

  const pin = (searchItem: SearchItem) => {
    const existing = items.value.find((i) => i.id === searchItem.entity_key)
    if (existing) {
      existing.minimized = false
      return existing
    }

    const isTask = searchItem.kind === 'task'
    const defaultWidth = isTask ? 420 : 360
    const defaultHeight = isTask ? 480 : 280

    // 计算初始展开位置：右下角偏移，多个错开
    const count = items.value.length
    const offset = (count % 5) * 24
    const x = Math.max(20, (window.innerWidth || 1200) - defaultWidth - 32 - offset)
    const y = Math.max(60, (window.innerHeight || 800) - defaultHeight - 48 - offset)

    // 计算最小化右侧初始停靠 top 位置
    const dockTop = Math.min(
      (window.innerHeight || 800) - 80,
      180 + (count % 8) * 58
    )

    const wsId = searchItem.target?.params?.wsId || ''
    const taskId = searchItem.target?.params?.taskId || ''
    const messageId = searchItem.message_id || searchItem.target?.query?.messageId || undefined

    const newItem: PinnedSearchItem = {
      id: searchItem.entity_key,
      kind: searchItem.kind,
      workspaceId: wsId,
      workspaceName: searchItem.workspace_name,
      taskId: taskId,
      taskName: searchItem.task_name,
      messageId,
      role: searchItem.role,
      creatorName: searchItem.creator_display_name ?? null,
      creatorAvatarUrl: searchItem.creator_avatar_url ?? null,
      creatorAvatarSvg: searchItem.creator_avatar_svg ?? null,
      snippetText: extractText(searchItem),
      created_at: searchItem.created_at,
      minimized: false,
      position: { x, y },
      size: { width: defaultWidth, height: defaultHeight },
      dockTop,
    }

    items.value.push(newItem)
    return newItem
  }

  const unpin = (id: string) => {
    const idx = items.value.findIndex((i) => i.id === id)
    if (idx !== -1) {
      items.value.splice(idx, 1)
    }
  }

  const togglePin = (searchItem: SearchItem) => {
    if (isPinned(searchItem.entity_key)) {
      unpin(searchItem.entity_key)
    } else {
      pin(searchItem)
    }
  }

  const toggleMinimize = (id: string) => {
    const target = items.value.find((i) => i.id === id)
    if (target) {
      target.minimized = !target.minimized
    }
  }

  const setMinimized = (id: string, minimized: boolean) => {
    const target = items.value.find((i) => i.id === id)
    if (target) {
      target.minimized = minimized
    }
  }

  const updatePosition = (id: string, pos: { x: number; y: number }) => {
    const target = items.value.find((i) => i.id === id)
    if (target) {
      target.position = { ...pos }
    }
  }

  const updateSize = (id: string, size: { width: number; height: number }) => {
    const target = items.value.find((i) => i.id === id)
    if (target) {
      target.size = { ...size }
    }
  }

  const updateDockTop = (id: string, top: number) => {
    const target = items.value.find((i) => i.id === id)
    if (target) {
      target.dockTop = top
    }
  }

  const clearAll = () => {
    items.value = []
  }

  return {
    items,
    isPinned,
    pin,
    unpin,
    togglePin,
    toggleMinimize,
    setMinimized,
    updatePosition,
    updateSize,
    updateDockTop,
    clearAll,
  }
})
