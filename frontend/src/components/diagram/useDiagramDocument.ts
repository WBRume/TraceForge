import { computed, shallowRef, watch } from 'vue'
import { arrangedNodes, inside } from './diagramGeometry'
import { applySketch, type SketchSession } from './diagramSketchDocument'
import type { SketchStrokes, SketchTiming } from './diagramSketchGeometry'
import {
  blankDiagram, decodeDiagram, freshId, isContainer, makeEdge, makeNode, MAX_EDGES, MAX_NODES, minNodeSize,
  type Arrangement, type DiagramDocument, type DiagramNode, type EdgeEdit, type NodeEdit, type Shape,
} from './diagramModel'
import type { Point } from '@/utils/canvasViewport'

const draftKey = 'traceforge.drawing.draft.v1'
const historyLimit = 50
type Selection = { nodes: ReadonlySet<string>; edge: string | null }
const emptySelection = (): Selection => ({ nodes: new Set(), edge: null })

export function useDiagramDocument(untitled: string) {
  function restore() {
    try {
      const raw = localStorage.getItem(draftKey)
      return raw ? decodeDiagram(raw) : blankDiagram(untitled)
    } catch { return blankDiagram(untitled) }
  }

  const doc = shallowRef(restore())
  const savedFile = shallowRef<DiagramDocument>()
  const selection = shallowRef<Selection>(emptySelection())
  const past = shallowRef<DiagramDocument[]>([])
  const future = shallowRef<DiagramDocument[]>([])
  let sketchSession: SketchSession | undefined
  const persisted = shallowRef(true)
  const canUndo = computed(() => past.value.length > 0)
  const canRedo = computed(() => future.value.length > 0)
  const dirty = computed(() => doc.value !== savedFile.value
    && (savedFile.value !== undefined || doc.value.nodes.length > 0 || doc.value.title !== untitled))
  const selectedNodes = computed(() => doc.value.nodes.filter(node => selection.value.nodes.has(node.id)))
  const selectedEdge = computed(() => doc.value.edges.find(edge => edge.id === selection.value.edge) ?? null)

  watch(doc, value => {
    try {
      localStorage.setItem(draftKey, JSON.stringify(value))
      persisted.value = true
    } catch { persisted.value = false }
  }, { flush: 'sync' })

  function endSketchSession() {
    sketchSession = undefined
  }

  function commit(next: DiagramDocument, beforeFormatting?: DiagramDocument) {
    const entries = beforeFormatting ? [doc.value, beforeFormatting] : [doc.value]
    past.value = [...past.value.slice(entries.length - historyLimit), ...entries]
    future.value = []
    endSketchSession()
    doc.value = next
  }

  function replace(next: DiagramDocument, openedFile = false) {
    endSketchSession()
    selection.value = emptySelection()
    past.value = []
    future.value = []
    savedFile.value = openedFile ? next : undefined
    doc.value = next
  }

  function undo() {
    const next = past.value.at(-1)
    if (!next) return
    endSketchSession()
    future.value = [...future.value, doc.value]
    past.value = past.value.slice(0, -1)
    selection.value = emptySelection()
    doc.value = next
  }

  function redo() {
    const next = future.value.at(-1)
    if (!next) return
    endSketchSession()
    past.value = [...past.value, doc.value]
    future.value = future.value.slice(0, -1)
    selection.value = emptySelection()
    doc.value = next
  }

  function selectNodes(ids: Iterable<string>) {
    selection.value = { nodes: new Set(ids), edge: null }
  }

  function selectEdge(id: string) {
    selection.value = { nodes: new Set(), edge: id }
  }

  function rename(value: string) {
    const title = value.trim().slice(0, 120) || untitled
    if (doc.value.title !== title) commit({ ...doc.value, title })
  }

  function addNode(shape: Shape, position: Point, label: string) {
    if (doc.value.nodes.length >= MAX_NODES) return
    const node = makeNode(shape, position, label)
    commit({ ...doc.value, nodes: [...doc.value.nodes, node] })
    selectNodes([node.id])
  }

  function addSketch(strokes: SketchStrokes, unit: number, timing: SketchTiming) {
    const result = applySketch(doc.value, strokes, unit, timing, sketchSession)
    if (!result) return
    commit(result.next, result.original)
    sketchSession = result.session
    selection.value = emptySelection()
  }

  function groupSelection(label: string) {
    const group = selectedNodes.value
    if (!group.length || doc.value.nodes.length >= MAX_NODES) return
    const x = Math.min(...group.map(node => node.x)) - 24
    const y = Math.min(...group.map(node => node.y)) - 44
    const width = Math.max(...group.map(node => node.x + node.width)) - x + 24
    const height = Math.max(...group.map(node => node.y + node.height)) - y + 24
    const frame = { ...makeNode('frame', { x, y }, label), width, height }
    commit({ ...doc.value, nodes: [frame, ...doc.value.nodes] })
    selectNodes([frame.id])
  }

  function addEdge(sourceId: string, targetId: string, y?: number) {
    if (doc.value.edges.length >= MAX_EDGES) return
    const source = doc.value.nodes.find(node => node.id === sourceId)
    const target = doc.value.nodes.find(node => node.id === targetId)
    if (!source || !target || (source === target && isContainer(source.shape))) return
    const sequence = source.shape === 'lifeline' && target.shape === 'lifeline'
    const latestMessage = Math.max(46, ...doc.value.edges.filter(edge => sequence && (edge.source === sourceId || edge.target === sourceId
      || edge.source === targetId || edge.target === targetId)).map(edge => edge.offset ?? 0))
    const top = Math.max(source.y, target.y)
    const edge = makeEdge(source, target, y !== undefined && y - top >= 60 ? y - top : latestMessage + 40)
    const nodes = extendLifelines(source.id, target.id, edge.offset)
    commit({ ...doc.value, nodes, edges: [...doc.value.edges, edge] })
    selectEdge(edge.id)
  }

  function extendLifelines(source: string, target: string, offset?: number) {
    const nodes = doc.value.nodes
    if (offset === undefined) return nodes
    const participants = nodes.filter(node => node.id === source || node.id === target)
    const bottom = Math.max(...participants.map(node => node.y)) + offset + 42
    return nodes.map(node => participants.includes(node) && node.y + node.height < bottom
      ? { ...node, height: bottom - node.y } : node)
  }

  function updateNodes(updates: ReadonlyMap<string, NodeEdit>) {
    if (!updates.size) return
    const nodes = doc.value.nodes.map(node => {
      const patch = updates.get(node.id)
      if (!patch) return node
      const min = minNodeSize(node.shape)
      return {
        ...node, ...patch, width: Math.max(min.width, patch.width ?? node.width), height: Math.max(min.height, patch.height ?? node.height),
      }
    })
    commit({ ...doc.value, nodes })
  }

  function updateNode(patch: NodeEdit) {
    const node = selectedNodes.value.length === 1 ? selectedNodes.value[0] : null
    if (node && Object.entries(patch).some(([key, value]) => node[key as keyof DiagramNode] !== value)) {
      updateNodes(new Map([[node.id, patch]]))
    }
  }

  function updateEdge(patch: EdgeEdit) {
    const active = selectedEdge.value
    if (!active || !Object.entries(patch).some(([key, value]) => active[key as keyof typeof active] !== value)) return
    commit({ ...doc.value, nodes: extendLifelines(active.source, active.target, patch.offset),
      edges: doc.value.edges.map(edge => edge.id === active.id ? { ...edge, ...patch } : edge) })
  }

  function movingIds() {
    const ids = new Set(selection.value.nodes)
    for (const container of selectedNodes.value.filter(node => isContainer(node.shape))) {
      for (const node of doc.value.nodes) if (inside(node, container)) ids.add(node.id)
    }
    return ids
  }

  function nudge(dx: number, dy: number) {
    const ids = movingIds()
    updateNodes(new Map(doc.value.nodes.filter(node => ids.has(node.id))
      .map(node => [node.id, { x: node.x + dx, y: node.y + dy }])))
  }

  function arrange(arrangement: Arrangement) {
    const nodes = arrangedNodes(doc.value, selection.value.nodes, arrangement)
    if (nodes !== doc.value.nodes) commit({ ...doc.value, nodes })
  }

  function remove() {
    const { nodes, edge } = selection.value
    if (!nodes.size && !edge) return
    commit({
      ...doc.value,
      nodes: doc.value.nodes.filter(node => !nodes.has(node.id)),
      edges: doc.value.edges.filter(connection => connection.id !== edge && !nodes.has(connection.source) && !nodes.has(connection.target)),
    })
    selection.value = emptySelection()
  }

  function clearCanvas() {
    if (!doc.value.nodes.length) return
    commit({ ...doc.value, nodes: [], edges: [] })
    selection.value = emptySelection()
  }

  function extractedSelection() {
    const ids = movingIds()
    return { ...doc.value, nodes: doc.value.nodes.filter(node => ids.has(node.id)),
      edges: doc.value.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target)) }
  }

  function paste(source: DiagramDocument) {
    if (!source.nodes.length || doc.value.nodes.length + source.nodes.length > MAX_NODES
      || doc.value.edges.length + source.edges.length > MAX_EDGES) return
    const ids = new Map(source.nodes.map(node => [node.id, freshId()]))
    const nodes = source.nodes.map(node => ({ ...node, id: ids.get(node.id)!, x: node.x + 32, y: node.y + 32 }))
    const edges = source.edges.map(edge => ({ ...edge, id: freshId(), source: ids.get(edge.source)!, target: ids.get(edge.target)! }))
    commit({ ...doc.value, nodes: [...doc.value.nodes, ...nodes], edges: [...doc.value.edges, ...edges] })
    selectNodes(nodes.map(node => node.id))
  }

  function markSaved(value: DiagramDocument) {
    savedFile.value = value
  }

  return {
    doc, selection, selectedNodes, selectedEdge, canUndo, canRedo, dirty, persisted, replace, undo, redo,
    selectNodes, selectEdge, rename, addNode, addSketch, endSketchSession, addEdge, groupSelection, updateNodes, updateNode, updateEdge,
    nudge, arrange, remove, clearCanvas, extractedSelection, paste, markSaved,
  }
}
