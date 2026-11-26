import { describe, expect, it } from 'vitest'
import { buildCanvasCatalog } from '../assetDomains'
import { layoutWorkspace, translatePoint } from '../assetLayout'
import { buildCanvasPaths } from '../canvasPaths'
import { arrowInBounds, fittedViewport, frameMembers } from '../geometry'
import { nodeSizes, referenceKey, scopedAssetId, type CanvasAsset, type CanvasNode, type CanvasSnapshot, type SourceReference } from '../model'
import { planTreePreview } from '../treePreview'

function asset(id: string, reference: SourceReference, taskType?: string): CanvasAsset {
  return { node_id: id, reference, details: { title: reference.id, status: null, detail: null, context: null,
    version: null, historical: false, task_id: null, task_type: taskType } }
}

function snapshot(assets: CanvasAsset[], nodes: CanvasNode[] = []): CanvasSnapshot {
  return { revision: 0, assets, nodes, edges: [], relations: [], access: { source_kinds: ['task'], can_link_requirements: true } }
}

describe('workspace canvas', () => {
  it('uses available width for wide branches while retaining subtrees and their canonical arrows', () => {
    const root = asset('requirement', { kind: 'requirement', id: 'requirement' })
    const tasks = Array.from({ length: 20 }, (_, i) => asset(`task-${i}`, { kind: 'task', id: `task-${i}` }))
    const doc = asset('document', { kind: 'document', id: 'document' })
    const placement = (count: number, width: number, nodes: CanvasNode[] = []) => {
      const selected = tasks.slice(0, count)
      const state = snapshot([root, ...selected, doc], nodes)
      state.root_tree = true
      state.relations = [
        ...selected.map(task => ({ source: task.reference, target: root.reference, relation_type: 'COVERS' as const })),
        { source: doc.reference, target: tasks[0]!.reference, relation_type: 'DOCUMENT_TASK' },
      ]
      return layoutWorkspace(state, buildCanvasCatalog(state), false, { width, height: 690 },
        new Map([[referenceKey(root.reference), { cursor: 'more' }]]))
    }
    const wide = placement(12, 1320)
    const narrow = placement(12, 720)
    const extended = placement(20, 1320)
    const node = (graph: typeof wide, id: string) => graph.nodes.find(item => item.id === graph.assetNodeIds.get(id))!
    const columns = (graph: typeof wide) => new Set(tasks.slice(0, 12).map(task => node(graph, task.node_id).position.x)).size
    expect(columns(wide)).toBe(4)
    expect(columns(narrow)).toBe(2)
    expect(node(wide, 'task-3').position.y).toBe(node(wide, 'task-0').position.y)
    expect(node(wide, 'task-4').position.y).toBeGreaterThan(node(wide, 'document').position.y)
    expect(node(wide, 'task-7').position).toEqual(node(extended, 'task-7').position)
    expect(wide.continuations[0]?.position).toEqual(extended.continuations[0]?.position)
    const note: CanvasNode = { id: 'branch-note', kind: 'note', scope_id: root.node_id, color: 'yellow',
      position: translatePoint(node(wide, 'task-3').position, wide.scopeOffsets.get(root.node_id)!, -1),
      size: nodeSizes.note, text: 'Review', reference: null, details: null }
    const withNote = placement(12, 1320, [note])
    expect(node(withNote, 'task-3').position.y).toBeGreaterThanOrEqual(node(wide, 'task-3').position.y + note.size.height)
    expect(node(withNote, 'task-1').position).toEqual(node(wide, 'task-1').position)
    const { business } = buildCanvasPaths({ ...extended, tree: true })
    const connection = business.find(path => path.relation.source.id === 'document')!
    expect(connection.branchParentId).toBe(node(extended, 'task-0').id)
    expect(connection.relation.relation_type).toBe('DOCUMENT_TASK')
    const long = business.find(path => path.relation.source.id === 'task-19')!
    const stem = long.stem!
    expect(long.vertices?.[0]?.y).toBeGreaterThan(node(extended, 'task-19').position.y)
    expect(long.vertices?.at(-1)?.y).toBe(node(extended, root.node_id).position.y + node(extended, root.node_id).size.height + 8)
    expect(arrowInBounds(long, { left: stem.x - 2, right: stem.x + 2, top: stem.top + 80, bottom: stem.top + 160 })).toBe(true)
    expect(arrowInBounds(long, { left: stem.x - 50, right: stem.x - 20, top: stem.top + 80, bottom: stem.top + 160 })).toBe(false)
  })

  it('opens compact branches independently, reduces depth in a narrow viewport and retains a manual expansion', () => {
    const requirement = asset('small', { kind: 'requirement', id: 'small' })
    const otherRoot = asset('unrelated', { kind: 'task', id: 'unrelated' })
    const broad = asset('broad', { kind: 'task', id: 'broad' })
    const short = asset('short', { kind: 'task', id: 'short' })
    const doc = asset('spec', { kind: 'document', id: 'spec' })
    const many = Array.from({ length: 6 }, (_, i) => asset(`doc-${i}`, { kind: 'document', id: `doc-${i}` }))
    const page = {
      assets: [requirement, otherRoot, broad, short, doc, ...many],
      root_ids: [requirement.node_id, otherRoot.node_id],
      next_cursor: 'more roots',
      preview_children: {
        small: [broad.node_id, short.node_id],
        broad: many.map(item => item.node_id),
        short: [doc.node_id],
      },
      relations: [
        { source: broad.reference, target: requirement.reference, relation_type: 'COVERS' as const },
        { source: short.reference, target: requirement.reference, relation_type: 'COVERS' as const },
        { source: doc.reference, target: short.reference, relation_type: 'DOCUMENT_TASK' as const },
        ...many.map(item => ({ source: item.reference, target: broad.reference, relation_type: 'DOCUMENT_TASK' as const })),
      ],
    }
    const plan = (width: number, pinned = new Set<string>()) =>
      planTreePreview([page], undefined, { width, height: 610 }, new Set(), pinned, new Set())
    const wide = plan(1460)
    expect(wide.parents.get(doc.node_id)).toBe(short.node_id)
    expect(wide.parents.has(many[0]!.node_id)).toBe(false)
    expect(wide.assets.map(item => item.node_id)).toContain(otherRoot.node_id)
    const narrow = plan(650)
    expect(narrow.parents.get(short.node_id)).toBe(requirement.node_id)
    expect(narrow.parents.has(doc.node_id)).toBe(false)
    expect(plan(650, new Set([short.node_id])).parents.get(doc.node_id)).toBe(short.node_id)
    const tall = planTreePreview([page], undefined, { width: 1460, height: 1230 }, new Set(), new Set(), new Set())
    expect(tall.parents.get(many[0]!.node_id)).toBe(broad.node_id)
  })

  it('gives each asset one placement and keeps actual relationships across workstreams', () => {
    const first = asset('req-one', { kind: 'requirement', id: 'first' })
    const second = asset('req-two', { kind: 'requirement', id: 'second' })
    const standalone = asset('task-two', { kind: 'task', id: 'standalone' })
    const diagnosis = asset('diagnosis-one', { kind: 'task', id: 'diagnosis' }, 'DIAGNOSIS')
    const issue = asset('case-one', { kind: 'case', id: 'case' })
    const spec = asset('spec-one', { kind: 'playbook', id: 'playbook' })
    const document = asset('doc-one', { kind: 'document', id: 'doc' })
    const state = snapshot([first, second, standalone, diagnosis, issue, spec, document])
    state.relations = [
      { source: second.reference, target: first.reference, relation_type: 'PREREQUISITE' },
      { source: document.reference, target: first.reference, relation_type: 'DOCUMENT_REQUIREMENT' },
      { source: document.reference, target: standalone.reference, relation_type: 'DOCUMENT_TASK' },
      { source: issue.reference, target: diagnosis.reference, relation_type: 'CASE_TASK' },
      { source: issue.reference, target: spec.reference, relation_type: 'CASE_PROMOTION' },
    ]
    const catalog = buildCanvasCatalog(state)
    const graph = layoutWorkspace(state, catalog)
    const node = (id: string) => graph.nodes.find(item => item.id === graph.assetNodeIds.get(id))!

    expect(graph.nodes).toHaveLength(state.assets.length)
    expect(new Set(graph.nodes.map(item => item.id)).size).toBe(state.assets.length)
    expect(node(document.node_id).domainId).toBe(standalone.node_id)
    expect(node(spec.node_id).domainId).toBe(diagnosis.node_id)
    expect(node(diagnosis.node_id).position.x).toBeLessThan(node(issue.node_id).position.x)
    expect(node(issue.node_id).position.x).toBeLessThan(node(spec.node_id).position.x)
    expect(graph.relations.map(link => [link.source.id, link.target.id, link.relation_type])).toEqual(
      state.relations.map(link => [link.source.id, link.target.id, link.relation_type]))
  })

  it('lays out and fits every asset in a large workstream and the isolated tasks around it', () => {
    const root = asset('root', { kind: 'requirement', id: 'requirement' })
    const tasks = Array.from({ length: 1200 }, (_, number) => asset(`node-${number}`, { kind: 'task', id: `task-${number}` }))
    const state = snapshot([root, ...tasks])
    state.relations = tasks.slice(0, 42).map(task => ({ source: task.reference, target: root.reference, relation_type: 'COVERS' }))
    const graph = layoutWorkspace(state, buildCanvasCatalog(state))
    const viewport = fittedViewport([...graph.nodes, ...graph.regions], { width: 1360, height: 800 })

    expect(graph.nodes).toHaveLength(1201)
    expect(graph.nodes.filter(item => item.domainId === root.node_id)).toHaveLength(43)
    expect(graph.relations).toHaveLength(42)
    expect(graph.regions.some(item => item.kind === 'standalone' && item.assetCount === 1158)).toBe(true)
    for (const item of graph.nodes) {
      const point = item.position
      expect(point.x * viewport.scale + viewport.x).toBeGreaterThan(0)
      expect((point.x + item.size.width) * viewport.scale + viewport.x).toBeLessThan(1360)
      expect((point.y + item.size.height) * viewport.scale + viewport.y).toBeLessThan(800)
    }
  })

  it('keeps scoped placements and older shared notes on the same editable graph', () => {
    const root = asset('delivery', { kind: 'requirement', id: 'requirement' })
    const task = asset('task-node', { kind: 'task', id: 'task' })
    const card: CanvasNode = { id: scopedAssetId(task.node_id, root.node_id), kind: 'card', scope_id: root.node_id,
      position: { x: 440, y: 190 }, size: nodeSizes.card, text: '', color: 'blue', reference: task.reference, details: task.details }
    const frame: CanvasNode = { id: 'frame', kind: 'frame', scope_id: root.node_id,
      position: { x: 420, y: 165 }, size: { width: 350, height: 220 }, text: 'Delivery', color: 'blue', reference: null, details: null }
    const workspaceNote: CanvasNode = { ...frame, id: 'note', scope_id: null, kind: 'note' }
    const state = snapshot([root, task], [card, frame, workspaceNote])
    state.relations = [{ source: task.reference, target: root.reference, relation_type: 'COVERS' }]
    state.edges = [{ id: 'manual', source: card.id, target: workspaceNote.id }]
    const graph = layoutWorkspace(state, buildCanvasCatalog(state))
    const placed = graph.nodes.find(node => node.id === card.id)!
    const placedFrame = graph.nodes.find(node => node.id === frame.id)!

    expect(translatePoint(placed.position, graph.scopeOffsets.get(root.node_id)!, -1)).toEqual(card.position)
    expect(frameMembers(placedFrame, graph.nodes).map(node => node.id)).toEqual([card.id])
    expect(graph.nodes).toContain(workspaceNote)
    expect(graph.edges).toEqual(state.edges)
  })

  it('lays out expanded siblings around saved cards and retains cross-root relations', () => {
    const root = asset('root', { kind: 'requirement', id: 'requirement' })
    const secondary = asset('second', { kind: 'task', id: 'independent' })
    const document = asset('doc', { kind: 'document', id: 'shared' })
    const task = asset('task', { kind: 'task', id: 'task' })
    const saved: CanvasNode = { id: scopedAssetId(document.node_id, root.node_id), kind: 'card',
      scope_id: root.node_id, position: { x: 442, y: 105 }, size: nodeSizes.card,
      text: '', color: 'blue', reference: document.reference, details: document.details }
    const state = snapshot([root, secondary, task, document], [saved])
    state.root_tree = true
    state.treeParents = new Map([[task.node_id, root.node_id], [document.node_id, root.node_id]])
    state.relations = [
      { source: task.reference, target: root.reference, relation_type: 'COVERS' },
      { source: document.reference, target: root.reference, relation_type: 'DOCUMENT_REQUIREMENT' },
      { source: document.reference, target: secondary.reference, relation_type: 'DOCUMENT_TASK' },
    ]
    const graph = layoutWorkspace(state, buildCanvasCatalog(state))
    const placement = (id: string) => graph.nodes.find(node => node.id === graph.assetNodeIds.get(id))!
    expect(placement(root.node_id).position.x).toBe(placement(secondary.node_id).position.x)
    expect(placement(task.node_id).position.y).toBeGreaterThanOrEqual(
      placement(document.node_id).position.y + placement(document.node_id).size.height)
    expect(graph.relations).toHaveLength(3)
    const collapsed = { ...state, assets: [root, secondary], relations: [], treeParents: new Map<string, string>() }
    const collapsedGraph = layoutWorkspace(collapsed, buildCanvasCatalog(collapsed))
    expect(collapsedGraph.nodes).toHaveLength(2)
  })

  it('places a fresh chain from business data and keeps reverse-only cards terminal', () => {
    const delivery = asset('delivery', { kind: 'requirement', id: 'delivery' })
    const implementation = asset('implementation', { kind: 'task', id: 'implementation' })
    const document = asset('document', { kind: 'document', id: 'document' })
    const observation = asset('observation', { kind: 'case', id: 'observation' })
    const state = snapshot([delivery, implementation, document, observation])
    const quarter = { id: '2026-Q4', label_year: 2026, number: 4, year: 2026,
      start: '2026-10-01', end: '2026-12-31', months: [] }
    state.quarter = quarter
    for (const item of state.assets) item.quarter = quarter
    state.relations = [
      { source: implementation.reference, target: delivery.reference, relation_type: 'COVERS' },
      { source: document.reference, target: implementation.reference, relation_type: 'DOCUMENT_TASK' },
    ]
    const graph = layoutWorkspace(state, buildCanvasCatalog(state))
    const placement = (id: string) => graph.nodes.find(node => node.id === graph.assetNodeIds.get(id))!
    expect(graph.regions.find(region => region.id === delivery.node_id)?.assetCount).toBe(3)
    expect(placement(delivery.node_id).position.x).toBeLessThan(placement(implementation.node_id).position.x)
    expect(placement(implementation.node_id).position.x).toBeLessThan(placement(document.node_id).position.x)
    expect(placement(implementation.node_id).expandedChildren).toBe(true)
    expect(placement(document.node_id).expandable).toBe(false)
    expect(placement(observation.node_id).expandable).toBe(false)
    const note: CanvasNode = { id: 'note', kind: 'note', position: placement(document.node_id).position,
      size: nodeSizes.note, text: 'Existing note', color: 'yellow', reference: null, details: null }
    const annotated = { ...state, nodes: [note] }
    const adjusted = layoutWorkspace(annotated, buildCanvasCatalog(annotated))
    const movedDocument = adjusted.nodes.find(node => node.reference?.id === document.reference.id)!
    expect(movedDocument.position.y).toBeGreaterThanOrEqual(note.position.y + note.size.height)
    expect(adjusted.nodes).toContain(note)
    state.collapsedAssets = new Set([implementation.node_id])
    const folded = layoutWorkspace(state, buildCanvasCatalog(state))
    expect(folded.assetNodeIds.has(document.node_id)).toBe(false)
    expect(folded.nodes.find(node => node.reference?.id === implementation.reference.id)?.expandable).toBe(true)
  })
})
