import type { Point, Size } from '@/utils/canvasViewport'
import { distance, last, resampleStroke, simplify, sketchBounds, type SketchStrokes } from './diagramSketchGeometry'
import type { TriangleDirection } from './diagramModel'

type OutlineKind = { shape: 'rectangle' | 'oval' | 'diamond' } | { shape: 'triangle'; direction: TriangleDirection }
export type SketchOutline = Point & Size & OutlineKind & { kind: 'outline' }
type Segment = { a: Point; b: Point; direction: Point; length: number }
type InkSegment = Segment & { stroke: number }
type Side = InkSegment & { mask: number }
interface StrokeCorners {
  joins: { point: Point; turn: number }[]
  first: number
  last: number
  endGap: number
}

const difference = (a: Point, b: Point): Point => ({ x: a.x - b.x, y: a.y - b.y })
const cross = (a: Point, b: Point) => a.x * b.y - a.y * b.x
const dot = (a: Point, b: Point) => a.x * b.x + a.y * b.y
const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v))

function segment(a: Point, b: Point): Segment {
  const { x, y } = difference(b, a)
  const length = Math.hypot(x, y)
  return { a, b, length, direction: length ? { x: x / length, y: y / length } : { x: 0, y: 0 } }
}

const project = (edge: Segment, point: Point) => dot(difference(point, edge.a), edge.direction)
const lineGap = (edge: Segment, point: Point) => Math.abs(cross(difference(point, edge.a), edge.direction))

function findStrokeCorners(path: readonly Point[], unit: number) {
  const length = path.reduce((sum, point, i) => i ? sum + distance(path[i - 1], point) : sum, 0)
  const samples = resampleStroke(path, Math.min(160, Math.max(5, Math.ceil(length / (3.5 * unit)) + 1)))
  const step = clamp(Math.round(12 * unit * (samples.length - 1) / length), 1, Math.floor((samples.length - 1) / 2))
  const corners: StrokeCorners['joins'] = []
  for (let i = step; i < samples.length - step; i++) {
    const point = samples[i]
    const incoming = difference(point, samples[i - step])
    const outgoing = difference(samples[i + step], point)
    const turn = Math.atan2(Math.abs(cross(incoming, outgoing)), dot(incoming, outgoing))
    if (turn >= .60) corners.push({ point, turn })
  }
  return corners
}

function fittedSides(strokes: SketchStrokes, unit: number) {
  const atoms: InkSegment[] = []
  const spans: Side[] = []
  const corners: StrokeCorners[] = []
  for (const [stroke, path] of strokes.entries()) {
    const box = sketchBounds([path])
    const tolerance = clamp(Math.max(box.width, box.height) * .045, 2.5 * unit, 12 * unit)
    const points = simplify(path, tolerance)
    const pieces = points.slice(1).map((end, i) => segment(points[i], end))
    const masks = pieces.map(part => {
      if (part.length < 4 * unit) return 0
      const mask = 1 << atoms.length
      atoms.push({ ...part, stroke })
      return mask
    })
    if (!masks.some(Boolean) || atoms.length > 18) return
    const segments = masks.filter(Boolean)
    corners.push({ joins: findStrokeCorners(path, unit), first: segments[0], last: segments[segments.length - 1],
      endGap: distance(path[0], last(path)) })

    // Allow a bowed or rounded side to be supported by several consecutive segments.
    for (let start = 0; start < pieces.length; start++) {
      let length = 0, mask = 0
      for (let end = start; end < Math.min(start + 3, pieces.length); end++) {
        length += pieces[end].length
        mask |= masks[end]
        const side = segment(points[start], points[end + 1])
        if (!mask || side.length < 7 * unit || length > side.length * 1.15) continue
        if (points.slice(start + 1, end + 1).some(point => lineGap(side, point) > .14 * side.length + 2 * unit)) continue
        spans.push({ ...side, mask, stroke })
      }
    }
  }
  const sides = spans.sort((a, b) => b.length - a.length).slice(0, 32)
  return { sides, atoms, corners }
}

