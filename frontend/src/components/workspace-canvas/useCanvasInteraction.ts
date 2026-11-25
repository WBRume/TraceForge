import { computed, onMounted, onScopeDispose, shallowRef, watch, type ShallowRef } from 'vue'
import { center, fittedViewport, frameMembers, zoomAround, type Viewport } from './geometry'
import { nodeSizes, type CanvasConnection, type CanvasNode, type CanvasRegion, type CanvasSelection, type CanvasTool, type NodePatch, type Point, type Size } from './model'

interface InteractionOptions {
  surface: Readonly<ShallowRef<HTMLElement | null>>
  nodes: () => CanvasNode[]
  regions: () => CanvasRegion[]
  featured?: () => boolean
  tool: () => CanvasTool
  busy: () => boolean
  select: (selection: CanvasSelection | null) => void
  create: (kind: 'note' | 'frame', position: Point, size?: Size) => void
  update: (nodeId: string, patch: NodePatch) => void
  connect: (source: string, target: string, mode: CanvasConnection) => void
}

interface PointerStart { id: number; screen: Point; world: Point }
type Gesture = PointerStart & (
  | { mode: 'pan'; viewport: Viewport }
  | { mode: 'move'; node: CanvasNode; members: Set<string> }
  | { mode: 'size'; node: CanvasNode }
  | { mode: 'frame' }
  | { mode: 'connect'; node: CanvasNode; connection: CanvasConnection }
)

const difference = (first: Point, second: Point): Point => ({ x: first.x - second.x, y: first.y - second.y })
const offset = (point: Point, delta: Point): Point => ({ x: point.x + delta.x, y: point.y + delta.y })
const bounds = (first: Point, second: Point) => ({
  position: { x: Math.min(first.x, second.x), y: Math.min(first.y, second.y) },
  size: { width: Math.abs(second.x - first.x), height: Math.abs(second.y - first.y) },
})

