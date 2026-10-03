import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import type { SearchItem } from '@/types/search'
import type { RuntimeState, TaskRuntimeEvent } from '@/types/taskAwareness'

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
  source?: 'manual' | 'automatic'
  runId?: string
  runtimeState?: RuntimeState
  runtimeSummary?: string
}

const STORAGE_KEY = 'tf_pinned_search_floats'

function extractText(item: SearchItem): string {
  if (!item.snippet || !item.snippet.length) return ''
  return item.snippet.map((s) => s.text).join('')
}

function loadInitialItems(key = STORAGE_KEY): PinnedSearchItem[] {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      return parsed.filter((item) => item && typeof item.id === 'string' && item.source !== 'automatic')
    }
  } catch {
    // 忽略异常，降级为空列表
  }
  return []
}

export const usePinnedFloatsStore = defineStore('pinnedFloats', () => {
  const items = ref<PinnedSearchItem[]>(loadInitialItems())
  let storageKey = STORAGE_KEY

  const scope = (userId: string, server: string) => {
    const key = `${STORAGE_KEY}:${encodeURIComponent(server)}:${userId}`
    if (key === storageKey) return
    let restored = userId ? loadInitialItems(key) : []
    // Adopt the existing account's pins once; later accounts have separate storage.
    try {
      if (userId && localStorage.getItem(key) === null) {
        restored = loadInitialItems()
        localStorage.removeItem(STORAGE_KEY)
      }
    } catch { /* Storage is optional. */ }
    storageKey = key
    items.value = restored.map(item => ({ ...item, runId: undefined, runtimeState: undefined, runtimeSummary: undefined }))
  }

  // 持久化到 localStorage
  watch(
    items,
    (val) => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(val.filter(item => item.source !== 'automatic')))
      } catch {
        // storage quota exceeded or disabled
      }
    },
    { deep: true, flush: 'sync' }
  )

  const isPinned = (id: string) => items.value.some((item) => item.id === id)

  const pin = (searchItem: SearchItem) => {
    const existing = items.value.find((i) => i.id === searchItem.entity_key
      || (searchItem.kind === 'task' && i.kind === 'task' && i.taskId === searchItem.target.params.taskId))
    if (existing) {
      existing.minimized = false
      existing.source = 'manual'
      return existing
    }

    if (searchItem.kind !== 'task' && searchItem.kind !== 'message') return
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
      source: 'manual',
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
    if (items.value.find(item => item.id === searchItem.entity_key)?.source === 'automatic') {
      pin(searchItem)
    } else if (isPinned(searchItem.entity_key)) {
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

  const pinTask = (task: { id: string; name: string; workspaceId: string; workspaceName: string }) => pin({
    entity_key: `task:${task.id}`, kind: 'task', workspace_name: task.workspaceName, task_name: task.name,
    created_at: '', snippet_basis: 'plain', snippet: [],
    target: { route_name: 'taskChat', params: { wsId: task.workspaceId, taskId: task.id }, query: {} },
  })

  const dockRuntime = (event: TaskRuntimeEvent) => {
    let item = items.value.find(item => item.kind === 'task' && item.taskId === event.task.id)
    if (!item) {
      item = pinTask({ id: event.task.id, name: event.task.title, workspaceId: event.workspace.id, workspaceName: event.workspace.name })
      if (!item) return
      item.source = 'automatic'
      item.minimized = true
    }
    item.runId = event.run.id
    item.runtimeState = event.event_type
    item.runtimeSummary = event.summary
    return item
  }

  const clearAutomatic = () => { items.value = items.value.filter(item => item.source !== 'automatic') }

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
    pinTask,
    dockRuntime,
    clearAutomatic,
    scope,
  }
})
