import { createHash, randomUUID } from 'node:crypto'
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import {
  isWorkspaceTabPath, MAIN_WORKSPACE_WINDOW, WORKSPACE_HOME, WORKSPACE_TAB_LIMIT,
} from '../src/types/workspaceWindows'
import type {
  TabDestination, TabStripBounds, WindowCommand, WindowPlacement, WindowPoint,
  WorkspaceTab, WorkspaceWindowState, WorkspaceWindowUpdate,
} from '../src/types/workspaceWindows'

const WINDOW_LIMIT = 12
const windowIdPattern = /^workspace-[a-f0-9-]{36}$/
const tabIdPattern = /^[a-f0-9-]{36}$/

interface WindowPointer {
  screen: WindowPoint
  windowId?: string
  local?: WindowPoint
}

export interface WorkspaceWindowDriver {
  create(id: string, placement?: WindowPlacement, position?: WindowPoint): Promise<void>
  restoreMain(placement: WindowPlacement): Promise<void> | void
  destroy(id: string): Promise<void> | void
  focus(id: string): Promise<void> | void
  pointer(): Promise<WindowPointer> | WindowPointer
  emit(id: string, event: string, payload: unknown): void
}

interface SavedWindow {
  id: string
  tabs: WorkspaceTab[]
  activeTabId: string
  placement?: WindowPlacement
}

function finitePoint(value: WindowPoint | undefined): value is WindowPoint {
  return !!value && [value.x, value.y].every(number => Number.isFinite(number) && Math.abs(number) <= 100000)
}

export function validWindowPlacement(placement?: WindowPlacement): placement is WindowPlacement {
  return finitePoint(placement) && [placement.width, placement.height].every(value => Number.isFinite(value) && value > 0 && value <= 32768)
}

function savedWindow(value: SavedWindow): SavedWindow | null {
  if (!value || (value.id !== MAIN_WORKSPACE_WINDOW && !windowIdPattern.test(value.id)) || !Array.isArray(value.tabs)) return null
  const ids = new Set<string>()
  const tabs = value.tabs.filter(tab => {
    if (!tab || !tabIdPattern.test(tab.id) || !isWorkspaceTabPath(tab.path) || ids.has(tab.id)) return false
    ids.add(tab.id)
    return true
  }).slice(0, WORKSPACE_TAB_LIMIT).map(({ id, path, title }) => ({
    id, path, title: typeof title === 'string' ? title.slice(0, 160) : undefined,
  }))
  if (!tabs.length) return null
  return {
    id: value.id,
    tabs,
    activeTabId: tabs.find(tab => tab.id === value.activeTabId)?.id ?? tabs[0]!.id,
    placement: validWindowPlacement(value.placement) ? value.placement : undefined,
  }
}

const newTab = (path: string): WorkspaceTab => ({ id: randomUUID(), path })
const singleTab = (id: string, tab: WorkspaceTab): SavedWindow => ({ id, tabs: [tab], activeTabId: tab.id })

