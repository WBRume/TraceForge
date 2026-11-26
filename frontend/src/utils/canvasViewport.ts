export interface Point { x: number; y: number }
export interface Size { width: number; height: number }
export interface Viewport extends Point { scale: number }
export interface CanvasBounds { left: number; top: number; right: number; bottom: number }

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

export function fittedViewport(nodes: { position: Point; size: Size }[], surface: Size, options?: { padding: number; verticalOffset: number }): Viewport {
  if (!nodes.length) return { x: 0, y: 0, scale: 1 }
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity
  for (const { position, size } of nodes) {
    left = Math.min(left, position.x)
    top = Math.min(top, position.y)
    right = Math.max(right, position.x + size.width)
    bottom = Math.max(bottom, position.y + size.height)
  }
  const padding = options?.padding ?? (surface.width < 550 ? 96 : 156)
  const controlOffset = options?.verticalOffset ?? (surface.width < 900 ? 25 : 0)
  const scale = zoomScale(Math.min(1, (surface.width - padding) / (right - left), (surface.height - padding) / (bottom - top)))
  return {
    scale,
    x: surface.width / 2 - (left + right) * scale / 2,
    y: surface.height / 2 - (top + bottom) * scale / 2 - controlOffset,
  }
}
