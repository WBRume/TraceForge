import type { Point, Size } from '@/utils/canvasViewport'

export const shapeLibraries = {
  flow: ['process', 'terminal', 'decision', 'data', 'document', 'subflow', 'lane'],
  uml: ['class', 'interface', 'actor', 'usecase', 'lifeline', 'state', 'initial', 'final'],
  architecture: ['client', 'service', 'database', 'queue', 'cloud', 'server', 'router', 'firewall'],
  basic: ['topicRoot', 'topic', 'person', 'entity', 'note', 'text', 'frame'],
} as const
export type Library = keyof typeof shapeLibraries
export type Shape = (typeof shapeLibraries)[Library][number]
export const relations = [
  'flow', 'association', 'dependency', 'inheritance', 'realization', 'aggregation', 'composition', 'call', 'reply', 'many',
  'dataflow', 'network', 'branch', 'reporting',
] as const
export type Relation = (typeof relations)[number]
export const routings = ['orthogonal', 'straight', 'curve'] as const
export type Routing = (typeof routings)[number]
export type DiagramTool = 'select' | 'pan' | 'connect'
export type DiagramFormat = 'tfdiagram' | 'svg' | 'png'
export type Arrangement = 'horizontal' | 'vertical' | 'mindmap' | 'organization' | 'alignLeft' | 'alignTop' | 'distributeX' | 'distributeY'
export type NodeEdit = Partial<Omit<DiagramNode, 'id' | 'shape'>>
export type EdgeEdit = Partial<Pick<DiagramEdge, 'label' | 'relation' | 'routing' | 'stroke' | 'offset'>>

export interface DiagramNode extends Point, Size {
  id: string
  shape: Shape
  label: string
  detail: string
  operations: string
  fill: string
  stroke: string
}

export interface DiagramEdge {
  id: string
  source: string
  target: string
  label: string
  relation: Relation
  routing: Routing
  stroke: string
  offset?: number
}

export interface DiagramDocument {
  format: 'traceforge-diagram'
  version: 1
  title: string
  nodes: DiagramNode[]
  edges: DiagramEdge[]
}

export const GRID = 16
export const MAX_NODES = 1000
export const MAX_EDGES = 2400
export const MAX_FILE_BYTES = 5 * 1024 * 1024
export const shapeNames = Object.values(shapeLibraries).flat()
export const isContainer = (shape: Shape) => shape === 'frame' || shape === 'lane'
export const hasCompartments = (shape: Shape) => shape === 'class' || shape === 'interface' || shape === 'entity'
export const isTopic = (shape: Shape) => shape === 'topic' || shape === 'topicRoot'
export const isInfrastructure = (shape: Shape) => (shapeLibraries.architecture as readonly Shape[]).includes(shape)
export const hasSubtitle = (shape: Shape) => shape === 'person' || isInfrastructure(shape)
export const CAPTION_LIMIT = 240
export const CONTENT_LIMIT = 1200
export const lineColor = '#47627f'

const sizes: Partial<Record<Shape, [width: number, height: number]>> = {
  decision: [150, 108], class: [224, 156], interface: [224, 156], entity: [216, 156],
  actor: [100, 112], lifeline: [156, 352], state: [156, 64], initial: [30, 30], final: [34, 34],
  note: [160, 110], text: [180, 44], frame: [368, 240], lane: [688, 176],
  client: [166, 80], service: [168, 77], database: [162, 89], queue: [164, 77], cloud: [176, 94],
  server: [164, 77], router: [168, 76], firewall: [168, 76], person: [172, 78],
  topicRoot: [174, 72], topic: [144, 50],
}

const fills: Partial<Record<Shape, string>> = {
  terminal: '#e6f6f9', decision: '#fff3d9', document: '#f1f4ff', data: '#edf5fc', usecase: '#eaf4fe',
  class: '#f4f8ff', interface: '#f3efff', entity: '#e9f6f2', note: '#fff2bc', state: '#eaf4fe',
  frame: '#f5f9fd', lane: '#f0f6fc', final: '#ffffff',
  client: '#edf5fd', service: '#edf8ff', database: '#ebf7f5', queue: '#fff4db', cloud: '#edf4fb',
  server: '#eef4ff', router: '#e8f5fa', firewall: '#fff2e6', person: '#f4f8ff', topicRoot: '#d8eefb', topic: '#f3f8ff',
}

