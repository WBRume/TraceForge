import { nodeSizes, referenceKey, sourceKinds, type CanvasAsset, type CanvasGraph,
  type CanvasGroup, type CanvasNode, type CanvasSnapshot, type Point, type SourceKind } from './model'

const columns: Record<SourceKind, number> = {
  requirement: 64, task: 358, case: 652, document: 946, plan_document: 946,
}
const top = 85
const gap = 24

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

export function layoutWorkspaceAssets(snapshot: CanvasSnapshot, planFiles: CanvasAsset[]): CanvasGraph {
  const assets = [...snapshot.assets, ...planFiles].filter(asset => sourceKinds.includes(asset.reference.kind))
  const canonicalKeys = new Set(assets.map(asset => referenceKey(asset.reference)))
  const savedKeys = new Set<string>()
  const nodes = snapshot.nodes.filter(node => !node.reference || sourceKinds.includes(node.reference.kind)).map(node => {
    if (!node.reference) return node
    const key = referenceKey(node.reference)
    savedKeys.add(key)
    return canonicalKeys.has(key) ? { ...node, automatic: true } : node
  })
  const byKind = new Map<SourceKind, CanvasAsset[]>()
  for (const asset of assets) {
    const kind = asset.reference.kind
    if (savedKeys.has(referenceKey(asset.reference))) continue
    if (!byKind.has(kind)) byKind.set(kind, [])
    byKind.get(kind)?.push(asset)
  }
  const groups: CanvasGroup[] = []
  const reserved = nodes.filter(node => node.kind !== 'frame')
  const nextByColumn = new Map<number, number>()
  for (const kind of sourceKinds) {
    const pending = byKind.get(kind)
    if (!pending?.length) continue
    const x = columns[kind]
    let y = nextByColumn.get(x) ?? top
    for (const asset of pending) {
      // Frames enclose the cards at their current coordinates.
      const position = nextOpenCard(x, y, reserved)
      if (asset === pending[0]) groups.push({ kind, position: { x, y: position.y - 33 } })
      nodes.push({ id: asset.node_id, kind: 'card', position, size: nodeSizes.card, text: '', color: 'blue',
        reference: asset.reference, details: asset.details, automatic: true })
      y = position.y + nodeSizes.card.height + gap
    }
    nextByColumn.set(x, y + 32)
  }
  return { revision: snapshot.revision, nodes, edges: snapshot.edges, relations: snapshot.relations, access: snapshot.access, groups }
}