function joinAtCorner(a: Side, b: Side, unit: number): Point | undefined {
  const denominator = cross(a.direction, b.direction)
  if ((a.mask & b.mask) || Math.abs(denominator) < .29) return
  const offset = difference(b.a, a.a)
  const alongA = cross(offset, b.direction) / denominator
  const alongB = cross(offset, a.direction) / denominator
  const near = (position: number, length: number) => {
    const extension = Math.min(52 * unit, length * .49 + 6 * unit)
    return position >= -extension && position <= length + extension
  }
  if (near(alongA, a.length) && near(alongB, b.length)) {
    return { x: a.a.x + a.direction.x * alongA, y: a.a.y + a.direction.y * alongA }
  }
}

function polygonKind(corners: Point[], sides: Segment[], box: Point & Size, area: number): OutlineKind | undefined {
  if (corners.length === 3) {
    const base = sides.map((side, index) => ({
      index, side, alignment: Math.max(Math.abs(side.direction.x), Math.abs(side.direction.y)),
    })).reduce((a, b) => b.alignment > a.alignment ? b : a)
    const tip = corners[(base.index + 2) % 3]
    if (Math.abs(base.side.direction.x) >= Math.abs(base.side.direction.y)) {
      return { shape: 'triangle', direction: tip.y < (base.side.a.y + base.side.b.y) / 2 ? 'up' : 'down' }
    }
    return { shape: 'triangle', direction: tip.x < (base.side.a.x + base.side.b.x) / 2 ? 'left' : 'right' }
  }
  const coverage = area / (box.width * box.height)
  for (const first of [0, 1]) {
    const horizontal = [sides[first], sides[first + 2]].map(side => Math.abs(side.direction.y))
    const vertical = [sides[(first + 1) % 4], sides[(first + 3) % 4]].map(side => Math.abs(side.direction.x))
    if (coverage >= .56 && Math.max(...horizontal) <= .54 && Math.min(...vertical) <= .48 && Math.max(...vertical) <= .75) {
      return { shape: 'rectangle' }
    }
  }
  const extremes = [
    corners.findIndex(point => point.x === box.x), corners.findIndex(point => point.y === box.y),
    corners.findIndex(point => Math.abs(point.x - box.x - box.width) < .001),
    corners.findIndex(point => Math.abs(point.y - box.y - box.height) < .001),
  ]
  if (coverage >= .31 && coverage <= .74 && new Set(extremes).size === 4) return { shape: 'diamond' }
}

function coveredLength(side: Segment, observed: Segment) {
  const a = project(side, observed.a), b = project(side, observed.b)
  return Math.max(0, Math.min(side.length, Math.max(a, b)) - Math.max(0, Math.min(a, b)))
}

function polygonFit(
  fitted: Side[], corners: Point[], atoms: InkSegment[], strokeCorners: StrokeCorners[], unit: number,
) {
  const box = sketchBounds([corners])
  if (Math.min(box.width, box.height) < Math.max(6, 13 * unit)) return
  const sides = corners.map((corner, index) => segment(corner, corners[(index + 1) % corners.length]))
  const turns = sides.map((side, index) => cross(side.direction, sides[(index + 1) % sides.length].direction))
  if (!(turns.every(turn => turn >= .28) || turns.every(turn => turn <= -.28))) return
  const area = Math.abs(sides.reduce((sum, side) => sum
    + cross(difference(side.a, corners[0]), difference(side.b, corners[0])), 0)) / 2
  const kind = polygonKind(corners, sides, box, area)
  if (!kind) return

  let total = 0, covered = 0, used = 0
  for (const [index, side] of sides.entries()) {
    const ink = fitted[index]
    const overlap = coveredLength(side, ink)
    if (overlap < side.length * .49 || ink.length > side.length * 3.25) return
    total += side.length
    covered += overlap
    used |= ink.mask
  }
  if (covered < total * .69) return

  let roundedCorners = 0
  for (const [i, incoming] of fitted.entries()) {
    const next = (i + 1) % fitted.length
    const outgoing = fitted[next]
    if (incoming.stroke !== outgoing.stroke) continue
    const stroke = strokeCorners[incoming.stroke]
    const meetsEnds = (incoming.mask & stroke.first) && (outgoing.mask & stroke.last)
      || (incoming.mask & stroke.last) && (outgoing.mask & stroke.first)
    if (meetsEnds) {
      const corner = corners[next]
      const withinSide = (side: Side) => {
        const position = project(side, corner)
        const gap = Math.min(32 * unit, Math.min(box.width, box.height) * .26)
        return position >= -gap && position <= side.length + gap
      }
      if (stroke.endGap <= 44 * unit || kind.shape === 'rectangle' && withinSide(incoming) && withinSide(outgoing)) continue
    }
    const margin = clamp(Math.min(sides[i].length, sides[next].length) * .13, 7 * unit, 17 * unit)
    const expected = Math.atan2(Math.abs(turns[i]), dot(sides[i].direction, sides[next].direction))
    if (!stroke.joins.some(join => join.turn >= Math.max(.65, expected * .54)
      && distance(join.point, corners[next]) <= margin)) roundedCorners++
  }
  if (roundedCorners > 1 || (roundedCorners && kind.shape === 'diamond' && strokeCorners.length > 1)) return

  const tolerance = clamp(Math.min(box.width, box.height) * .16, 5 * unit, 16 * unit)
  const observed: number[] = [], matched: number[] = []
  for (const [index, atom] of atoms.entries()) {
    const followsSide = (used & (1 << index)) || sides.some(side =>
      Math.abs(cross(side.direction, atom.direction)) < .46
      && Math.max(lineGap(side, atom.a), lineGap(side, atom.b)) <= tolerance
      && coveredLength(side, atom) >= atom.length * .18)
    observed[atom.stroke] = (observed[atom.stroke] ?? 0) + atom.length
    matched[atom.stroke] = (matched[atom.stroke] ?? 0) + (followsSide ? atom.length : 0)
  }
  if (observed.some((length, index) => matched[index] < length * .65)) return
  const explanation = matched.reduce((sum, length) => sum + length, 0) / observed.reduce((sum, length) => sum + length, 0)
  if (explanation < .83) return
  const outline: SketchOutline = { kind: 'outline', ...kind, ...box }
  return { outline, score: covered / total + explanation }
}