export const defaultStroke = '#5b799a'
export const blankDiagram = (title: string): DiagramDocument => ({ format: 'traceforge-diagram', version: 1, title, nodes: [], edges: [] })
export const freshId = () => crypto.randomUUID()
export const snapToGrid = (coordinate: number) => Math.round(coordinate / GRID) * GRID
export const minNodeSize = (shape: Shape): Size => {
  if (shape === 'initial' || shape === 'final') return { width: 20, height: 20 }
  if (hasCompartments(shape)) return { width: 116, height: 110 }
  if (shape === 'lifeline') return { width: 80, height: 116 }
  if (shape === 'actor') return { width: 64, height: 86 }
  return { width: 60, height: 32 }
}

export function makeNode(shape: Shape, point: Point, label: string): DiagramNode {
  const [width, height] = sizes[shape] ?? [160, 66]
  return {
    id: freshId(), shape, ...point, width, height, label, detail: '', operations: '',
    fill: fills[shape] ?? '#ffffff', stroke: defaultStroke,
  }
}

export function makeEdge(source: DiagramNode, target: DiagramNode, offset?: number): DiagramEdge {
  const sequence = source.shape === 'lifeline' && target.shape === 'lifeline'
  const useCase = [source.shape, target.shape].some(shape => shape === 'actor' || shape === 'usecase')
  let relation: Relation = 'flow'
  if (sequence) relation = 'call'
  else if (isTopic(source.shape) && isTopic(target.shape)) relation = 'branch'
  else if (source.shape === 'person' && target.shape === 'person') relation = 'reporting'
  else if (isInfrastructure(source.shape) && isInfrastructure(target.shape)) relation = 'dataflow'
  else if (source.shape === 'entity' && target.shape === 'entity') relation = 'many'
  else if (useCase || (hasCompartments(source.shape) && hasCompartments(target.shape))) relation = 'association'
  return {
    id: freshId(), source: source.id, target: target.id, label: '',
    relation, routing: sequence ? 'straight' : relation === 'branch' ? 'curve' : 'orthogonal', stroke: lineColor,
    offset: sequence ? Math.max(60, offset ?? 80) : undefined,
  }
}

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
const text = (value: unknown, limit: number) => typeof value === 'string' ? value.slice(0, limit) : ''
const color = (value: unknown, fallback: string) => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) ? value : fallback
const numeric = (value: unknown, min: number, max: number) =>
  typeof value === 'number' && Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : null
const validId = (value: unknown): value is string => typeof value === 'string' && /^[a-z0-9_-]{1,64}$/i.test(value)

export function decodeDiagram(raw: string): DiagramDocument {
  const invalid = () => new Error('Invalid drawing document')
  if (raw.length > MAX_FILE_BYTES) throw invalid()
  const data = record(JSON.parse(raw))
  if (!data || data.format !== 'traceforge-diagram' || data.version !== 1 || typeof data.title !== 'string'
    || !Array.isArray(data.nodes) || data.nodes.length > MAX_NODES || !Array.isArray(data.edges) || data.edges.length > MAX_EDGES) {
    throw invalid()
  }
  const nodeIds = new Set<string>()
  const nodes = data.nodes.map((source: unknown): DiagramNode => {
    const node = record(source)
    if (!node || !validId(node.id) || nodeIds.has(node.id) || !shapeNames.includes(node.shape as Shape)) throw invalid()
    const shape = node.shape as Shape
    const size = minNodeSize(shape)
    const x = numeric(node.x, -100000, 100000)
    const y = numeric(node.y, -100000, 100000)
    const width = numeric(node.width, size.width, 100000)
    const height = numeric(node.height, size.height, 100000)
    if (x === null || y === null || width === null || height === null) throw invalid()
    nodeIds.add(node.id)
    return {
      id: node.id, shape, x, y, width, height, label: text(node.label, CAPTION_LIMIT),
      detail: text(node.detail, CONTENT_LIMIT), operations: text(node.operations, CONTENT_LIMIT),
      fill: color(node.fill, fills[shape] ?? '#ffffff'), stroke: color(node.stroke, defaultStroke),
    }
  })
  const edgeIds = new Set<string>()
  const edges = data.edges.map((source: unknown): DiagramEdge => {
    const edge = record(source)
    if (!edge || !validId(edge.id) || edgeIds.has(edge.id) || !validId(edge.source) || !nodeIds.has(edge.source)
      || !validId(edge.target) || !nodeIds.has(edge.target)
      || !relations.includes(edge.relation as Relation) || !routings.includes(edge.routing as Routing)) throw invalid()
    edgeIds.add(edge.id)
    return {
      id: edge.id, source: edge.source, target: edge.target, label: text(edge.label, CAPTION_LIMIT),
      relation: edge.relation as Relation, routing: edge.routing as Routing,
      stroke: color(edge.stroke, lineColor), offset: numeric(edge.offset, 60, 100000) ?? undefined,
    }
  })
  return { ...blankDiagram(data.title.slice(0, 120)), nodes, edges }
}
