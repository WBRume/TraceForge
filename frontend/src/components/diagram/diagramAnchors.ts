import type { Point } from '@/utils/canvasViewport'
import { anchorSides, isContainer, isStroke, triangleCorners, type DiagramAnchor, type DiagramNode } from './diagramModel'

type Side = DiagramAnchor['side']
const normals: Record<Side, Point> = {
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
  top: { x: 0, y: -1 },
  bottom: { x: 0, y: 1 },
}

function anchorPoint(node: DiagramNode, anchor: DiagramAnchor): Point {
  const { x, y, width, height, shape } = node
  const { side, position } = anchor
  const normal = normals[side]
  if (shape === 'triangle') {
    const axis = normal.x ? 'x' : 'y'
    const across = normal.x ? 'y' : 'x'
    const corners = triangleCorners(1, 1, node.direction)
    const intersections = corners.flatMap((a, index) => {
      const b = corners[(index + 1) % corners.length]
      const distance = b[across] - a[across]
      if (!distance) return position === a[across] ? [a[axis], b[axis]] : []
      const ratio = (position - a[across]) / distance
      return ratio >= 0 && ratio <= 1 ? [a[axis] + (b[axis] - a[axis]) * ratio] : []
    })
    const depth = normal[axis] > 0 ? Math.max(...intersections) : Math.min(...intersections)
    return normal.x ? { x: x + width * depth, y: y + height * position }
      : { x: x + width * position, y: y + height * depth }
  }
  const alongSide = position * 2 - 1
  let radius = 1
  if (shape === 'oval' || shape === 'usecase' || shape === 'initial' || shape === 'final') {
    radius = Math.sqrt(Math.max(0, 1 - alongSide ** 2))
  } else if (shape === 'diamond' || shape === 'decision') {
    radius = 1 - Math.abs(alongSide)
  }
  return normal.x
    ? { x: x + width * (1 + normal.x * radius) / 2, y: y + height * position }
    : { x: x + width * position, y: y + height * (1 + normal.y * radius) / 2 }
}

export function nearestAnchor(node: DiagramNode, point: Point) {
  return anchorSides.map(side => {
    const ratio = normals[side].x ? (point.y - node.y) / node.height : (point.x - node.x) / node.width
    const position = Math.min(.96, Math.max(.04, ratio))
    const anchor = { side, position }
    const at = anchorPoint(node, anchor)
    return { anchor, distance: Math.hypot(at.x - point.x, at.y - point.y) }
  }).reduce((best, option) => option.distance < best.distance ? option : best)
}

export function containsDiagramPoint(node: DiagramNode, point: Point) {
  const position = (point.y - node.y) / node.height
  if (position < 0 || position > 1 || point.x < node.x || point.x > node.x + node.width) return false
  return point.x >= anchorPoint(node, { side: 'left', position }).x
    && point.x <= anchorPoint(node, { side: 'right', position }).x
}

function firstBorderCrossing(node: DiagramNode, path: readonly Point[], reach: number) {
  let walked = 0
  for (let i = 1; i < path.length && walked < reach; i++) {
    const from = path[i - 1], to = path[i]
    const length = Math.hypot(to.x - from.x, to.y - from.y)
    if (!containsDiagramPoint(node, to)) {
      let inside = 0, outside = 1
      const at = (t: number) => ({ x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t })
      for (let step = 0; step < 12; step++) {
        const middle = (inside + outside) / 2
        if (containsDiagramPoint(node, at(middle))) inside = middle
        else outside = middle
      }
      const distance = walked + length * inside
      if (distance <= reach) return { point: at(inside), distance }
      return
    }
    walked += length
  }
}