function recognizePolygon(strokes: SketchStrokes, unit: number) {
  const fitted = fittedSides(strokes, unit)
  if (!fitted || fitted.sides.length < 3) return
  const { sides, atoms, corners } = fitted
  const joins = sides.map(side => sides.map(other => joinAtCorner(side, other, unit)))
  const neighbors = joins.map(row => row.flatMap((corner, index) => corner ? [index] : []))
  let best: ReturnType<typeof polygonFit>

  function check(indices: number[]) {
    const outline = indices.map((index, i) => joins[indices.at(i - 1)!][index]!)
    const fit = polygonFit(indices.map(index => sides[index]), outline, atoms, corners, unit)
    if (fit && (!best || fit.score > best.score)) best = fit
  }

  // Corners come from crossing the fitted sides. Stroke order and pen-up gaps are arbitrary.
  for (let a = 0; a < sides.length; a++) {
    for (const b of neighbors[a]) {
      if (b <= a) continue
      for (const c of neighbors[b]) {
        if (c <= a) continue
        if (b < c && joins[c][a]) check([a, b, c])
        if (sides[a].mask & sides[c].mask) continue
        for (const d of neighbors[c]) {
          if (d > b && joins[d][a] && !(sides[b].mask & sides[d].mask)) check([a, b, c, d])
        }
      }
    }
  }
  return best?.outline
}

function straightSide(
  samples: Point[], axis: 'x' | 'y', side: number, span: number, depth: number, fraction: number, unit: number,
) {
  const across = axis === 'x' ? 'y' : 'x'
  const band = depth * .21
  const tolerance = Math.min(depth * .053, span * .072, Math.max(2.4 * unit, depth * .033))
  for (let start = 0; start < samples.length - 2; start++) {
    const a = samples[start]
    if (Math.abs(a[across] - side) > band) continue
    for (let end = start + 2; end < samples.length; end++) {
      const b = samples[end]
      if (Math.abs(samples[end - 1][across] - side) > band || Math.abs(b[across] - side) > band) break
      const run = b[axis] - a[axis]
      const rise = b[across] - a[across]
      if (Math.abs(run) < fraction * span || Math.abs(rise) > Math.min(band * .82, Math.abs(run) * .27)) continue
      if (samples.slice(start + 1, end).every(point => {
        const projected = (point[axis] - a[axis]) / run
        return Math.abs(point[across] - a[across] - projected * rise) <= tolerance
      })) return true
    }
  }
  return false
}

