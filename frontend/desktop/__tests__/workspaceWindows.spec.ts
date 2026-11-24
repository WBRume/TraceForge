import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createWorkspaceWindows } from '../workspaceWindows'
import type { WorkspaceWindowDriver } from '../workspaceWindows'

const main = 'main'
const scope = '["https://example.test","user-1"]'
const home = '/workspaces'
const task = '/workspaces/project/chat/task?message=17'
const mock = '/workspaces/project/api-mock'
const bounds = { x: -1780, y: 278, width: 1140, height: 750, maximized: true }
const connect = (path = home, owner: string | null = scope) => ({ type: 'connect', scope: owner, path } as const)

function testDriver() {
  return {
    create: vi.fn<WorkspaceWindowDriver['create']>().mockResolvedValue(undefined),
    restoreMain: vi.fn<WorkspaceWindowDriver['restoreMain']>(),
    destroy: vi.fn<WorkspaceWindowDriver['destroy']>(),
    focus: vi.fn<WorkspaceWindowDriver['focus']>(),
    pointer: vi.fn<WorkspaceWindowDriver['pointer']>().mockReturnValue({ screen: { x: -800, y: 400 } }),
    emit: vi.fn<WorkspaceWindowDriver['emit']>(),
  }
}

describe('Windows workspace tab layout', () => {
  let directory: string
  beforeEach(async () => { directory = await mkdtemp(join(tmpdir(), 'traceforge-layout-')) })
  afterEach(async () => { await rm(directory, { recursive: true, force: true }) })

  it('restores the active route, tab title, order and native placement for both windows', async () => {
    const driver = testDriver()
    const app = createWorkspaceWindows(driver, directory)
    const start = (await app.command(main, connect(task)))!
    await app.command(main, { type: 'title', tabId: start.activeTabId, path: task, title: 'Review access' })
    const view = (await app.command(main, { type: 'open', path: mock }))!
    await app.command(main, { type: 'move', tabId: view.activeTabId, destination: { position: { x: -800, y: 400 } } })
    const child = driver.create.mock.calls[0]![0]
    app.geometry(main, { ...bounds, x: 100, maximized: false })
    app.geometry(child, bounds)
    await app.command(main, { type: 'open', path: '/workspaces/project/assets/requirements' })
    await app.command(main, { type: 'select', tabId: start.activeTabId })
    await app.flush()

    const restoredDriver = testDriver()
    const restored = createWorkspaceWindows(restoredDriver, directory)
    const mainView = (await restored.command(main, connect()))!
    expect(mainView.activeTabId).toBe(start.activeTabId)
    expect(mainView.tabs.map(tab => [tab.path, tab.title])).toEqual([
      [task, 'Review access'], ['/workspaces/project/assets/requirements', undefined],
    ])
    expect(restoredDriver.restoreMain).toHaveBeenCalledWith({ ...bounds, x: 100, maximized: false })
    expect(restoredDriver.create).toHaveBeenCalledWith(child, bounds)
    expect((await restored.command(child, connect()))?.tabs.map(tab => tab.path)).toEqual([mock])
    await restored.flush()
  })

  it('reorders tabs and transfers to an insertion point before closing an empty detached window', async () => {
    const driver = testDriver()
    const app = createWorkspaceWindows(driver, directory)
    const initial = (await app.command(main, connect()))!
    const view = (await app.command(main, { type: 'open', path: mock }))!
    const first = initial.activeTabId
    const second = view.activeTabId
    const ordered = await app.command(main, { type: 'move', tabId: second, destination: { windowId: main, beforeTabId: first } })
    expect(ordered?.tabs.map(tab => tab.id)).toEqual([second, first])
    await app.command(main, { type: 'move', tabId: second, destination: {} })
    const child = driver.create.mock.calls[0]![0]
    app.setStrip(main, { x: 90, y: 0, width: 460, height: 46, tabs: [{ id: first, midpoint: 160 }] })
    driver.pointer.mockReturnValue({ windowId: main, local: { x: 110, y: 14 }, screen: { x: 880, y: 210 } })
    expect(await app.drag(child, second, 'preview')).toEqual({ windowId: main, beforeTabId: first })
    expect(driver.emit).toHaveBeenLastCalledWith(main, 'sdd:workspace-window:drop-hint', { beforeTabId: first })
    const destination = (await app.drag(child, second, 'drop'))!
    expect(driver.emit).toHaveBeenLastCalledWith(main, 'sdd:workspace-window:drop-hint', null)
    expect(await app.command(child, { type: 'move', tabId: second, destination })).toBeNull()
    expect(driver.destroy).toHaveBeenCalledWith(child)
    expect(driver.focus).toHaveBeenCalledWith(main)
    expect((await app.command(main, connect()))?.tabs.map(tab => tab.id)).toEqual([second, first])
    await app.flush()
  })

  it('keeps the source tab after a failed detach and isolates saved tabs across accounts', async () => {
    const driver = testDriver()
    const app = createWorkspaceWindows(driver, directory)
    const view = (await app.command(main, connect(task)))!
    const tabId = view.activeTabId
    driver.create.mockRejectedValueOnce(new Error('create failed'))
    await expect(app.command(main, { type: 'move', tabId, destination: {} })).rejects.toThrow('create failed')
    expect(await app.command(main, connect())).toEqual(view)
    await app.command(main, { type: 'move', tabId, destination: {} })
    const child = driver.create.mock.calls[1]![0]
    expect(await app.command(main, connect(home, null))).toBeNull()
    expect(driver.destroy).toHaveBeenCalledWith(child)
    expect((await app.command(main, connect(home, 'another user')))?.tabs.map(tab => tab.path)).toEqual([home])
    expect(await app.command(child, connect())).toBeNull()
    await app.command(main, connect())
    expect((await app.command(child, connect()))?.tabs[0]?.path).toBe(task)
    await app.flush()
  })
})
