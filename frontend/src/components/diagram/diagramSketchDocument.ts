import type { Point } from '@/utils/canvasViewport'
import { sketchAttachment } from './diagramAnchors'
import { diagramDrawings, inside } from './diagramGeometry'
import { recognizeArrowTip, recognizeSketch, type SketchArrowTip, type SketchLine } from './diagramSketch'
import { distance, last, resampleStroke, sketchBounds, type SketchStrokes, type SketchTiming } from './diagramSketchGeometry'
import { recognizeOutline, type SketchOutline } from './diagramSketchOutline'
import {
  freshId, isStroke, lineColor, makeNode, MAX_EDGES, MAX_NODES, MAX_SKETCH_POINTS, MAX_SKETCH_STROKES,
  type DiagramDocument, type DiagramEdge, type DiagramNode,
} from './diagramModel'

type SketchConnector = { points: Point[]; arrow: boolean } & ({ nodeId: string } | { edgeId: string })
type Bounds = ReturnType<typeof sketchBounds>
interface SketchFragment {
  id: string
  paths: SketchStrokes
  bounds: Bounds
  endedAt: number
}
export interface SketchSession {
  endedAt: number
  fragments: SketchFragment[]
  connector?: SketchConnector
}
interface SketchEdit {
  next: DiagramDocument
  original?: DiagramDocument
  session: SketchSession
}

const pauseLimitMs = 1800
const fragmentLimitMs = 6500

function strokeNode(shape: 'ink' | 'line', strokes: SketchStrokes, arrow = false, startArrow = false): DiagramNode {
  const bounds = sketchBounds(strokes)
  const width = Math.max(1, bounds.width), height = Math.max(1, bounds.height)
  const paths = strokes.map(path => {
    const points = path.length <= MAX_SKETCH_POINTS ? path : resampleStroke(path, MAX_SKETCH_POINTS)
    return points.map(({ x, y }): [number, number] => [
      Number(((x - bounds.x) / width).toFixed(4)),
      Number(((y - bounds.y) / height).toFixed(4)),
    ])
  })
  return {
    ...makeNode(shape, bounds, ''), ...bounds, width, height, paths, stroke: lineColor,
    ...(arrow ? { arrow: true } : {}),
    ...(startArrow ? { startArrow: true } : {}),
  }
}

function encloses(outer: DiagramNode, inner: DiagramNode) {
  return outer.id !== inner.id && outer.width > inner.width && outer.height > inner.height && inside(inner, outer)
}

function appendOutline(doc: DiagramDocument, node: DiagramNode): DiagramDocument {
  if (node.shape !== 'rectangle') return { ...doc, nodes: [...doc.nodes, node] }
  const nodes = doc.nodes.map(item => item.shape === 'rectangle' && encloses(item, node) ? { ...item, shape: 'frame' as const } : item)
  if (nodes.some(item => !isStroke(item.shape) && encloses(node, item))) node = { ...node, shape: 'frame' }
  return { ...doc, nodes: [...nodes, node] }
}

function outlineNode(outline: SketchOutline, id: string) {
  const { shape, x, y, width, height } = outline
  return { ...makeNode(shape, { x, y }, ''), id, width, height,
    ...(outline.shape === 'triangle' ? { direction: outline.direction } : {}) }
}

function boundsGap(a: Bounds, b: Bounds) {
  return Math.hypot(
    Math.max(0, a.x - b.x - b.width, b.x - a.x - a.width),
    Math.max(0, a.y - b.y - b.height, b.y - a.y - a.height),
  )
}

function nearbyOutline(fragments: SketchFragment[], strokes: SketchStrokes, unit: number) {
  const nearby: SketchFragment[] = []
  const bounds: Bounds[] = [sketchBounds(strokes)]
  const gap = 36 * unit
  // Follow nearby sides through a corner so an earlier opposite side can participate.
  for (let index = 0; index < bounds.length && nearby.length < MAX_SKETCH_STROKES; index++) {
    for (const candidate of fragments) {
      if (boundsGap(candidate.bounds, bounds[index]) > gap || nearby.includes(candidate)) continue
      bounds.push(candidate.bounds)
      nearby.push(candidate)
      if (nearby.length === MAX_SKETCH_STROKES) break
    }
  }

  const combinations: { paths: SketchStrokes; ids: string[] }[] = [{ paths: strokes, ids: [] }]
  for (const { paths, id } of nearby) {
    const additions = combinations.filter(part => part.paths.length + paths.length <= MAX_SKETCH_STROKES)
      .map(part => ({ paths: [...part.paths, ...paths], ids: [...part.ids, id] }))
    combinations.push(...additions)
  }
  let oval: { outline: SketchOutline; ids: Set<string> } | undefined
  for (const part of combinations.slice(1).sort((a, b) => a.ids.length - b.ids.length)) {
    const outline = recognizeOutline(part.paths, unit)
    if (!outline) continue
    const result = { outline, ids: new Set(part.ids) }
    if (outline.shape !== 'oval') return result
    oval ??= result
  }
  return oval
}