function closesContour(strokes: SketchStrokes, gap: number) {
  const endpoints = strokes.map(path => [path[0], last(path)] as const)
  const [start, end] = endpoints[0]
  const all = (1 << endpoints.length) - 1

  function trace(point: Point, visited: number): boolean {
    if (visited === all) return distance(point, start) <= gap
    for (let i = 1; i < endpoints.length; i++) {
      const bit = 1 << i
      if (visited & bit) continue
      const [a, b] = endpoints[i]
      if (distance(point, a) <= gap && trace(b, visited | bit)
        || distance(point, b) <= gap && trace(a, visited | bit)) return true
    }
    return false
  }

  return trace(end, 1)
}

const strokeLength = (path: readonly Point[]) => path.reduce(
  (total, point, index) => index ? total + distance(path[index - 1], point) : total, 0,
)

function flatSides(strokes: SketchStrokes, box: Point & Size, unit: number) {
  const { x, y, width, height } = box
  const shorter = Math.min(width, height)
  if (shorter < 18 * unit) return
  const gap = Math.min(40 * unit, shorter * .28)
  const closed = closesContour(strokes, gap)
  if (!closed && strokes.length !== 1) return
  const samples = strokes.map(path => resampleStroke(path, 80))
  if (!closed) {
    const [path] = samples
    // The closing edge can meet a side that was extended or retraced at the start.
    const returnsToSide = path.slice(0, 24).some(point => distance(last(path), point) <= gap)
      || path.slice(-24).some(point => distance(path[0], point) <= gap)
    if (!returnsToSide) return
  }
  const horizontal = (y: number) => samples.some(path => straightSide(path, 'x', y, width, height, .54, unit))
  const vertical = (x: number) => samples.some(path => straightSide(path, 'y', x, height, width, .54, unit))
  const top = horizontal(y), bottom = horizontal(y + height), left = vertical(x), right = vertical(x + width)
  const opposing = top && bottom || left && right
  const sides = [top, bottom, left, right].filter(Boolean).length
  const length = strokes.reduce((total, path) => total + strokeLength(path), 0)
  const enoughSides = sides === 4 || closed && sides === 3
  return { opposing, box: enoughSides && length >= (width + height) * 1.56 && length <= (width + height) * 2.33 }
}

function fitOval(strokes: SketchStrokes, bounds: Point & Size, unit: number) {
  const { x, y, width, height } = bounds
  const shorter = Math.min(width, height)
  const closureGap = Math.min(28 * unit, Math.max(5 * unit, shorter * .24))
  if (!closesContour(strokes, closureGap)) return
  const perimeter = Math.PI * (3 * (width + height) - Math.sqrt((3 * width + height) * (width + 3 * height))) / 2
  const angularCoverage = new Set<number>()
  let arc = 0
  let deviation = 0
  for (const path of strokes) {
    const length = strokeLength(path)
    const chord = distance(path[0], last(path))
    if (chord > perimeter * .15 && length < chord * 1.055) return
    arc += length
    let error = 0
    const samples = resampleStroke(path, 48)
    for (const point of samples) {
      const u = 2 * (point.x - x) / width - 1
      const v = 2 * (point.y - y) / height - 1
      const angle = Math.atan2(v, u) + Math.PI
      angularCoverage.add(Math.floor(angle * 8 / Math.PI) % 16)
      error += Math.abs(Math.hypot(u, v) - 1)
    }
    deviation = Math.max(deviation, error / samples.length)
    if (deviation > .19) return
  }
  if (angularCoverage.size >= 13 && arc >= perimeter * .74 && arc <= perimeter * 1.29) {
    const outline: SketchOutline = { kind: 'outline', shape: 'oval', ...bounds }
    return { outline, deviation }
  }
}

export function recognizeOutline(strokes: SketchStrokes, unit: number) {
  if (!strokes.length) return
  const bounds = sketchBounds(strokes)
  if (Math.min(bounds.width, bounds.height) < Math.max(6, 13 * unit)) return
  const sides = flatSides(strokes, bounds, unit)
  const oval = sides?.opposing ? undefined : fitOval(strokes, bounds, unit)
  if (oval && oval.deviation <= .075) return oval.outline
  return recognizePolygon(strokes, unit)
    ?? (sides?.box ? { kind: 'outline', shape: 'rectangle', ...bounds } as const : oval?.outline)
}
