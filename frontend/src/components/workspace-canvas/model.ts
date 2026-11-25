import { BookMarked, ClipboardList, FileText, Folder, MessageSquare } from '@/components/icons'
import { canvasOperationTarget } from '@/router/workspaceAssetPresentation'
import { taskStatusKey } from '@/utils/taskStatus'

export const sourceKinds = ['requirement', 'task', 'case', 'document', 'plan_document'] as const
export type SourceKind = typeof sourceKinds[number]
export type CanvasCommand = Exclude<SourceKind, 'plan_document'> | 'playbooks'

export type DocumentReference =
  | { kind: 'document'; id: string; version_id?: string | null; block?: string | null }
  | { kind: 'plan_document'; id: string; section: 'plans' | 'specs'; path: string; block?: string | null }

export type SourceReference = DocumentReference
  | { kind: 'requirement' | 'task' | 'case'; id: string }

export interface SourceDetails {
  title: string
  detail: string | null
  context: string | null
  status: string | null
  version: number | null
  historical: boolean
  task_id: string | null
}

export interface SourceItem {
  reference: SourceReference
  details: SourceDetails
}

export interface CanvasAsset extends SourceItem { node_id: string }

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
}

export interface CanvasNode extends CanvasNodeInput {
  details: SourceDetails | null
  automatic?: boolean
}

export interface CanvasEdge {
  id: string
  source: string
  target: string
}

export interface CanvasRelation {
  requirement_id: string
  task_id: string
  relation_type: string
}

export interface CanvasSnapshot {
  revision: number
  assets: CanvasAsset[]
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  relations: CanvasRelation[]
  access: { source_kinds: SourceKind[]; can_link_requirements: boolean }
}

export interface CanvasGroup {
  kind: SourceKind
  position: Point
}

export interface CanvasGraph extends Omit<CanvasSnapshot, 'assets'> {
  groups: CanvasGroup[]
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
  case: BookMarked,
}

export const canvasUrl = (workspaceId: string) => `/workspaces/${encodeURIComponent(workspaceId)}/canvas`
export const canvasId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
export const isDocument = (reference: SourceReference): reference is DocumentReference =>
  reference.kind === 'document' || reference.kind === 'plan_document'

export function referenceKey(reference: SourceReference): string {
  switch (reference.kind) {
    case 'document': return JSON.stringify([reference.kind, reference.id, reference.version_id ?? '', reference.block ?? ''])
    case 'plan_document': return JSON.stringify([reference.kind, reference.id, reference.section, reference.path, reference.block ?? ''])
    default: return JSON.stringify([reference.kind, reference.id])
  }
}

export function nodeInput({ id, kind, position, size, text, color, reference }: CanvasNode): CanvasNodeInput {
  return { id, kind, position, size, text, color, reference }
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
    : reference.kind === 'case' ? `case_center.status.${status}` : ''
  return key && hasTranslation(key) ? translate(key) : status
}

export function assetOperation(workspaceId: string, node: CanvasNode) {
  const { reference, details } = node
  if (!reference || !details) return null
  const params = { wsId: workspaceId }
  switch (reference.kind) {
    case 'requirement': return canvasOperationTarget('workspaceAssetsRequirementDetail', { ...params, requirementId: reference.id })
    case 'task': return canvasOperationTarget('workspaceAssetTaskDetail', { ...params, taskId: reference.id })
    case 'case': return canvasOperationTarget('workspaceCaseDetail', { ...params, caseId: reference.id })
    case 'document': return details.task_id ? canvasOperationTarget('taskSpec', { ...params, taskId: details.task_id }, {
      asset: reference.id, version: reference.version_id || undefined, block: reference.block || undefined,
    }) : null
    case 'plan_document': return canvasOperationTarget('taskSpec', { ...params, taskId: reference.id }, {
      plan: reference.section, path: reference.path, block: reference.block || undefined,
    })
  }
}