function attachedConnector(
  doc: DiagramDocument, line: Pick<SketchLine, 'traced' | 'arrow' | 'startArrow'>, unit: number,
): DiagramEdge | undefined {
  const { traced: points, arrow, startArrow } = line
  const start = sketchAttachment(doc.nodes, points, unit)
  const end = sketchAttachment(doc.nodes, [...points].reverse(), unit)
  if (!start || !end || start.node === end.node) return
  return {
    id: freshId(), source: start.node.id, target: end.node.id, label: '', stroke: lineColor,
    relation: startArrow ? 'bidirectional' : arrow ? 'flow' : 'association',
    routing: points.length === 2 ? 'straight' : 'orthogonal',
    anchors: [start.anchor, end.anchor],
  }
}

function visibleConnectors(doc: DiagramDocument) {
  const candidates: SketchConnector[] = []
  for (const { edge, geometry } of diagramDrawings(doc.nodes, doc.edges)) {
    if (edge.relation === 'association' || edge.relation === 'flow') {
      candidates.push({ edgeId: edge.id, points: geometry.points, arrow: edge.relation === 'flow' })
    }
  }
  for (const node of doc.nodes) {
    if (node.shape !== 'line' || !node.paths?.length || node.startArrow) continue
    const points = node.paths[0].map(([x, y]) => ({ x: node.x + x * node.width, y: node.y + y * node.height }))
    if (points.length >= 2) candidates.push({ nodeId: node.id, points, arrow: node.arrow === true })
  }
  return candidates
}

function findHeadSupplement(
  doc: DiagramDocument, strokes: SketchStrokes, fragments: SketchFragment[], unit: number, prior?: SketchConnector,
) {
  const bounds = sketchBounds(strokes)
  const withinHeadSize = (area: Bounds) => Math.hypot(area.width, area.height) <= 138 * unit
  if (!withinHeadSize(bounds)) return
  const candidates = visibleConnectors(doc)
  if (prior) candidates.unshift(prior)
  const inputs = [{ paths: strokes, fragments: [] as string[] }]
  for (const part of fragments) {
    if (boundsGap(bounds, part.bounds) > 12 * unit) continue
    const paths = [...strokes, ...part.paths]
    if (withinHeadSize(sketchBounds(paths))) inputs.push({ paths, fragments: [part.id] })
  }
  let best: { connector: SketchConnector; tip: SketchArrowTip; exact: boolean; ids: string[]; score: number } | undefined
  for (const input of inputs) {
    const area = sketchBounds(input.paths)
    const near = (point: Point, margin: number) => point.x >= area.x - margin && point.x <= area.x + area.width + margin
      && point.y >= area.y - margin && point.y <= area.y + area.height + margin
    for (const connector of candidates) {
      if ('nodeId' in connector && input.fragments.includes(connector.nodeId)) continue
      const exact = connector !== prior
      const margin = (exact ? 17 : 47) * unit
      if (!near(connector.points[0], margin) && (connector.arrow || !near(last(connector.points), margin))) continue
      const tip = recognizeArrowTip(connector.points, input.paths, unit, { visible: exact, at: connector.arrow ? 'start' : undefined })
      const score = (tip?.distance ?? Infinity) + input.fragments.length * 8 * unit
      if (tip && (!best || score < best.score)) best = { connector, tip, exact, ids: input.fragments, score }
    }
  }
  return best
}

function addArrowhead(
  doc: DiagramDocument, { connector, tip, exact }: NonNullable<ReturnType<typeof findHeadSupplement>>, unit: number,
): { next: DiagramDocument; connector?: SketchConnector } {
  const startArrow = connector.arrow
  const reverse = tip.at === 'start' && !startArrow
  const points = [...connector.points]
  if (!exact && 'nodeId' in connector) points[tip.at === 'start' ? 0 : points.length - 1] = tip.point
  if (reverse) points.reverse()
  if ('nodeId' in connector) {
    const line = { traced: points, arrow: true, ...(startArrow ? { startArrow: true as const } : {}) }
    const connection = !exact && doc.edges.length < MAX_EDGES ? attachedConnector(doc, line, unit) : undefined
    if (connection) return {
      next: { ...doc, nodes: doc.nodes.filter(node => node.id !== connector.nodeId), edges: [...doc.edges, connection] },
      connector: startArrow ? undefined : { edgeId: connection.id, points, arrow: true },
    }
    const arrow = strokeNode('line', [points], true, startArrow)
    const nodes = doc.nodes.map(node => node.id === connector.nodeId
      ? { ...node, x: arrow.x, y: arrow.y, width: arrow.width, height: arrow.height, paths: arrow.paths,
        arrow: true, ...(startArrow ? { startArrow: true } : {}) } : node)
    return { next: { ...doc, nodes }, connector: startArrow ? undefined : { ...connector, points, arrow: true } }
  }
  const edges = doc.edges.map((edge): DiagramEdge => {
    if (edge.id !== connector.edgeId) return edge
    if (!reverse) return { ...edge, relation: startArrow ? 'bidirectional' : 'flow' }
    return { ...edge, relation: 'flow', source: edge.target, target: edge.source,
      ...(edge.anchors ? { anchors: [edge.anchors[1], edge.anchors[0]] } : {}) }
  })
  return { next: { ...doc, edges }, connector: startArrow ? undefined : { ...connector, points, arrow: true } }
}

