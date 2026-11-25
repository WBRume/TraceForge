import type { LocationQueryRaw, RouteLocationNormalized, RouteLocationRaw, RouteRecordRaw } from 'vue-router'

export const WORKSPACE_ASSET_CANVAS = 'workspaceAssetsCanvas'

interface AssetOperation {
  name: string
  path: string
  component: NonNullable<RouteRecordRaw['component']>
  title: string
  alias?: string | string[]
  context?: 'canvas'
  wide?: boolean
}

const operations: AssetOperation[] = [
  {
    name: 'workspaceRequirementDocument', path: 'assets/requirement-documents/:documentId',
    component: () => import('../views/RequirementDocumentView.vue'),
    title: 'workspace_canvas.kind.requirement_document', wide: true,
  },
  {
    name: 'workspaceAssetsRequirementDetail', path: 'assets/requirements/:requirementId',
    component: () => import('../views/WorkspaceAssetRequirementDetailView.vue'), title: 'workspace_canvas.kind.requirement',
  },
  {
    name: 'workspaceAssetsRequirementEdit', path: 'assets/requirements/:requirementId/edit',
    component: () => import('../views/WorkspaceAssetRequirementEditView.vue'), title: 'workspace_canvas.actions.edit_requirement',
  },
  {
    name: 'workspaceAssetsRequirementChild', path: 'assets/requirements/:requirementId/children/new',
    component: () => import('../views/WorkspaceAssetRequirementEditView.vue'), title: 'workspace_assets.requirements.table.add_child',
  },
  {
    name: 'workspaceAssetRequirementSplitReview', path: 'assets/requirements/:requirementId/split-review/:batchId',
    component: () => import('../views/WorkspaceAssetRequirementSplitReviewView.vue'),
    title: 'workspace_assets.requirements.create.split_title', wide: true,
  },
  {
    name: 'workspaceAssetsTaskFinalWorkflow', path: 'assets/tasks/:taskId/final-workflow',
    component: () => import('../views/WorkspaceAssetTaskFinalWorkflowView.vue'),
    title: 'workspace_canvas.actions.final_workflow', wide: true,
  },
  {
    name: 'workspaceAssetTaskDetail', path: 'assets/tasks/:taskId',
    component: () => import('../views/WorkspaceAssetTaskDetailView.vue'), title: 'workspace_canvas.kind.task',
  },
  {
    name: 'deltaWorkbench', path: 'assets/tasks/:taskId/deltas/:deltaId/workbench',
    component: () => import('../views/DeltaWorkbenchView.vue'), title: 'workspace_canvas.actions.human_delta', wide: true,
  },
  {
    name: 'workspaceCaseDetail', path: 'assets/cases/:caseId', alias: 'cases/:caseId',
    component: () => import('../views/CaseReportView.vue'), title: 'workspace_canvas.kind.case',
  },
  {
    name: 'workspacePlaybookDetail', path: 'assets/cases/playbooks/:playbookId',
    alias: ['cases/playbooks/:playbookId', 'playbooks/:playbookId'],
    component: () => import('../views/PlaybookDetailView.vue'), title: 'workspace_canvas.actions.playbooks',
  },
  {
    name: 'workspaceCasePromotionReview', path: 'assets/cases/promotions/:jobId', alias: 'cases/promotions/:jobId',
    component: () => import('../views/CasePromotionReviewView.vue'), title: 'workspace_canvas.actions.case_promotion', wide: true,
  },
  {
    name: 'taskSpec', path: 'chat/:taskId/spec', context: 'canvas', wide: true,
    component: () => import('../views/TaskSpecView.vue'), title: 'workspace_canvas.kind.document',
  },
  {
    name: 'taskChat', path: 'chat/:taskId?', context: 'canvas', wide: true,
    component: () => import('../views/ChatView.vue'), title: 'workspace_canvas.actions.task_session',
  },
]

const operationsByName = new Map(operations.map(operation => [operation.name, operation]))
const indexRoutes = new Set([
  'workspaceAssetsOverview', 'workspaceAssetsRequirements', 'workspaceAssetsTasks',
  'workspaceCases', 'workspaceAssetsKnowledgeBase',
])

function panelName(name: string) {
  return `${WORKSPACE_ASSET_CANVAS}:${name}`
}

export function isCanvasRoute(route: Pick<RouteLocationNormalized, 'meta'> & { name?: RouteLocationNormalized['name'] | null }) {
  return route.name === WORKSPACE_ASSET_CANVAS || Boolean(route.meta?.assetOperation)
}

export const workspaceAssetOperationRoutes: RouteRecordRaw[] = operations.map(({ path, name, component, alias }) => ({
  path, name, component, ...(alias ? { alias } : {}),
}))

export const workspaceAssetCanvasRoute: RouteRecordRaw = {
  path: 'assets/canvas',
  name: WORKSPACE_ASSET_CANVAS,
  component: () => import('../views/WorkspaceAssetCanvasView.vue'),
  children: [
    ...operations.map(({ path, name, component, title, wide, context }) => ({
      path: context ? path.replace(':taskId?', ':taskId') : path.slice('assets/'.length),
      name: panelName(name),
      component,
      meta: { assetOperation: name, canvasTitle: title, canvasWide: wide },
    })),
    {
      path: 'playbooks',
      name: WORKSPACE_ASSET_CANVAS + ':playbooks',
      component: () => import('../components/workspace-canvas/CanvasCaseTools.vue'),
      meta: { assetOperation: 'playbooks', canvasTitle: 'workspace_canvas.actions.case_tools' },
    },
  ],
}

export function canvasOperationTarget(name: string, params: Record<string, string>, query?: LocationQueryRaw) {
  return { name: panelName(name), params, query }
}

export function workspaceAssetPresentation(
  to: RouteLocationNormalized,
  from: RouteLocationNormalized,
  mode: 'table' | 'canvas',
): RouteLocationRaw | undefined {
  const name = String(to.name ?? '')
  const wsId = to.params.wsId
  if (typeof wsId !== 'string') return
  if (mode === 'table' && isCanvasRoute(to)) {
    const fallback = String(to.meta.assetOperation ?? '')
    if (operationsByName.has(fallback)) return { name: fallback, params: to.params, query: to.query, hash: to.hash }
    return { name: 'workspaceAssetsRequirements', params: { wsId } }
  }
  if (mode !== 'canvas' || isCanvasRoute(to)) return
  const operation = operationsByName.get(name)
  const fromCanvas = isCanvasRoute(from) && from.params.wsId === wsId
  if (operation && (!operation.context || (fromCanvas && (name !== 'taskChat' || to.params.taskId)))) {
    return { name: panelName(name), params: to.params, query: to.query, hash: to.hash }
  }
  if (!indexRoutes.has(name)) return
  const { requirementId, case: caseId, ...query } = to.query
  if (typeof requirementId === 'string' && requirementId) {
    return { name: panelName('workspaceAssetsRequirementDetail'), params: { wsId, requirementId }, query }
  }
  if (name === 'workspaceCases' && typeof caseId === 'string' && caseId) {
    return { name: panelName('workspaceCaseDetail'), params: { wsId, caseId }, query }
  }
  if (name === 'workspaceCases' && (query.tab === 'playbooks' || query.promotionJob)) {
    return { name: panelName('playbooks'), params: { wsId }, query }
  }
  return { name: WORKSPACE_ASSET_CANVAS, params: { wsId }, query }
}