export function useCanvasInteraction(options: InteractionOptions) {
  const viewport = shallowRef<Viewport>({ x: 0, y: 0, scale: 1 })
  const gesture = shallowRef<Gesture | null>(null)
  const pointer = shallowRef<Point | null>(null)
  const moving = shallowRef(false)
  const space = shallowRef(false)
  const connectStart = shallowRef<{ id: string; connection: CanvasConnection } | null>(null)
  const hoveredTarget = shallowRef('')
  const pendingPlacement = shallowRef<Map<string, Pick<CanvasNode, 'position' | 'size'>> | null>(null)
  watch(options.busy, busy => { if (!busy) pendingPlacement.value = null })

  function size(): Size {
    return { width: options.surface.value?.clientWidth || 0, height: options.surface.value?.clientHeight || 0 }
  }

  function localPoint(event: MouseEvent): Point {
    const rect = options.surface.value?.getBoundingClientRect()
    return { x: event.clientX - (rect?.left || 0), y: event.clientY - (rect?.top || 0) }
  }

  function worldPoint(screen: Point): Point {
    const { x, y, scale } = viewport.value
    return { x: (screen.x - x) / scale, y: (screen.y - y) / scale }
  }

  function startPointer(event: PointerEvent): PointerStart {
    const screen = localPoint(event)
    return { id: event.pointerId, screen, world: worldPoint(screen) }
  }

  function startPan(event: PointerEvent) {
    gesture.value = { ...startPointer(event), mode: 'pan', viewport: viewport.value }
  }

  function pointerDown(event: PointerEvent) {
    if (gesture.value || (event.button !== 0 && event.button !== 1)) return
    if (options.busy() || event.button === 1 || space.value || options.tool() === 'pan') {
      startPan(event)
      return
    }
    options.select(null)
    connectStart.value = null
    if (options.tool() === 'frame') gesture.value = { ...startPointer(event), mode: 'frame' }
    else if (options.tool() === 'note') options.create('note', worldPoint(localPoint(event)))
    else startPan(event)
  }

  function nodeDown(event: PointerEvent, node: CanvasNode, handle?: 'resize' | 'connect') {
    if (gesture.value || (event.button !== 0 && event.button !== 1)) return
    if (event.button === 1 || space.value || options.tool() === 'pan') {
      startPan(event)
      return
    }
    if (options.busy()) return
    const start = startPointer(event)
    options.select({ type: 'node', id: node.id })
    if (handle === 'connect' || options.tool() === 'arrow' || options.tool() === 'relation') {
      const connection = options.tool() === 'relation' ? 'relation' : options.tool() === 'arrow' ? 'arrow' : 'auto'
      gesture.value = { ...start, mode: 'connect', node, connection }
    } else if (handle === 'resize') {
      gesture.value = { ...start, mode: 'size', node }
    } else {
      const members = node.kind === 'frame' ? frameMembers(node, options.nodes()).map(item => item.id) : []
      gesture.value = { ...start, mode: 'move', node, members: new Set(members) }
    }
  }

  function targetAt(event: PointerEvent) {
    const target = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>('[data-canvas-node]')
    return target && options.surface.value?.contains(target) ? target.dataset.canvasNode || '' : ''
  }

  function pointerMove(event: PointerEvent) {
    const current = gesture.value
    if (!current) {
      if (connectStart.value) pointer.value = worldPoint(localPoint(event))
      return
    }
    if (current.id !== event.pointerId) return
    const screen = localPoint(event)
    const delta = difference(screen, current.screen)
    if (!moving.value && Math.hypot(delta.x, delta.y) < 4) return
    if (!moving.value) {
      moving.value = true
      options.surface.value?.setPointerCapture(event.pointerId)
    }
    if (current.mode === 'pan') {
      viewport.value = { ...offset(current.viewport, delta), scale: current.viewport.scale }
      return
    }
    pointer.value = worldPoint(screen)
    if (current.mode === 'connect') hoveredTarget.value = targetAt(event)
  }

  const delta = computed(() => gesture.value && pointer.value ? difference(pointer.value, gesture.value.world) : null)

  function resized(node: CanvasNode, change: Point): Size {
    return { width: Math.min(20_000, Math.max(180, Math.round(node.size.width + change.x))),
      height: Math.min(20_000, Math.max(124, Math.round(node.size.height + change.y))) }
  }

  function finishConnect(event: PointerEvent, current: Gesture & { mode: 'connect' }) {
    const anchored = connectStart.value
    const source = moving.value ? current.node.id : anchored?.id
    const target = moving.value ? targetAt(event) : current.node.id
    if (source && target && source !== target && (moving.value || anchored?.connection === current.connection)) {
      connectStart.value = null
      options.connect(source, target, current.connection)
    } else if (!moving.value) {
      connectStart.value = { id: current.node.id, connection: current.connection }
      pointer.value = worldPoint(localPoint(event))
    } else connectStart.value = null
  }

  function pointerUp(event: PointerEvent) {
    const current = gesture.value
    if (!current || current.id !== event.pointerId) return
    if (current.mode === 'frame') {
      const area = bounds(current.world, worldPoint(localPoint(event)))
      options.create('frame', moving.value ? area.position : current.world, area.size.width > 80 && area.size.height > 72
        ? { width: Math.min(20_000, area.size.width), height: Math.min(20_000, area.size.height) } : undefined)
    } else if (current.mode === 'connect') {
      finishConnect(event, current)
    } else if (moving.value && delta.value && (current.mode === 'move' || current.mode === 'size')) {
      const patch = current.mode === 'move' ? { position: offset(current.node.position, delta.value) }
        : { size: resized(current.node, delta.value) }
      pendingPlacement.value = new Map(renderedNodes.value
        .filter(node => node.id === current.node.id || (current.mode === 'move' && current.members.has(node.id)))
        .map(node => [node.id, { position: node.position, size: node.size }]))
      options.update(current.node.id, patch)
    }
    cancelGesture()
  }

  function cancelGesture() {
    gesture.value = null
    moving.value = false
    hoveredTarget.value = ''
    if (!connectStart.value) pointer.value = null
  }

  function cancelConnection() {
    connectStart.value = null
    cancelGesture()
  }

  const renderedNodes = computed(() => {
    const current = gesture.value
    const shift = delta.value
    if (!current || !shift || !moving.value) {
      const pending = pendingPlacement.value
      return pending ? options.nodes().map(node => pending.has(node.id) ? { ...node, ...pending.get(node.id)! } : node) : options.nodes()
    }
    if (current.mode === 'size') return options.nodes().map(node => node.id === current.node.id
      ? { ...node, size: resized(current.node, shift) } : node)
    if (current.mode !== 'move') return options.nodes()
    return options.nodes().map(node => node.id === current.node.id || current.members.has(node.id)
      ? { ...node, position: offset(node.position, shift) } : node)
  })

  const framePreview = computed(() => gesture.value?.mode === 'frame' && pointer.value
    ? bounds(gesture.value.world, pointer.value) : null)

  const connectionPreview = computed(() => {
    const current = gesture.value
    const sourceId = current?.mode === 'connect' ? current.node.id : connectStart.value?.id
    const source = options.nodes().find(node => node.id === sourceId)
    return source && pointer.value ? { source: center(source.position, source.size), target: pointer.value } : null
  })

  function adjustZoom(factor: number) {
    const { width, height } = size()
    viewport.value = zoomAround(viewport.value, { x: width / 2, y: height / 2 }, viewport.value.scale * factor)
  }

  function wheel(event: WheelEvent) {
    if (gesture.value) return
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? size().height : 1
    if (event.ctrlKey || event.metaKey) {
      viewport.value = zoomAround(viewport.value, localPoint(event), viewport.value.scale * Math.exp(-event.deltaY * unit * 0.003))
    } else {
      const { x, y, scale } = viewport.value
      viewport.value = { x: x - event.deltaX * unit, y: y - event.deltaY * unit, scale }
    }
  }

  function fit(includeAnnotations = false) {
    const regions = options.regions()
    const nodes = options.nodes()
    const featured = options.featured?.() && regions.length && !includeAnnotations
    viewport.value = fittedViewport([...regions, ...(featured ? nodes.filter(node => node.automatic) : nodes)], size())
  }

  function focusRegion(region: CanvasRegion) { viewport.value = fittedViewport([region], size()) }

  function focusNodes(ids: string[]) {
    const wanted = new Set(ids)
    const nodes = options.nodes().filter(node => wanted.has(node.id))
    if (nodes.length) viewport.value = fittedViewport(nodes, size())
  }

  function insertionPoint(kind: CanvasNode['kind']): Point {
    const { width, height } = size()
    const midpoint = worldPoint({ x: width / 2, y: height / 2 })
    const position = { x: midpoint.x - nodeSizes[kind].width / 2, y: midpoint.y - nodeSizes[kind].height / 2 }
    for (let index = 0; index <= options.nodes().length; index++) {
      if (!options.nodes().some(node => Math.hypot(node.position.x - position.x, node.position.y - position.y) < 26)) break
      position.x += 32
      position.y += 26
    }
    return position
  }

  const clearSpace = () => { space.value = false }
  onMounted(() => {
    fit()
    window.addEventListener('blur', clearSpace)
    window.addEventListener('keyup', clearSpaceOnKey)
    window.addEventListener('pointerup', pointerUp)
  })
  function clearSpaceOnKey(event: KeyboardEvent) { if (event.code === 'Space') clearSpace() }
  onScopeDispose(() => {
    window.removeEventListener('blur', clearSpace)
    window.removeEventListener('keyup', clearSpaceOnKey)
    window.removeEventListener('pointerup', pointerUp)
  })

  return { viewport, gesture, moving, space, connectStart, hoveredTarget, renderedNodes, framePreview, connectionPreview,
    pointerDown, nodeDown, pointerMove, cancelGesture, cancelConnection, adjustZoom, wheel, fit, focusNodes, focusRegion, insertionPoint }
}
