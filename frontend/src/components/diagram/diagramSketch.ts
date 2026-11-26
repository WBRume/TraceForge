import type { Point } from '@/utils/canvasViewport'
import { distance, last, simplify, sketchBounds, type SketchStrokes } from './diagramSketchGeometry'
import { recognizeOutline, type SketchOutline } from './diagramSketchOutline'

export type ArrowEnd = 'start' | 'end'
export interface SketchLine {
  kind: 'line'
  points: Point[]
  traced: Point[]
  arrow: boolean
  startArrow?: true
}
export type SketchShape = SketchOutline | SketchLine

function cleanLine(points: readonly Point[], unit: number): Point[] | undefined {
  if (points.length < 2 || points.length > 5 || distance(points[0], last(points)) < 16 * unit) return
  const clean = points.map(point => ({ ...point }))
  let previousAxis: 'x' | 'y' | undefined
  for (let index = 1; index < clean.length; index++) {
    const a = points[index - 1], b = points[index]
    const dx = Math.abs(a.x - b.x), dy = Math.abs(a.y - b.y)
    if (Math.hypot(dx, dy) < 11 * unit) return
    const axis = dy <= dx * .19 ? 'y' : dx <= dy * .19 ? 'x' : undefined
    if (points.length > 2 && (!axis || axis === previousAxis)) return
    if (axis) clean[index - 1][axis] = clean[index][axis] = (a[axis] + b[axis]) / 2
    previousAxis = axis
  }
  return clean
}

function straightenWavyLine(path: readonly Point[], unit: number) {
  const a = path[0], b = last(path)
  const length = distance(a, b)
  if (length < 24 * unit) return
  const dx = (b.x - a.x) / length, dy = (b.y - a.y) / length
  const tolerance = Math.min(19 * unit, length * .12)
  let walked = 0
  for (let i = 1; i < path.length; i++) {
    const { x, y } = path[i]
    walked += distance(path[i - 1], path[i])
    if (walked > length * 1.21 || Math.abs((x - a.x) * dy - (y - a.y) * dx) > tolerance) return
  }
  return cleanLine([a, b], unit)
}

function fitShaft(path: readonly Point[], unit: number) {
  const tolerance = Math.min(9 * unit, Math.max(3 * unit, distance(path[0], last(path)) * .055))
  return cleanLine(simplify(path, tolerance), unit) ?? straightenWavyLine(path, unit)
}

function shaftPoints(path: readonly Point[], points: Point[]) {
  return [path[0], ...points.slice(1, -1), last(path)]
}

function arrowLine(points: Point[], traced: Point[], start: boolean, end: boolean): SketchLine {
  if (start && !end) return { kind: 'line', arrow: true, points: [...points].reverse(), traced: [...traced].reverse() }
  return { kind: 'line', arrow: start || end, points, traced, ...(start && end ? { startArrow: true } : {}) }
}

function headBasis(stem: readonly Point[], at: ArrowEnd, unit: number) {
  const end = at === 'end' ? last(stem) : stem[0]
  const ordered = at === 'end' ? [...stem].reverse() : stem
  const base = ordered.find(point => distance(point, end) >= 5 * unit)
  if (!base) return
  const length = distance(base, end)
  return { end, dx: (end.x - base.x) / length, dy: (end.y - base.y) / length }
}

type Direction = { dx: number; dy: number }
function offset(point: Point, tip: Point, { dx, dy }: Direction) {
  return { along: (point.x - tip.x) * dx + (point.y - tip.y) * dy, across: (point.y - tip.y) * dx - (point.x - tip.x) * dy }
}

function wingEvidence(
  paths: SketchStrokes, tip: Point, axis: Direction, shaftLength: number, unit: number, continuous: boolean,
) {
  const maxArm = Math.min(88 * unit, shaftLength * .63)
  const points = paths.flat()
  if (points.some(point => {
    const { along, across } = offset(point, tip, axis)
    return along > 4.5 * unit || along < -maxArm || Math.abs(across) > maxArm
  })) return 0
  let left = false, right = false, foldedBack = false
  const wings = continuous ? points : paths.flatMap(path => [path[0], last(path)])
  for (const point of wings) {
    const { along, across } = offset(point, tip, axis)
    const back = -along
    if (back < 3 * unit) continue
    const width = Math.max(3.3 * unit, back * .10)
    if (across >= width) left = true
    if (across <= -width) right = true
    if (back >= 8 * unit && Math.abs(across) >= Math.max(4.5 * unit, back * .15) && back >= Math.abs(across) * .72) {
      foldedBack = true
    }
  }
  if (left && right) return 2
  return continuous && foldedBack ? 1 : 0
}

