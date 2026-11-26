import type { Point, Size } from '@/utils/canvasViewport'

export type SketchStrokes = readonly (readonly Point[])[]
export interface SketchTiming { startedAt: number; endedAt: number }

export const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y)
export const last = (points: readonly Point[]) => points[points.length - 1]

export function sketchBounds(strokes: SketchStrokes): Point & Size {
  let x = Infinity, y = Infinity, right = -Infinity, bottom = -Infinity
  for (const path of strokes) {
    for (const point of path) {
      x = Math.min(x, point.x)
      y = Math.min(y, point.y)
      right = Math.max(right, point.x)
      bottom = Math.max(bottom, point.y)
    }
  }
  return { x, y, width: right - x, height: bottom - y }
}

export function resampleStroke(points: readonly Point[], count: number): Point[] {
  const lengths = [0]
  for (let i = 1; i < points.length; i++) lengths.push(lengths[i - 1] + distance(points[i - 1], points[i]))
  const total = lengths[lengths.length - 1]
  if (!total) return [...points]
  const sampled = [points[0]]
  let segment = 1
  for (let step = 1; step < count - 1; step++) {
    const length = total * step / (count - 1)
    while (length > lengths[segment]) segment++
    const ratio = (length - lengths[segment - 1]) / (lengths[segment] - lengths[segment - 1])
    const a = points[segment - 1], b = points[segment]
    sampled.push({ x: a.x + (b.x - a.x) * ratio, y: a.y + (b.y - a.y) * ratio })
  }
  return [...sampled, last(points)]
}

export function simplify(points: readonly Point[], tolerance: number): Point[] {
  const a = points[0], b = last(points)
  const dx = b.x - a.x, dy = b.y - a.y
  const lengthSquared = dx ** 2 + dy ** 2
  let furthest = tolerance, index = 0
  for (let i = 1; i < points.length - 1; i++) {
    const p = points[i]
    const projection = lengthSquared ? ((p.x - a.x) * dx + (p.y - a.y) * dy) / lengthSquared : 0
    const t = Math.max(0, Math.min(1, projection))
    const error = Math.hypot(p.x - a.x - dx * t, p.y - a.y - dy * t)
    if (error > furthest) {
      furthest = error
      index = i
    }
  }
  if (!index) return [a, b]
  return [...simplify(points.slice(0, index + 1), tolerance).slice(0, -1), ...simplify(points.slice(index), tolerance)]
}
