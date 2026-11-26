import { center, type Point } from '@/utils/canvasViewport'
import { isContainer, type Arrangement, type DiagramDocument, type DiagramEdge, type DiagramNode, type Shape } from './diagramModel'
import { layoutHierarchy } from './diagramHierarchy'

function rounded(width: number, height: number, radius: number) {
  const r = Math.min(radius, width / 2, height / 2)
  return `M ${r} 0 H ${width - r} Q ${width} 0 ${width} ${r} V ${height - r}
    Q ${width} ${height} ${width - r} ${height} H ${r} Q 0 ${height} 0 ${height - r} V ${r} Q 0 0 ${r} 0 Z`
}

function ellipse(width: number, height: number) {
  return `M 0 ${height / 2} A ${width / 2} ${height / 2} 0 1 1 ${width} ${height / 2}
    A ${width / 2} ${height / 2} 0 1 1 0 ${height / 2} Z`
}

export function shapeOutline(shape: Shape, w: number, h: number) {
  switch (shape) {
    case 'terminal': return rounded(w, h, h / 2)
    case 'state': return rounded(w, h, 16)
    case 'topic': case 'topicRoot': return rounded(w, h, 14)
    case 'client': return rounded(w, h * .85, 5)
    case 'decision': return `M ${w / 2} 0 L ${w} ${h / 2} L ${w / 2} ${h} L 0 ${h / 2} Z`
    case 'data': return `M ${w * .13} 0 H ${w} L ${w * .87} ${h} H 0 Z`
    case 'document': return `M 0 0 H ${w} V ${h * .83} Q ${w * .78} ${h * .72} ${w / 2} ${h * .89}
      T 0 ${h * .95} Z`
    case 'note': {
      const fold = Math.min(w, h) * .2
      return `M 0 0 H ${w} V ${h - fold} L ${w - fold} ${h} H 0 Z`
    }
    case 'usecase': case 'initial': case 'final': return ellipse(w, h)
    case 'lifeline': return rounded(w, Math.min(h * .35, 50), 5)
    case 'database': return `M 0 ${h * .14} C 0 ${-h * .045} ${w} ${-h * .045} ${w} ${h * .14}
      V ${h * .86} C ${w} ${h * 1.045} 0 ${h * 1.045} 0 ${h * .86} Z`
    case 'cloud': return `M ${w * .2} ${h * .91} C ${w * -.035} ${h * .91} ${-w * .035} ${h * .43} ${w * .19} ${h * .36}
      C ${w * .22} 0 ${w * .52} ${-h * .04} ${w * .62} ${h * .26}
      C ${w * .86} ${h * .08} ${w} ${h * .39} ${w * .91} ${h * .48}
      C ${w * 1.09} ${h * .61} ${w * 1.02} ${h * .91} ${w * .81} ${h * .91} Z`
    default: return rounded(w, h, shape === 'subflow' || shape === 'class' ? 2 : 5)
  }
}

export function shapeDecoration(shape: Shape, w: number, h: number) {
  switch (shape) {
    case 'subflow': return `M ${w * .1} 0 V ${h} M ${w * .9} 0 V ${h}`
    case 'note': {
      const fold = Math.min(w, h) * .2
      return `M ${w} ${h - fold} H ${w - fold} V ${h}`
    }
    case 'actor': return `M ${w * .5} ${h * .35} V ${h * .59} M ${w * .22} ${h * .43} H ${w * .78}
      M ${w * .25} ${h * .79} L ${w * .5} ${h * .59} L ${w * .75} ${h * .79}`
    case 'lane': return `M ${Math.min(92, w * .2)} 0 V ${h}`
    case 'client': return `M ${w * .5} ${h * .85} V ${h} M ${w * .33} ${h} H ${w * .67}`
    case 'database': return `M 0 ${h * .14} C 0 ${h * .33} ${w} ${h * .33} ${w} ${h * .14}`
    case 'service': return `M ${w * .07} ${h * .43} L ${w * .13} ${h * .34} L ${w * .19} ${h * .43} L ${w * .13} ${h * .52} Z
      M ${w * .07} ${h * .57} L ${w * .13} ${h * .66} L ${w * .19} ${h * .57}`
    case 'server': case 'queue': return `M ${w * .065} ${h * .34} H ${w * .2} V ${h * .66} H ${w * .065} Z
      M ${w * .065} ${h * .5} H ${w * .2}`
    case 'router': return `M ${w * .07} ${h * .42} H ${w * .2} L ${w * .16} ${h * .35}
      M ${w * .2} ${h * .58} H ${w * .07} L ${w * .11} ${h * .65}`
    case 'firewall': return `M ${w * .065} ${h * .36} H ${w * .205} V ${h * .64} H ${w * .065} Z
      M ${w * .065} ${h * .5} H ${w * .205} M ${w * .135} ${h * .36} V ${h * .5}`
    case 'person': return `M ${w * .135} ${h * .37} a ${h * .075} ${h * .075} 0 1 0 0.001 0
      M ${w * .07} ${h * .69} Q ${w * .073} ${h * .55} ${w * .135} ${h * .55}
      T ${w * .2} ${h * .69}`
    default: return ''
  }
}

