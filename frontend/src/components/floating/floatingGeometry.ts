import type { FloatPoint, FloatSize } from '@/types/taskFloat'

export function fitFloatingPosition(position: FloatPoint, size: FloatSize, viewport: FloatSize): FloatPoint {
  return {
    x: Math.max(10, Math.min(viewport.width - size.width - 10, position.x)),
    y: Math.max(10, Math.min(viewport.height - size.height - 10, position.y)),
  }
}
