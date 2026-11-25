import { isDocument, nodeSizes, referenceKey, sourceKinds, type CanvasAsset, type CanvasGraph,
  type CanvasGroup, type CanvasGroupKind, type CanvasNode, type CanvasRelation, type CanvasSnapshot, type Point } from './model'

const columns: Record<CanvasGroupKind, number> = {
  requirement: 64, document: 404, task: 744, case: 1084, playbook: 1424,
}
const placementOrder: CanvasGroupKind[] = ['requirement', 'task', 'case', 'playbook', 'document']
const top = 85
const gap = 32

function overlapsCard(position: Point, node: CanvasNode, margin: number) {
  return position.x < node.position.x + node.size.width + margin
    && position.x + nodeSizes.card.width + margin > node.position.x
    && position.y < node.position.y + node.size.height + margin
    && position.y + nodeSizes.card.height + margin > node.position.y
}

function nextOpenCard(x: number, initialY: number, reserved: CanvasNode[]): Point {
  let y = initialY
  while (reserved.some(node => overlapsCard({ x, y }, node, 14))) y += nodeSizes.card.height + gap
  return { x, y }
}

export function paragraphPosition(document: CanvasNode, nodes: CanvasNode[]): Point {
  return nextOpenCard(document.position.x, document.position.y + document.size.height + gap,
    nodes.filter(node => node.kind !== 'frame'))
}

function orderRequirements(assets: CanvasAsset[], relations: CanvasRelation[]) {
  const byKey = new Map(assets.map(asset => [referenceKey(asset.reference), asset]))
  const dependencies = new Map<string, string[]>()
  for (const link of relations) {
    if (link.relation_type !== 'SUB_REQUIREMENT' && link.relation_type !== 'PREREQUISITE') continue
    const key = referenceKey(link.source)
    dependencies.set(key, [...(dependencies.get(key) ?? []), referenceKey(link.target)])
  }
  const visited = new Set<string>()
  const ordered: CanvasAsset[] = []
  function visit(key: string) {
    const asset = byKey.get(key)
    if (!asset || visited.has(key)) return
    visited.add(key)
    for (const parent of dependencies.get(key) ?? []) visit(parent)
    ordered.push(asset)
  }
  for (const key of byKey.keys()) visit(key)
  return ordered
}

export function layoutWorkspaceAssets(snapshot: CanvasSnapshot, planFiles: CanvasAsset[]): CanvasGraph {
  const assets = [...snapshot.assets, ...planFiles].filter(asset => sourceKinds.includes(asset.reference.kind))
  const taskIds = new Set(assets.filter(asset => asset.reference.kind === 'task').map(asset => asset.reference.id))
  const relations: CanvasRelation[] = [...snapshot.relations]
  for (const file of planFiles) {
    if (file.reference.kind === 'plan_document' && taskIds.has(file.reference.id)) {
      relations.push({ source: file.reference, target: { kind: 'task', id: file.reference.id }, relation_type: 'DOCUMENT_TASK' })
    }
  }
  const canonicalKeys = new Set(assets.map(asset => referenceKey(asset.reference)))
  const savedKeys = new Set<string>()
  const nodes = snapshot.nodes.filter(node => !node.reference || sourceKinds.includes(node.reference.kind)).map(node => {
    if (!node.reference) return node
    const key = referenceKey(node.reference)
    savedKeys.add(key)
    return canonicalKeys.has(key) ? { ...node, automatic: true } : node
  })
  const byKind = new Map<CanvasGroupKind, CanvasAsset[]>()
  for (const asset of assets) {
    const kind = isDocument(asset.reference) ? 'document' : asset.reference.kind
    if (!byKind.has(kind)) byKind.set(kind, [])
    byKind.get(kind)?.push(asset)
  }
  const neighbors = new Map<string, string[]>()
  for (const link of relations) {
    const source = referenceKey(link.source), target = referenceKey(link.target)
    for (const [key, opposite] of [[source, target], [target, source]] as const) {
      if (!neighbors.has(key)) neighbors.set(key, [])
      neighbors.get(key)?.push(opposite)
    }
  }
  const groups: CanvasGroup[] = []
  const reserved = nodes.filter(node => node.kind !== 'frame')
  const rows = new Map<string, number>()
  const linkedRow = (asset: CanvasAsset) => Math.min(Infinity,
    ...(neighbors.get(referenceKey(asset.reference)) ?? []).map(key => rows.get(key) ?? Infinity))
  for (const kind of placementOrder) {
    const items = byKind.get(kind)
    if (!items?.length) continue
    const ordered = kind === 'requirement' ? orderRequirements(items, relations)
      : items.map(asset => ({ asset, row: linkedRow(asset) }))
        .sort((a, b) => a.row === b.row ? 0 : a.row - b.row).map(item => item.asset)
    const x = columns[kind]
    let y = top
    let hasGroup = false
    for (const [row, asset] of ordered.entries()) {
      const key = referenceKey(asset.reference)
      rows.set(key, row)
      if (savedKeys.has(key)) continue
      // Frames enclose the cards at their current coordinates.
      const position = nextOpenCard(x, y, reserved)
      if (!hasGroup) groups.push({ kind, position: { x, y: position.y - 36 } })
      hasGroup = true
      nodes.push({ id: asset.node_id, kind: 'card', position, size: nodeSizes.card, text: '', color: 'blue',
        reference: asset.reference, details: asset.details, automatic: true })
      y = position.y + nodeSizes.card.height + gap
    }
  }
  const nodeIds = new Map<string, string>()
  for (const node of nodes) {
    if (node.reference) {
      const key = referenceKey(node.reference)
      if (canonicalKeys.has(key) && !nodeIds.has(key)) nodeIds.set(key, node.id)
    }
  }
  const projected = relations.flatMap(link => {
    const sourceNodeId = nodeIds.get(referenceKey(link.source))
    const targetNodeId = nodeIds.get(referenceKey(link.target))
    if (!sourceNodeId || !targetNodeId) return []
    return [{ ...link, sourceNodeId, targetNodeId, id: JSON.stringify([sourceNodeId, targetNodeId, link.relation_type]) }]
  })
  return { revision: snapshot.revision, nodes, edges: snapshot.edges, relations: projected, access: snapshot.access, groups }
}
