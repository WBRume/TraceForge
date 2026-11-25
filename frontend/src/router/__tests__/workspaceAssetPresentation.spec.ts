import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type RouteRecordRaw } from 'vue-router'
import { isCanvasRoute, workspaceAssetCanvasRoute, workspaceAssetOperationRoutes, workspaceAssetPresentation } from '../workspaceAssetPresentation'

function workbenchRouter(mode: 'table' | 'canvas') {
  const view = { template: '<div />' }
  function stub(record: RouteRecordRaw): RouteRecordRaw {
    const { path, name, meta, alias, children } = record
    const route = { path, name, meta, component: view, ...(alias ? { alias } : {}) }
    return children ? { ...route, children: children.map(stub) } : route
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{
      path: '/workspaces/:wsId',
      component: view,
      children: [
        { path: 'assets/requirements', name: 'workspaceAssetsRequirements', component: view },
        { path: 'assets/cases', name: 'workspaceCases', component: view },
        { path: 'api-mock', name: 'apiMock', component: view },
        ...workspaceAssetOperationRoutes.map(stub),
        stub(workspaceAssetCanvasRoute),
      ],
    }],
  })
  router.beforeEach((to, from) => workspaceAssetPresentation(to, from, mode))
  return router
}

describe('workspace asset workbench routing', () => {
  it('opens the canvas for the workspace asset entry and existing asset bookmarks', async () => {
    const router = workbenchRouter('canvas')
    await router.push('/workspaces/ws/assets/requirements')
    expect(router.currentRoute.value.path).toBe('/workspaces/ws/assets/canvas')
    await router.push('/workspaces/ws/cases/c1')
    expect(router.currentRoute.value.path).toBe('/workspaces/ws/assets/canvas/cases/c1')
    expect(isCanvasRoute(router.currentRoute.value)).toBe(true)
  })

  it('keeps asset edits, task sessions and document operations in the canvas', async () => {
    const router = workbenchRouter('canvas')
    await router.push('/workspaces/ws/assets/requirements/r1/edit')
    expect(router.currentRoute.value.path).toBe('/workspaces/ws/assets/canvas/requirements/r1/edit')
    await router.push('/workspaces/ws/chat/t1')
    expect(router.currentRoute.value.path).toBe('/workspaces/ws/assets/canvas/chat/t1')
    await router.push('/workspaces/ws/chat/t1/spec?asset=d1')
    expect(router.currentRoute.value.fullPath).toBe('/workspaces/ws/assets/canvas/chat/t1/spec?asset=d1')
  })

  it('opens API Mock as a standalone page from the canvas', async () => {
    const router = workbenchRouter('canvas')
    await router.push('/workspaces/ws/assets/canvas')
    await router.push('/workspaces/ws/api-mock?task=t1&endpoint=e1')
    expect(router.currentRoute.value.fullPath).toBe('/workspaces/ws/api-mock?task=t1&endpoint=e1')
    expect(isCanvasRoute(router.currentRoute.value)).toBe(false)
  })

  it('preserves table navigation and resolves canvas bookmarks for a table user', async () => {
    const router = workbenchRouter('table')
    await router.push('/workspaces/ws/assets/requirements')
    expect(router.currentRoute.value.path).toBe('/workspaces/ws/assets/requirements')
    await router.push('/workspaces/ws/assets/canvas/cases/c1')
    expect(router.currentRoute.value.path).toBe('/workspaces/ws/assets/cases/c1')
    expect(isCanvasRoute(router.currentRoute.value)).toBe(false)
  })
})
