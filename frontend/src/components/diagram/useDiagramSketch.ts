import { onScopeDispose, shallowRef } from 'vue'
import type { Point } from '@/utils/canvasViewport'
import { MAX_SKETCH_POINTS } from './diagramModel'
import { resampleStroke, type SketchStrokes, type SketchTiming } from './diagramSketchGeometry'

const maxSamples = MAX_SKETCH_POINTS * 3

export function useDiagramSketch(commit: (strokes: SketchStrokes, unit: number, timing: SketchTiming) => void) {
  const ink = shallowRef<readonly Point[]>([])
  let active: Point[] | undefined
  let unit = 1
  let startedAt = 0
  let frame: number | undefined

  function paint() {
    if (frame !== undefined) return
    frame = requestAnimationFrame(() => {
      frame = undefined
      ink.value = active ? [...active] : []
    })
  }

  function cancelActive() {
    if (frame !== undefined) cancelAnimationFrame(frame)
    frame = undefined
    active = undefined
    ink.value = []
  }

  function begin(point: Point, newUnit: number) {
    unit = newUnit
    startedAt = performance.now()
    active = [point]
    paint()
  }

  function add(point: Point) {
    if (!active) return
    const last = active[active.length - 1]
    if (Math.hypot(point.x - last.x, point.y - last.y) < unit * .75) return
    active.push(point)
    if (active.length >= maxSamples) active = resampleStroke(active, maxSamples / 2)
    paint()
  }

  function finish(point: Point) {
    add(point)
    const path = active
    cancelActive()
    if (path && path.length > 1) commit([path], unit, { startedAt, endedAt: performance.now() })
  }

  onScopeDispose(cancelActive)
  return { ink, begin, add, finish, cancelActive }
}