export interface EdgeDrawing {
  points: Point[]
  path: string
  label: Point
}

const pathThrough = (points: Point[]) => points.map(({ x, y }, index) => `${index ? 'L' : 'M'} ${x} ${y}`).join(' ')
const midpoint = (a: Point, b: Point) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })

export function edgeDrawing(edge: DiagramEdge, source: DiagramNode, target: DiagramNode, offset = 0): EdgeDrawing {
  const from = center(source, source)
  const to = center(target, target)
  if (source.shape === 'lifeline' && target.shape === 'lifeline') {
    const y = Math.max(source.y, target.y) + (edge.offset ?? 76)
    const points = source.id === target.id
      ? [{ x: from.x, y }, { x: from.x + 64, y }, { x: from.x + 64, y: y + 22 }, { x: from.x, y: y + 22 }]
      : [{ x: from.x, y }, { x: to.x, y }]
    return { points, path: pathThrough(points), label: midpoint(points[0], points[1]) }
  }
  if (source.id === target.id) {
    const points = [
      { x: source.x + source.width, y: from.y + offset },
      { x: source.x + source.width + 58, y: from.y + offset },
      { x: source.x + source.width + 58, y: source.y - 36 - Math.abs(offset) },
      { x: from.x, y: source.y - 36 - Math.abs(offset) },
      { x: from.x, y: source.y },
    ]
    return { points, path: pathThrough(points), label: midpoint(points[2], points[3]) }
  }

  const dx = to.x - from.x
  const dy = to.y - from.y
  const horizontal = edge.relation === 'branch' || (edge.relation !== 'reporting'
    && Math.abs(dx) / (source.width + target.width) >= Math.abs(dy) / (source.height + target.height))
  const axis = horizontal ? 'x' : 'y'
  const cross = horizontal ? 'y' : 'x'
  const size = horizontal ? 'width' : 'height'
  const sign = to[axis] >= from[axis] ? 1 : -1
  from[axis] += sign * source[size] / 2
  to[axis] -= sign * target[size] / 2
  const anchorOffset = (node: DiagramNode) => Math.min(node[horizontal ? 'height' : 'width'] * .18, Math.abs(offset)) * Math.sign(offset)
  if (source.shape !== 'decision' && source.shape !== 'usecase') from[cross] += anchorOffset(source)
  if (target.shape !== 'decision' && target.shape !== 'usecase') to[cross] += anchorOffset(target)

  const label = midpoint(from, to)
  if (edge.routing === 'straight') {
    return { points: [from, to], path: pathThrough([from, to]), label }
  }
  if (edge.routing === 'curve') {
    const handle = sign * Math.max(28, Math.abs(to[axis] - from[axis]) * .52)
    const a = { ...from, [axis]: from[axis] + handle }
    const b = { ...to, [axis]: to[axis] - handle }
    return {
      points: [from, a, b, to], label,
      path: `M ${from.x} ${from.y} C ${a.x} ${a.y} ${b.x} ${b.y} ${to.x} ${to.y}`,
    }
  }
  const middle = (from[axis] + to[axis]) / 2 + offset * .65
  const a = { ...from, [axis]: middle }
  const b = { ...to, [axis]: middle }
  const points = [from, a, b, to]
  return { points, path: pathThrough(points), label: midpoint(a, b) }
}

