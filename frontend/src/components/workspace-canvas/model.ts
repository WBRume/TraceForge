import { BookMarked, ClipboardList, FileText, Folder, MessageSquare, Workflow } from '@/components/icons'
import { canvasOperationTarget } from '@/router/workspaceAssetPresentation'
import { taskStatusKey } from '@/utils/taskStatus'

export const sourceKinds = ['requirement', 'document', 'requirement_document', 'plan_document', 'task', 'case', 'playbook'] as const
export type SourceKind = typeof sourceKinds[number]
export type CanvasCommand = 'requirement' | 'task' | 'case' | 'document' | 'playbooks'

export type DocumentReference =
  | { kind: 'document'; id: string; version_id?: string | null; block?: string | null }
  | { kind: 'plan_document'; id: string; section: 'plans' | 'specs'; path: string; block?: string | null }
  | { kind: 'requirement_document'; id: string; block?: string | null }

export type SourceReference = DocumentReference
  | { kind: 'requirement' | 'task' | 'case' | 'playbook'; id: string }

export interface SourceDetails {
  title: string
  detail: string | null
  context: string | null
  status: string | null
  version: number | null
  historical: boolean
  task_id: string | null
  task_type?: string | null
  created_at?: string | null
  has_children?: boolean
  parent_requirement_id?: string | null
}

export interface SourceItem {
  reference: SourceReference
  details: SourceDetails
}

export interface CanvasDocumentOwner {
  kind: 'requirement' | 'task'
  id: string
  title: string
  taskType?: string | null
}

export interface AssetQuarter { id: string; label_year: number; number: number }
export interface CanvasAsset extends SourceItem {
  node_id: string
  quarter?: AssetQuarter | null
  has_related?: boolean | null
  has_tree_children?: boolean
  has_unseen_children?: boolean
}

export interface PeriodSlice { id: string; index: number; start: string; end: string }
export interface FiscalQuarter extends AssetQuarter { year: number; start: string; end: string; months: PeriodSlice[] }
export type CalendarFormat = 'months' | '4-4-5' | '4-5-4' | '5-4-4'
export interface CanvasCalendarSettings {
  format: CalendarFormat
  start_month: number
  timezone: string
  year_label: 'start' | 'end'
  week_end: number
  week_end_rule: 'last' | 'nearest'
  extra_week_quarter: number
  overrides: { year: number; boundaries: string[] }[]
}
export interface CanvasCalendar { settings: CanvasCalendarSettings; can_edit: boolean; current: string; quarters: FiscalQuarter[] }

export type CanvasRootKind = Exclude<SourceKind, 'plan_document'>
export interface CanvasRootFilters {
  kind?: CanvasRootKind
  slice?: string
  task_type?: string
  status?: string
  creator_id?: string
  q?: string
}

export interface PlanFilesPage {
  items: CanvasAsset[]
  next_cursor: string | null
}

export interface SourcePage {
  items: SourceItem[]
  has_more: boolean
}

export const noteColors = ['yellow', 'mint', 'blue', 'lilac', 'rose'] as const
export type NoteColor = typeof noteColors[number]
export interface Point { x: number; y: number }
export interface Size { width: number; height: number }
export type CanvasTool = 'select' | 'pan' | 'note' | 'frame' | 'arrow' | 'relation'
export type CanvasConnection = 'arrow' | 'relation' | 'auto'
export type CanvasSelection = { type: 'node' | 'edge'; id: string }

export interface CanvasNodeInput {
  id: string
  kind: 'card' | 'note' | 'frame'
  position: Point
  size: Size
  text: string
  color: NoteColor
  reference: SourceReference | null
  scope_id?: string | null
}

export interface CanvasNode extends CanvasNodeInput {
  details: SourceDetails | null
  automatic?: boolean
  domainId?: string
  historicalQuarter?: AssetQuarter
  expandable?: boolean
  expandedChildren?: boolean
  unseenChildren?: boolean
}

export interface CanvasEdge {
  id: string
  source: string
  target: string
}

export interface CanvasRelation {
  source: SourceReference
  target: SourceReference
  relation_type: CanvasRelationType
  link_id?: string | null
}

export type CanvasRelationType = 'COVERS' | 'RELATES_TO' | 'DOCUMENT_TASK' | 'DOCUMENT_REQUIREMENT' | 'CASE_TASK'
  | 'CASE_PROMOTION' | 'CASE_PLAYBOOK' | 'TASK_PLAYBOOK' | 'SUB_REQUIREMENT' | 'PREREQUISITE'

export interface CanvasGraphRelation extends CanvasRelation {
  id: string
  sourceNodeId: string
  targetNodeId: string
}

export interface CanvasSnapshot {
  revision: number
  assets: CanvasAsset[]
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  relations: CanvasRelation[]
  access: { source_kinds: SourceKind[]; can_link_requirements: boolean }
  quarter?: FiscalQuarter
  root_tree?: boolean
  root_cursor?: string | null
  root_ids?: string[]
  preview_children?: Record<string, string[]>
  treeParents?: ReadonlyMap<string, string>
  collapsedAssets?: ReadonlySet<string>
  annotations_limited?: boolean
}

export type CanvasDomainKind = 'delivery' | 'standalone' | 'diagnosis' | 'knowledge'

