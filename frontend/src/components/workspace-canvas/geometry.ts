import type { CanvasNode, CanvasRegion, Point, Size } from './model'

export interface Viewport extends Point { scale: number }

export const minimumZoom = 0.0125
export const zoomScale = (value: number) => Math.min(2.5, Math.max(minimumZoom, value))
export const center = (position: Point, size: Size): Point => ({
  x: position.x + size.width / 2,
  y: position.y + size.height / 2,
})

export function zoomAround(viewport: Viewport, point: Point, newScale: number): Viewport {
  const scale = zoomScale(newScale)
  const ratio = scale / viewport.scale
  return { scale, x: point.x + (viewport.x - point.x) * ratio, y: point.y + (viewport.y - point.y) * ratio }
}

export function fittedViewport(nodes: Pick<CanvasNode, 'position' | 'size'>[], surface: Size): Viewport {
  if (!nodes.length) return { x: 0, y: 0, scale: 1 }
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity
  for (const { position, size } of nodes) {
    left = Math.min(left, position.x)
    top = Math.min(top, position.y)
    right = Math.max(right, position.x + size.width)
    bottom = Math.max(bottom, position.y + size.height)
  }
  const padding = surface.width < 550 ? 96 : 156
  const controlOffset = surface.width < 900 ? 25 : 0
  const scale = zoomScale(Math.min(1, (surface.width - padding) / (right - left), (surface.height - padding) / (bottom - top)))
  return {
    scale,
    x: surface.width / 2 - (left + right) * scale / 2,
    y: surface.height / 2 - (top + bottom) * scale / 2 - controlOffset,
  }
}

export function frameMembers(frame: CanvasNode, nodes: CanvasNode[]) {
  const frames = nodes.filter(node => node.kind === 'frame' && node.scope_id === frame.scope_id).sort((first, second) => (
    first.size.width * first.size.height - second.size.width * second.size.height || (first.id < second.id ? -1 : 1)
  ))
  return nodes.filter(node => {
    if (node.kind === 'frame' || node.scope_id !== frame.scope_id) return false
    const point = center(node.position, node.size)
    const closest = frames.find(({ position, size }) => point.x >= position.x && point.y >= position.y
      && point.x <= position.x + size.width && point.y <= position.y + size.height)
    return closest?.id === frame.id
  })
}

export function arrowGeometry(source: CanvasNode, target: CanvasNode, offset = 0, business = false, guideY?: number) {
  const from = center(source.position, source.size)
  const to = center(target.position, target.size)
  const dx = Math.abs(to.x - from.x), dy = Math.abs(to.y - from.y)
  const separatedColumns = dx > (source.size.width + target.size.width) / 2 + 20
  if (guideY !== undefined && dx > (source.size.width + target.size.width) / 2 + 180) {
    const direction = to.x > from.x ? 1 : -1
    from.x += direction * (source.size.width / 2 + 2)
    to.x -= direction * (target.size.width / 2 + 8)
    from.y += offset
    to.y += offset
    const fromLane = from.x + direction * 24
    const toLane = to.x - direction * 26
    return { path: `M ${from.x} ${from.y} H ${fromLane} V ${guideY} H ${toLane} V ${to.y} H ${to.x}`,
      label: { x: (fromLane + toLane) / 2, y: guideY } }
  }
  if (business && !separatedColumns && dy > Math.max(source.size.height, target.size.height) * 1.5) {
    const left = Math.min(source.position.x, target.position.x) - 44 - Math.abs(offset)
    from.x = source.position.x - 2
    to.x = target.position.x - 8
    from.y += offset
    to.y += offset
    return { path: `M ${from.x} ${from.y} C ${left} ${from.y} ${left} ${to.y} ${to.x} ${to.y}`,
      label: { x: (from.x + to.x + 6 * left) / 8, y: (from.y + to.y) / 2 } }
  }
  const horizontal = dx >= dy || (business && separatedColumns)
  const axis = horizontal ? 'x' : 'y'
  const across = horizontal ? 'y' : 'x'
  const dimension = horizontal ? 'width' : 'height'
  const direction = to[axis] >= from[axis] ? 1 : -1
  from[axis] += direction * (source.size[dimension] / 2 + 2)
  to[axis] -= direction * (target.size[dimension] / 2 + 8)
  from[across] += offset
  to[across] += offset
  const extension = Math.max(38, Math.min(140, Math.abs(to[axis] - from[axis]) * 0.54))
  const controlFrom = { ...from, [axis]: from[axis] + direction * extension }
  const controlTo = { ...to, [axis]: to[axis] - direction * extension }
  const path = `M ${from.x} ${from.y} C ${controlFrom.x} ${controlFrom.y} ${controlTo.x} ${controlTo.y} ${to.x} ${to.y}`
  return { path, label: { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 } }
}

export function crossDomainGeometry(source: CanvasNode, target: CanvasNode, sourceRegion: CanvasRegion,
  targetRegion: CanvasRegion, offset: number, rowLane = 0) {
  const [top, bottom] = sourceRegion.position.y < targetRegion.position.y ? [sourceRegion, targetRegion] : [targetRegion, sourceRegion]
  const gap = bottom.position.y - top.position.y - top.size.height
  if (gap < 24) {
    const guide = Math.min(sourceRegion.position.y, targetRegion.position.y) + 64 + offset + rowLane
    return arrowGeometry(source, target, offset + rowLane / 2, true, guide)
  }
  const from = center(source.position, source.size), to = center(target.position, target.size)
  const direction = to.x >= from.x ? 1 : -1
  const sourceX = from.x + direction * (source.size.width / 2 + 2)
  const targetX = to.x - direction * (target.size.width / 2 + 8)
  const sourceLane = sourceX + direction * 22
  const targetLane = targetX - direction * 22
  const laneY = bottom.position.y - Math.min(25, gap / 2)
  return { path: `M ${sourceX} ${from.y + offset} H ${sourceLane} V ${laneY} H ${targetLane} V ${to.y + offset} H ${targetX}`,
    label: { x: (sourceLane + targetLane) / 2, y: laneY } }
}

export function branchArrowGeometry(source: CanvasNode, target: CanvasNode, port: number) {
  const from = center(source.position, source.size), to = center(target.position, target.size)
  const direction = from.x >= to.x ? 1 : -1
  from.x -= direction * (source.size.width / 2 + 2)
  to.x += direction * (target.size.width / 2 + 8)
  to.y += port
  const lane = to.x + direction * Math.min(34, Math.abs(from.x - to.x) / 2)
  return { path: `M ${from.x} ${from.y} H ${lane} V ${to.y} H ${to.x}`,
    label: { x: (from.x + lane) / 2, y: from.y } }
}