export function diagramDrawings(nodes: DiagramNode[], edges: DiagramEdge[]) {
  const byId = new Map(nodes.map(node => [node.id, node]))
  const straightPairs = (edge: DiagramEdge) => edge.source < edge.target ? `${edge.source}:${edge.target}` : `${edge.target}:${edge.source}`
  const counts = new Map<string, number>()
  const rendered = new Map<string, number>()
  for (const edge of edges) {
    const key = straightPairs(edge)
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return edges.flatMap(edge => {
    const source = byId.get(edge.source), target = byId.get(edge.target)
    if (!source || !target) return []
    const key = straightPairs(edge)
    const index = rendered.get(key) ?? 0
    rendered.set(key, index + 1)
    return [{ edge, geometry: edgeDrawing(edge, source, target, (index - ((counts.get(key) ?? 1) - 1) / 2) * 16) }]
  })
}

export function diagramBounds(nodes: DiagramNode[], drawings: ReturnType<typeof diagramDrawings>) {
  if (!nodes.length) return { left: 0, top: 0, width: 320, height: 200 }
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity
  const include = (x: number, y: number) => {
    left = Math.min(left, x); top = Math.min(top, y)
    right = Math.max(right, x); bottom = Math.max(bottom, y)
  }
  for (const node of nodes) {
    include(node.x, node.y)
    include(node.x + node.width, node.y + node.height)
  }
  for (const { edge, geometry } of drawings) {
    for (const point of geometry.points) include(point.x, point.y)
    if (edge.label) {
      const width = Math.min(100, edge.label.length * 7)
      include(geometry.label.x - width, geometry.label.y - 36)
      include(geometry.label.x + width, geometry.label.y + 20)
    }
  }
  return { left: left - 24, top: top - 24, width: Math.ceil(right - left + 48), height: Math.ceil(bottom - top + 48) }
}

export function inside(node: DiagramNode, bounds: Point & { width: number; height: number }) {
  return node.x >= bounds.x && node.y >= bounds.y
    && node.x + node.width <= bounds.x + bounds.width && node.y + node.height <= bounds.y + bounds.height
}

export function arrangedNodes(doc: DiagramDocument, selected: ReadonlySet<string>, arrangement: Arrangement) {
  if (arrangement === 'mindmap' || arrangement === 'organization') return layoutHierarchy(doc, selected, arrangement === 'mindmap')
  const automatic = arrangement === 'horizontal' || arrangement === 'vertical'
  const nodes = doc.nodes.filter(node => automatic ? !isContainer(node.shape) && (!selected.size || selected.has(node.id)) : selected.has(node.id))
  if (nodes.length < 2) return doc.nodes
  if (automatic) return layeredLayout(doc, nodes, arrangement === 'horizontal')
  const axis = ['alignLeft', 'distributeX'].includes(arrangement) ? 'x' : 'y'
  const dimension = axis === 'x' ? 'width' : 'height'
  const ordered = [...nodes].sort((a, b) => a[axis] - b[axis])
  const start = ordered[0][axis]
  let position = start
  const final = Math.max(...ordered.map(node => node[axis] + node[dimension]))
  const total = ordered.reduce((sum, node) => sum + node[dimension], 0)
  const gap = Math.max(0, (final - start - total) / (ordered.length - 1))
  const positions = new Map(ordered.map(node => {
    const next = arrangement.startsWith('align') ? start : position
    position += node[dimension] + gap
    return [node.id, next] as const
  }))
  return doc.nodes.map(node => positions.has(node.id) ? { ...node, [axis]: positions.get(node.id)! } : node)
}

function layeredLayout(doc: DiagramDocument, nodes: DiagramNode[], horizontal: boolean) {
  const byId = new Map(nodes.map(node => [node.id, node]))
  const incoming = new Map(nodes.map(node => [node.id, 0]))
  const outgoing = new Map(nodes.map(node => [node.id, [] as string[]]))
  for (const edge of doc.edges) {
    if (!byId.has(edge.source) || !byId.has(edge.target) || edge.source === edge.target) continue
    outgoing.get(edge.source)!.push(edge.target)
    incoming.set(edge.target, incoming.get(edge.target)! + 1)
  }
  const order = nodes.map(node => node.id)
  const pending = new Set(order)
  const ready = order.filter(id => !incoming.get(id))
  const depth = new Map<string, number>()
  const layers = new Map<number, DiagramNode[]>()
  let head = 0
  while (pending.size) {
    // When a component has a cycle, start at its first remaining node and route the return edge back.
    const id = head < ready.length ? ready[head++] : pending.values().next().value!
    if (!pending.delete(id)) continue
    const layer = depth.get(id) ?? 0
    const group = layers.get(layer) ?? []
    group.push(byId.get(id)!)
    layers.set(layer, group)
    for (const child of outgoing.get(id)!) {
      if (!pending.has(child)) continue
      depth.set(child, Math.max(depth.get(child) ?? 0, layer + 1))
      const count = incoming.get(child)! - 1
      incoming.set(child, count)
      if (!count) ready.push(child)
    }
  }
  const primary = horizontal ? 'x' : 'y'
  const cross = horizontal ? 'y' : 'x'
  const dimension = horizontal ? 'width' : 'height'
  const secondary = horizontal ? 'height' : 'width'
  let start = Math.min(...nodes.map(node => node[primary]))
  const base = Math.min(...nodes.map(node => node[cross]))
  const placed = new Map<string, DiagramNode>()
  for (const [, group] of [...layers].sort(([a], [b]) => a - b)) {
    let row = base
    for (const node of group) {
      placed.set(node.id, { ...node, [primary]: start, [cross]: row })
      row += node[secondary] + 48
    }
    start += Math.max(...group.map(node => node[dimension])) + 104
  }
  return doc.nodes.map(node => placed.get(node.id) ?? node)
}