export interface CanvasAssetWindow {
  assets: CanvasAsset[]
  relations: CanvasRelation[]
  next_cursor: string | null
}

export interface CanvasRootWindow extends CanvasAssetWindow {
  root_ids: string[]
  preview_children: Record<string, string[]>
}

export interface CanvasGraph extends Omit<CanvasSnapshot, 'assets' | 'relations'> {
  relations: CanvasGraphRelation[]
  regions: CanvasRegion[]
  continuations: CanvasBranchContinuation[]
  branchRoutes: ReadonlyMap<string, CanvasBranchRoute>
  scopeOffsets: ReadonlyMap<string, Point>
  assetNodeIds: ReadonlyMap<string, string>
}

export interface CanvasBranchContinuation {
  parentId: string
  position: Point
  stemHeight: number
}

export interface CanvasBranchRoute {
  parentId: string
  stemInset: number
}

export interface CanvasRegion {
  id: string
  type: 'domain' | 'section'
  kind: CanvasDomainKind | 'linked'
  title?: string
  assetCount: number
  position: Point
  size: Size
}

export type NodePatch = Partial<Pick<CanvasNodeInput, 'position' | 'size' | 'text' | 'color'>> & { expected_text?: string }
export type CanvasEdit =
  | { type: 'add_node'; node: CanvasNodeInput }
  | { type: 'update_node'; id: string; patch: NodePatch }
  | { type: 'remove_node'; id: string }
  | { type: 'add_edge'; edge: CanvasEdge }
  | { type: 'remove_edge'; id: string }

export const nodeSizes: Record<CanvasNode['kind'], Size> = {
  card: { width: 248, height: 150 },
  note: { width: 214, height: 156 },
  frame: { width: 470, height: 304 },
}

export const sourceIcons = {
  requirement: ClipboardList,
  task: MessageSquare,
  document: FileText,
  plan_document: Folder,
  requirement_document: FileText,
  case: BookMarked,
  playbook: Workflow,
}

export const canvasUrl = (workspaceId: string) => `/workspaces/${encodeURIComponent(workspaceId)}/canvas`
export const canvasId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
export const isDocument = (reference: SourceReference): reference is DocumentReference =>
  reference.kind === 'document' || reference.kind === 'plan_document' || reference.kind === 'requirement_document'

export function referenceKey(reference: SourceReference): string {
  switch (reference.kind) {
    case 'document': return JSON.stringify([reference.kind, reference.id, reference.version_id ?? '', reference.block ?? ''])
    case 'plan_document': return JSON.stringify([reference.kind, reference.id, reference.section, reference.path, reference.block ?? ''])
    case 'requirement_document': return JSON.stringify([reference.kind, reference.id, reference.block ?? ''])
    default: return JSON.stringify([reference.kind, reference.id])
  }
}

export function scopedAssetId(assetId: string, scopeId: string) {
  return `asset-${scopeId.slice(-26)}-${assetId.slice(-26)}`
}

export function nodeInput({ id, kind, position, size, text, color, reference, scope_id }: CanvasNode): CanvasNodeInput {
  return { id, kind, position, size, text, color, reference, scope_id }
}

type Translate = (key: string, values?: Record<string, unknown>) => string

export function cardStatus(item: SourceItem, translate: Translate, hasTranslation: (key: string) => boolean) {
  const { reference, details } = item
  const status = details.status
  if (status === 'EXCERPT_CHANGED') return translate('workspace_canvas.excerpt_changed')
  if (details.version) return translate(
    details.historical ? 'workspace_canvas.historical_version' : 'workspace_canvas.version',
    { version: details.version },
  )
  if (!status) return ''
  if (reference.kind === 'task') return translate(taskStatusKey(status))
  const key = reference.kind === 'requirement' ? `workspace_assets.requirements.status_labels.${status}`
    : reference.kind === 'case' ? `case_center.status.${status}`
    : reference.kind === 'playbook' ? `workspace_canvas.playbook_status.${status}` : ''
  return key && hasTranslation(key) ? translate(key) : status
}

export function assetOperation(workspaceId: string, node: Pick<CanvasNode, 'reference' | 'details'>) {
  const { reference, details } = node
  if (!reference || !details) return null
  const params = { wsId: workspaceId }
  switch (reference.kind) {
    case 'requirement': return canvasOperationTarget('workspaceAssetsRequirementDetail', { ...params, requirementId: reference.id })
    case 'task': return canvasOperationTarget('workspaceAssetTaskDetail', { ...params, taskId: reference.id })
    case 'case': return canvasOperationTarget('workspaceCaseDetail', { ...params, caseId: reference.id })
    case 'playbook': return canvasOperationTarget('workspacePlaybookDetail', { ...params, playbookId: reference.id })
    case 'requirement_document': return canvasOperationTarget('workspaceRequirementDocument', { ...params, documentId: reference.id },
      { block: reference.block || undefined })
    case 'document': return details.task_id ? canvasOperationTarget('taskSpec', { ...params, taskId: details.task_id }, {
      asset: reference.id, version: reference.version_id || undefined, block: reference.block || undefined,
    }) : null
    case 'plan_document': return canvasOperationTarget('taskSpec', { ...params, taskId: reference.id }, {
      plan: reference.section, path: reference.path, block: reference.block || undefined,
    })
  }
}