function finishPreDrawnHeads(line: SketchLine, fragments: SketchFragment[], unit: number) {
  const ids = new Set<string>()
  const traced = [...line.traced], points = [...line.points]
  let start = line.startArrow === true, end = line.arrow
  for (const at of ['start', 'end'] as const) {
    if (at === 'start' ? start : end) continue
    let best: { tip: SketchArrowTip; id: string } | undefined
    for (const fragment of fragments) {
      if (ids.has(fragment.id)) continue
      const tip = recognizeArrowTip(line.traced, fragment.paths, unit, { at })
      if (tip && (!best || tip.distance < best.tip.distance)) best = { tip, id: fragment.id }
    }
    if (!best) continue
    ids.add(best.id)
    const index = at === 'start' ? 0 : points.length - 1
    points[index] = traced[index] = best.tip.point
    if (at === 'start') start = true
    else end = true
  }
  if (start && !end) {
    points.reverse()
    traced.reverse()
  }
  const finished: SketchLine = { ...line, traced, points, arrow: start || end, ...(start && end ? { startArrow: true } : {}) }
  return { line: finished, ids }
}

export function applySketch(
  doc: DiagramDocument, strokes: SketchStrokes, unit: number, timing: SketchTiming, previous?: SketchSession,
): SketchEdit | undefined {
  if (!strokes.length || doc.nodes.length >= MAX_NODES) return
  const continued = previous && timing.startedAt - previous.endedAt <= pauseLimitMs ? previous : undefined
  const fragments = continued?.fragments.filter(part => timing.startedAt - part.endedAt <= fragmentLimitMs) ?? []
  const ink = strokeNode('ink', strokes)
  const original = { ...doc, nodes: [...doc.nodes, ink] }

  function result(next: DiagramDocument, fragment = false, connector?: SketchConnector): SketchEdit {
    const retained = fragments.filter(part => next.nodes.some(node => node.id === part.id && !node.arrow))
    const bounds = ink
    if (fragment && strokes.every(path => distance(path[0], last(path)) >= Math.min(36 * unit,
      Math.max(8 * unit, Math.hypot(bounds.width, bounds.height) * .17)))) {
      retained.push({ id: ink.id, paths: strokes, bounds, endedAt: timing.endedAt })
    }
    return { next, original: next === original ? undefined : original,
      session: { endedAt: timing.endedAt, fragments: retained.slice(-MAX_SKETCH_STROKES), connector } }
  }

  const shape = recognizeSketch(strokes, unit)
  if (shape?.kind === 'outline') return result(appendOutline(doc, outlineNode(shape, ink.id)))
  const supplement = findHeadSupplement(doc, strokes, fragments, unit, continued?.connector)
  if (supplement) {
    const base = supplement.ids.length ? { ...doc, nodes: doc.nodes.filter(node => !supplement.ids.includes(node.id)) } : doc
    const added = addArrowhead(base, supplement, unit)
    return result(added.next, false, added.connector)
  }
  const prepared = shape && finishPreDrawnHeads(shape, fragments, unit)
  const line = prepared?.line
  const base = prepared?.ids.size ? { ...doc, nodes: doc.nodes.filter(node => !prepared.ids.has(node.id)) } : doc
  if (line && base.edges.length < MAX_EDGES) {
    const edge = attachedConnector(base, line, unit)
    if (edge) return result({ ...base, edges: [...base.edges, edge] }, false,
      line.startArrow ? undefined : { edgeId: edge.id, points: line.traced, arrow: line.arrow })
  }
  if (!line?.arrow && fragments.length) {
    const assembled = nearbyOutline(fragments, strokes, unit)
    if (assembled) {
      const base = { ...doc, nodes: doc.nodes.filter(node => !assembled.ids.has(node.id)) }
      return result(appendOutline(base, outlineNode(assembled.outline, ink.id)))
    }
  }
  if (!line) return result(original, true)
  const node = { ...strokeNode('line', [line.points], line.arrow, line.startArrow), id: ink.id }
  return result({ ...base, nodes: [...base.nodes, node] }, !line.arrow,
    line.startArrow ? undefined : { nodeId: node.id, points: line.traced, arrow: line.arrow })
}