export function sketchAttachment(nodes: readonly DiagramNode[], path: readonly Point[], unit: number) {
  const [start, next] = path
  const strokeLength = path.reduce((length, point, i) => i
    ? length + Math.hypot(point.x - path[i - 1].x, point.y - path[i - 1].y) : length, 0)
  const direction = delta(start, next)
  const directionLength = Math.hypot(direction.x, direction.y)
  let best: { node: DiagramNode; anchor: DiagramAnchor; score: number } | undefined
  for (const node of nodes) {
    if (isStroke(node.shape)) continue
    const tolerance = 18 * unit
    if (start.x < node.x - tolerance || start.x > node.x + node.width + tolerance
      || start.y < node.y - tolerance || start.y > node.y + node.height + tolerance) continue
    const container = isContainer(node.shape)
    let match: { anchor: DiagramAnchor; score: number } | undefined
    if (containsDiagramPoint(node, start)) {
      const reach = Math.max(20 * unit, Math.min(110 * unit, strokeLength * .38))
      const crossing = firstBorderCrossing(node, path, reach)
      if (crossing) match = { anchor: nearestAnchor(node, crossing.point).anchor, score: crossing.distance * .18 + (container ? 7 * unit : -12 * unit) }
    }
    if (!match) {
      const near = nearestAnchor(node, start)
      const facesStroke = dot(direction, normals[near.anchor.side]) > directionLength * .08
      if (near.distance <= (facesStroke ? 18 : 4) * unit) match = { anchor: near.anchor, score: near.distance + (container ? 4 * unit : 0) }
    }
    if (match && (!best || match.score < best.score)) best = { node, ...match }
  }
  return best
}

function via(point: Point, normal: Point, length: number): Point {
  return { x: point.x + normal.x * length, y: point.y + normal.y * length }
}

const dot = (a: Point, b: Point) => a.x * b.x + a.y * b.y
const delta = (a: Point, b: Point) => ({ x: b.x - a.x, y: b.y - a.y })

function cutsThrough(a: Point, b: Point, node: DiagramNode) {
  const x = node.x + .1, y = node.y + .1
  const right = node.x + node.width - .1, bottom = node.y + node.height - .1
  if (a.x === b.x) return a.x > x && a.x < right && Math.max(a.y, b.y) > y && Math.min(a.y, b.y) < bottom
  return a.y > y && a.y < bottom && Math.max(a.x, b.x) > x && Math.min(a.x, b.x) < right
}

export function anchoredPoints(
  source: DiagramNode, target: DiagramNode, anchors: [DiagramAnchor, DiagramAnchor], straight: boolean,
) {
  const from = anchorPoint(source, anchors[0]), to = anchorPoint(target, anchors[1])
  const out = normals[anchors[0].side], into = normals[anchors[1].side]
  const direction = delta(from, to)
  if (straight && dot(direction, out) > 0 && dot(direction, into) < 0) return [from, to]
  const stub = Math.min(18, Math.max(6, Math.hypot(direction.x, direction.y) / 4))
  const a = via(from, out, stub), b = via(to, into, stub)
  const left = Math.min(a.x, b.x, source.x, target.x) - stub
  const right = Math.max(a.x, b.x, source.x + source.width, target.x + target.width) + stub
  const top = Math.min(a.y, b.y, source.y, target.y) - stub
  const bottom = Math.max(a.y, b.y, source.y + source.height, target.y + target.height) + stub
  const byX = (x: number) => [a, { x, y: a.y }, { x, y: b.y }, b]
  const byY = (y: number) => [a, { x: a.x, y }, { x: b.x, y }, b]
  const paths = [
    [a, { x: b.x, y: a.y }, b],
    [a, { x: a.x, y: b.y }, b],
    byX((a.x + b.x) / 2),
    byY((a.y + b.y) / 2),
    byX(left), byX(right), byY(top), byY(bottom),
  ]
  let best = paths[0], score = Infinity
  for (const path of paths) {
    let cost = path.length
    for (let index = 1; index < path.length; index++) {
      const p = path[index - 1], q = path[index]
      cost += Math.abs(p.x - q.x) + Math.abs(p.y - q.y)
      if (cutsThrough(p, q, source) || cutsThrough(p, q, target)) cost += 1_000_000
    }
    if (cost < score) {
      score = cost
      best = path
    }
  }
  return [from, ...best, to].filter((point, i, points) =>
    !i || point.x !== points[i - 1].x || point.y !== points[i - 1].y)
}