export function createWorkspaceWindows(driver: WorkspaceWindowDriver, storageDirectory: string) {
  let scope: string | null = null
  let revision = 0
  let queue: Promise<unknown> = Promise.resolve()
  let disk: Promise<unknown> = Promise.resolve()
  let saveTimer: ReturnType<typeof setTimeout> | undefined
  let hint: { source: string; windowId: string; beforeTabId?: string } | null = null
  const windows = new Map<string, SavedWindow>()
  const strips = new Map<string, TabStripBounds>()
  const layouts = join(storageDirectory, 'workspace-layouts')

  const pathFor = (principal: string) => join(layouts, `${createHash('sha256').update(principal).digest('hex')}.json`)
  const enqueue = <T>(operation: () => T | Promise<T>): Promise<T> => {
    const result = queue.then(operation)
    queue = result.catch(() => {})
    return result
  }

  function save() {
    clearTimeout(saveTimer)
    saveTimer = undefined
    if (!scope || !windows.size) return disk
    const path = pathFor(scope)
    const contents = JSON.stringify({ version: 1, windows: [...windows.values()] })
    disk = disk.then(async () => {
      await mkdir(layouts, { recursive: true })
      const temporary = `${path}.${process.pid}.tmp`
      await writeFile(temporary, contents)
      await rename(temporary, path)
    }).catch(error => console.error('Failed to save workspace layout', error))
    return disk
  }

  function scheduleSave() {
    clearTimeout(saveTimer)
    saveTimer = setTimeout(save, 200)
  }

  function state(id: string): WorkspaceWindowState | null {
    const window = windows.get(id)
    if (!window || !scope) return null
    return { id, scope, revision, activeTabId: window.activeTabId, tabs: window.tabs.map(tab => ({ ...tab })) }
  }

  function publish(id: string, receivedTabId?: string) {
    const snapshot = state(id)
    if (snapshot) driver.emit(id, 'sdd:workspace-window:update', { state: snapshot, receivedTabId } satisfies WorkspaceWindowUpdate)
  }

  function setHint(source: string, destination: TabDestination | null) {
    const next = destination && 'windowId' in destination ? { source, ...destination } : null
    if (hint?.windowId === next?.windowId && hint?.beforeTabId === next?.beforeTabId && hint?.source === next?.source) return
    if (hint && hint.windowId !== next?.windowId) driver.emit(hint.windowId, 'sdd:workspace-window:drop-hint', null)
    hint = next
    if (next) driver.emit(next.windowId, 'sdd:workspace-window:drop-hint', { beforeTabId: next.beforeTabId })
  }

  async function connect(id: string, request: Extract<WindowCommand, { type: 'connect' }>) {
    const requested = typeof request.scope === 'string' && request.scope.length <= 2048 && request.scope ? request.scope : null
    if (id !== MAIN_WORKSPACE_WINDOW) return requested === scope ? state(id) : null
    if (scope === requested) return state(id)
    const previous = [...windows.keys()].filter(key => key !== MAIN_WORKSPACE_WINDOW)
    setHint(id, null)
    await save()
    windows.clear()
    strips.clear()
    scope = requested
    await Promise.allSettled(previous.map(key => driver.destroy(key)))
    if (!scope) return null

    const restored = new Map<string, SavedWindow>()
    try {
      const stored = JSON.parse(await readFile(pathFor(scope), 'utf8'))
      if (stored.version === 1 && Array.isArray(stored.windows)) {
        for (const raw of stored.windows.slice(0, WINDOW_LIMIT)) {
          const window = savedWindow(raw)
          if (window) restored.set(window.id, window)
        }
      }
    } catch { /* A first launch or an unreadable layout uses a fresh tab. */ }
    const main = restored.get(id) ?? singleTab(id, newTab(isWorkspaceTabPath(request.path) ? request.path : WORKSPACE_HOME))
    windows.set(id, main)
    if (main.placement) await Promise.resolve(driver.restoreMain(main.placement)).catch(error => console.error('Failed to restore main window bounds', error))
    for (const window of restored.values()) {
      if (window.id === id) continue
      windows.set(window.id, window)
      try {
        await driver.create(window.id, window.placement)
      } catch (error) {
        windows.delete(window.id)
        main.tabs.push(...window.tabs.slice(0, WORKSPACE_TAB_LIMIT - main.tabs.length))
        console.error('Failed to restore workspace window', error)
      }
    }
    revision++
    scheduleSave()
    return state(id)
  }

  function removeTab(window: SavedWindow, tabId: string) {
    const index = window.tabs.findIndex(tab => tab.id === tabId)
    if (index === -1) return
    window.tabs.splice(index, 1)
    if (!window.tabs.length && window.id === MAIN_WORKSPACE_WINDOW) window.tabs.push(newTab(WORKSPACE_HOME))
    if (window.activeTabId === tabId) window.activeTabId = (window.tabs[index] ?? window.tabs.at(-1))?.id ?? ''
  }

  async function finishMutation(id: string) {
    revision++
    const snapshot = state(id)
    if (snapshot && !snapshot.tabs.length) {
      windows.delete(id)
      strips.delete(id)
      scheduleSave()
      await driver.destroy(id)
      return null
    }
    publish(id)
    scheduleSave()
    return snapshot
  }

  async function move(source: SavedWindow, tab: WorkspaceTab, destination: TabDestination) {
    let target: SavedWindow | undefined
    if ('windowId' in destination) {
      target = windows.get(destination.windowId)
      if (!target) throw new Error('The destination window has closed')
      if (target.id === source.id) {
        if (destination.beforeTabId === tab.id) return state(source.id)
        source.tabs = source.tabs.filter(candidate => candidate.id !== tab.id)
      } else if (target.tabs.length >= WORKSPACE_TAB_LIMIT) {
        throw new Error('The destination window is full')
      }
      const before = target.tabs.findIndex(candidate => candidate.id === destination.beforeTabId)
      target.tabs.splice(before === -1 ? target.tabs.length : before, 0, tab)
      if (target.id === source.id) return finishMutation(source.id)
    } else {
      if (windows.size >= WINDOW_LIMIT) throw new Error('There are too many workspace windows')
      if (destination.position && !finitePoint(destination.position)) throw new Error('Invalid window position')
      target = singleTab(`workspace-${randomUUID()}`, tab)
      windows.set(target.id, target)
      try {
        await driver.create(target.id, undefined, destination.position)
      } catch (error) {
        windows.delete(target.id)
        throw error
      }
    }
    removeTab(source, tab.id)
    const result = await finishMutation(source.id)
    if ('windowId' in destination) {
      publish(target.id, tab.id)
      await driver.focus(target.id)
    }
    return result
  }

  function command(id: string, request: WindowCommand) {
    return enqueue(async () => {
      if (request.type === 'connect') return connect(id, request)
      const window = windows.get(id)
      if (!window) return null
      if (request.type === 'open') {
        if (!isWorkspaceTabPath(request.path) || window.tabs.length >= WORKSPACE_TAB_LIMIT) throw new Error('Cannot open tab')
        const tab = newTab(request.path)
        window.tabs.push(tab)
        window.activeTabId = tab.id
        return finishMutation(id)
      }
      const tab = window.tabs.find(candidate => candidate.id === request.tabId)
      if (!tab) return state(id)
      switch (request.type) {
        case 'navigate':
          if (!isWorkspaceTabPath(request.path) || tab.path === request.path) return state(id)
          tab.path = request.path
          tab.title = undefined
          break
        case 'title': {
          if (request.path !== tab.path || typeof request.title !== 'string') return state(id)
          const title = request.title.trim().slice(0, 160)
          if (!title || tab.title === title) return state(id)
          tab.title = title
          break
        }
        case 'select':
          window.activeTabId = tab.id
          break
        case 'close':
          removeTab(window, tab.id)
          break
        case 'move':
          return move(window, tab, request.destination)
      }
      return finishMutation(id)
    })
  }

  function setStrip(id: string, strip: TabStripBounds | null) {
    if (!strip) {
      strips.delete(id)
      if (hint?.windowId === id || hint?.source === id) setHint(id, null)
      return
    }
    if (validWindowPlacement({ ...strip, maximized: false }) && Array.isArray(strip.tabs) && strip.tabs.length <= WORKSPACE_TAB_LIMIT) {
      strips.set(id, strip)
    }
  }

  async function drag(id: string, tabId: string, phase: 'preview' | 'drop' | 'cancel'): Promise<TabDestination | null> {
    if (phase === 'cancel' || !windows.get(id)?.tabs.some(tab => tab.id === tabId)) {
      if (hint?.source === id) setHint(id, null)
      return null
    }
    const { screen, local, windowId } = await driver.pointer()
    const strip = windowId ? strips.get(windowId) : undefined
    let destination: TabDestination | null = null
    if (windowId && local && strip
      && local.x >= strip.x && local.x < strip.x + strip.width && local.y >= strip.y && local.y < strip.y + strip.height) {
      const target = windows.get(windowId)
      if (target && (windowId === id || target.tabs.length < WORKSPACE_TAB_LIMIT)) {
        const before = strip.tabs.find(tab => tab.id !== tabId && local.x < tab.midpoint)
        destination = { windowId, beforeTabId: before?.id }
      }
    } else if (windows.size < WINDOW_LIMIT && (!windowId
      || (windowId === id && strip && local && local.y > strip.y + strip.height + 36))) {
      destination = { position: screen }
    }
    setHint(id, phase === 'preview' ? destination : null)
    return destination
  }

  return {
    command, setStrip, drag,
    geometry(id: string, placement: WindowPlacement) {
      const window = windows.get(id)
      if (!window || !validWindowPlacement(placement)) return
      window.placement = placement
      scheduleSave()
    },
    closed(id: string) {
      if (id === MAIN_WORKSPACE_WINDOW || !windows.delete(id)) return
      setStrip(id, null)
      scheduleSave()
    },
    async flush() {
      await queue
      await save()
    },
  }
}