export interface SketchArrowTip { at: ArrowEnd; point: Point; distance: number }

export function recognizeArrowTip(
  stem: readonly Point[], strokes: SketchStrokes, unit: number, options: { visible?: boolean; at?: ArrowEnd } = {},
): SketchArrowTip | undefined {
  const length = distance(stem[0], last(stem))
  if (length < 24 * unit) return
  const paths = strokes.map(path => simplify(path, 2.4 * unit))
  let best: SketchArrowTip | undefined
  const ends = options.at ? [options.at] : ['end', 'start'] as const
  for (const at of ends) {
    const axis = headBasis(stem, at, unit)
    if (!axis) continue
    const points = paths.flat()
    const furthest = Math.max(...points.map(point => offset(point, axis.end, axis).along))
    for (const point of points) {
      const { along, across } = offset(point, axis.end, axis)
      const gap = distance(point, axis.end)
      if (along < furthest - 4.5 * unit || along < -22 * unit || along > 37 * unit || Math.abs(across) > 28 * unit) continue
      if (options.visible && gap > 17 * unit || best && gap >= best.distance) continue
      if (!paths.every(path => path.some(sample => distance(sample, point) <= 9 * unit))) continue
      if (wingEvidence(paths, point, axis, length, unit, false)) best = { at, point, distance: gap }
    }
  }
  return best
}

function recognizeContinuousArrow(path: readonly Point[], unit: number): SketchLine | undefined {
  const bounds = sketchBounds([path])
  const extent = Math.hypot(bounds.width, bounds.height)
  const vertices = simplify(path, 2.5 * unit)
  if (vertices.length < 3 || vertices.length > 30 || distance(path[0], last(path)) < extent * .28) return
  let best: { line: SketchLine; score: number } | undefined
  // Everything before or after the shaft must form a head at the corresponding tip.
  for (let start = 0; start < Math.min(9, vertices.length - 1); start++) {
    for (let end = Math.max(start + 1, vertices.length - 9); end < vertices.length; end++) {
      const hasStart = start > 0, hasEnd = end < vertices.length - 1
      if (!hasStart && !hasEnd) continue
      const length = distance(vertices[start], vertices[end])
      if (length < Math.max(27 * unit, extent * .58)) continue
      const shaft = vertices.slice(start, end + 1)
      const clean = fitShaft(shaft, unit)
      if (!clean) continue
      const traced = shaftPoints(shaft, clean)
      const headAt = (at: ArrowEnd, points: Point[]) => {
        const basis = headBasis(traced, at, unit)
        return basis ? wingEvidence([points], basis.end, basis, length, unit, true) : 0
      }
      const startWings = hasStart ? headAt('start', vertices.slice(0, start + 1)) : 0
      const endWings = hasEnd ? headAt('end', vertices.slice(end)) : 0
      if (hasStart && !startWings || hasEnd && !endWings) continue
      const score = length / extent + .23 * (startWings + endWings) + (hasStart && hasEnd ? .21 : 0)
      if (!best || score > best.score) best = { score, line: arrowLine(clean, traced, hasStart, hasEnd) }
    }
  }
  return best?.line
}

function recognizeSeparateArrow(strokes: SketchStrokes, unit: number) {
  for (let index = 0; index < strokes.length; index++) {
    const shaft = strokes[index]
    const points = fitShaft(shaft, unit)
    if (!points) continue
    const traced = shaftPoints(shaft, points)
    const heads = strokes.filter((_, i) => i !== index)
    const tip = recognizeArrowTip(traced, heads, unit)
    if (tip) return arrowLine(points, traced, tip.at === 'start', tip.at === 'end')
  }
}

export function recognizeSketch(strokes: SketchStrokes, unit: number): SketchShape | undefined {
  if (!strokes.length) return
  const outline = recognizeOutline(strokes, unit)
  if (outline) return outline
  if (strokes.length > 1) return recognizeSeparateArrow(strokes, unit)

  const path = strokes[0]
  const arrow = recognizeContinuousArrow(path, unit)
  if (arrow) return arrow
  const points = fitShaft(path, unit)
  if (points) return arrowLine(points, shaftPoints(path, points), false, false)
}
