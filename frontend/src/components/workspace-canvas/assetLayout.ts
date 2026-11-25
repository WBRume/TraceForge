import { domainKinds, domainMembers, type CanvasCatalog, type CanvasDomain } from './assetDomains'
import { nodeSizes, referenceKey, scopedAssetId, type CanvasGraph, type CanvasNode, type CanvasRegion,
  type CanvasSnapshot, type Point, type Size } from './model'

const columnStride = nodeSizes.card.width + 90
const rowStride = nodeSizes.card.height + 26
const rowsPerColumn = 5
const localOrigin = { x: 80, y: 20 }
const cardOrigin = { x: 104, y: 94 }

export const translatePoint = (point: Point, offset: Point, direction = 1): Point => ({
  x: point.x + direction * offset.x, y: point.y + direction * offset.y,
})

export function paragraphPosition(document: CanvasNode, nodes: CanvasNode[]): Point {
  const { x } = document.position
  let y = document.position.y + document.size.height + 26
  const occupied = nodes.filter(node => node.kind !== 'frame' && x < node.position.x + node.size.width + 14
    && x + nodeSizes.card.width + 14 > node.position.x).sort((a, b) => a.position.y - b.position.y)
  for (const node of occupied) {
    if (y + nodeSizes.card.height + 14 <= node.position.y) break
    if (y < node.position.y + node.size.height + 14) y = node.position.y + node.size.height + 26
  }
  return { x, y }
}

interface DomainLayout {
  region: CanvasRegion
  nodes: { node: CanvasNode; assetId: string }[]
}

const treeCardSize = { width: 248, height: 122 }

function createDomain(catalog: CanvasCatalog, domain: CanvasDomain, saved: ReadonlyMap<string, CanvasNode>, tile: boolean,
  quarter?: string, tree = false, collapsed?: ReadonlySet<string>): DomainLayout {
  const { node_id: root, details } = domain.asset
  const nodes: DomainLayout['nodes'] = []
  const start = tree ? { x: cardOrigin.x, y: localOrigin.y + 14 }
    : tile ? { x: localOrigin.x + 10, y: localOrigin.y + 10 } : cardOrigin
  const defaultSize = tree ? treeCardSize : tile ? { width: 166, height: 100 } : nodeSizes.card
  const reserved = tree ? domainMembers(catalog, root).flatMap(({ id }) => {
    const node = saved.get(scopedAssetId(id, root))
    return node ? [node] : []
  }).sort((first, second) => first.position.y - second.position.y) : []
  let right = start.x, bottom = start.y

  function availablePosition(proposed: Point, size: Size, old?: CanvasNode) {
    if (!tree) return old?.position ?? proposed
    const point = { ...(old?.position ?? proposed) }
    // Preserve placed cards and leave room for saved positions when flowing in new siblings.
    const occupied = [...(old ? [] : reserved), ...nodes.map(item => item.node)]
      .sort((first, second) => first.position.y - second.position.y)
    for (const { position, size: current } of occupied) {
      if (point.x < position.x + current.width + 12 && point.x + size.width + 12 > position.x
        && point.y < position.y + current.height + 16 && point.y + size.height + 16 > position.y) {
        point.y = position.y + current.height + 16
      }
    }
    return point
  }

  function place(assetId: string, proposed: Point) {
    const asset = catalog.byId.get(assetId)!
    const historicalQuarter = quarter && asset.reference.kind === 'requirement' && asset.quarter?.id !== quarter
      ? asset.quarter ?? undefined : undefined
    const id = scopedAssetId(assetId, root)
    const old = saved.get(id)
    const size = historicalQuarter ? { width: nodeSizes.card.width, height: 174 } : old?.size ?? defaultSize
    const position = availablePosition(proposed, size, old)
    right = Math.max(right, position.x + size.width)
    bottom = Math.max(bottom, position.y + size.height)
    const children = catalog.childLinks.get(assetId)
    const expandedChildren = (catalog.children.get(assetId) ?? []).some(child => children?.has(child))
    const unseenChildren = Boolean(asset.has_unseen_children)
    const foldedChildren = Boolean(collapsed?.has(assetId) && (asset.has_tree_children || children?.size))
    nodes.push({ assetId, node: { id, kind: 'card', automatic: true, domainId: root,
      scope_id: root, position, size, reference: asset.reference, details: asset.details, text: '', color: 'blue',
      historicalQuarter, expandedChildren, unseenChildren,
      expandable: !historicalQuarter && (expandedChildren || unseenChildren || foldedChildren) } })
    return Math.max(proposed.y, position.y) + size.height
  }
  if (tree) {
    const visited = new Set<string>()
    function placeSubtree(id: string, depth: number, y: number): number {
      visited.add(id)
      let end = place(id, { x: start.x + depth * columnStride, y })
      let next = y
      for (const child of catalog.children.get(id) ?? []) {
        if (visited.has(child) || catalog.rootByAsset.get(child) !== root) continue
        end = Math.max(end, placeSubtree(child, depth + 1, next))
        next = end + 22
      }
      return end
    }
    placeSubtree(root, 0, start.y)
  } else {
    const levels = new Map<number, string[]>()
    for (const { id, level } of domainMembers(catalog, root)) {
      const entries = levels.get(level) ?? []
      entries.push(id)
      levels.set(level, entries)
    }
    let column = 0
    for (const tier of levels.values()) {
      for (const [index, id] of tier.entries()) {
        place(id, { x: start.x + (column + Math.floor(index / rowsPerColumn)) * columnStride,
          y: start.y + (index % rowsPerColumn) * rowStride })
      }
      column += Math.ceil(tier.length / rowsPerColumn)
    }
  }
  return { nodes, region: { id: root, type: 'domain', title: details.title, kind: domain.kind, assetCount: nodes.length,
    position: localOrigin, size: { width: right - localOrigin.x + (tile || tree ? 14 : 24),
      height: bottom - localOrigin.y + (tile || tree ? 14 : 24) } } }
}

function arrangeTree(domains: DomainLayout[]) {
  let y = 0
  return { sections: [], domains: domains.map(item => {
    const position = { x: 0, y }
    y += item.region.size.height + 14
    return { item, position }
  }) }
}

function pack<T>(items: T[], sizeOf: (item: T) => Size, minWidth: number, gap: number, widthHint?: number) {
  let maxWidth = minWidth, area = 0
  for (const item of items) {
    const size = sizeOf(item)
    maxWidth = Math.max(maxWidth, size.width)
    area += (size.width + gap) * (size.height + gap)
  }
  const target = Math.max(maxWidth, widthHint ?? Math.sqrt(area * 1.5))
  let x = 0, y = 0, rowHeight = 0, width = 0
  const positions = items.map(item => {
    const size = sizeOf(item)
    if (x > 0 && x + size.width > target) { x = 0; y += rowHeight + gap; rowHeight = 0 }
    const position = { x, y }
    rowHeight = Math.max(rowHeight, size.height)
    width = Math.max(width, x + size.width)
    x += size.width + gap
    return { item, position }
  })
  return { positions, size: { width, height: y + rowHeight } }
}

function arrangeDomains(catalog: CanvasCatalog, domains: DomainLayout[], featured: boolean) {
  const connected = new Map<string, Set<string>>()
  const add = (source: string, target: string) => {
    let destinations = connected.get(source)
    if (!destinations) connected.set(source, destinations = new Set())
    destinations.add(target)
  }
  for (const link of catalog.relations) {
    const source = catalog.rootByAsset.get(link.sourceId), target = catalog.rootByAsset.get(link.targetId)
    if (source && target && source !== target) { add(source, target); add(target, source) }
  }
  const byId = new Map(domains.map(domain => [domain.region.id, domain]))
  const visited = new Set<string>()
  const ordered: DomainLayout[] = []
  // Keep workstreams with real cross-domain links spatially near each other.
  for (const domain of domains.slice().sort((a, b) => b.region.assetCount - a.region.assetCount)) {
    const pending = [domain.region.id]
    for (const id of pending) {
      if (visited.has(id)) continue
      visited.add(id)
      ordered.push(byId.get(id)!)
      for (const neighbor of connected.get(id) ?? []) pending.push(neighbor)
    }
  }
  if (featured) {
    const gap = 58
    const sizeOf = (item: DomainLayout) => item.region.size
    const widths = new Set<number>()
    for (let from = 0; from < ordered.length; from += 1) {
      let width = 0
      for (const item of ordered.slice(from)) {
        if (width) width += gap
        width += sizeOf(item).width
        widths.add(width)
      }
    }
    const candidates = [...widths].map(width => pack(ordered, sizeOf, 0, gap, width))
    const fit = ({ size }: typeof candidates[number]) => Math.max(size.height * 1.65, size.width)
    const best = candidates.reduce<typeof candidates[number] | undefined>((best, item) =>
      !best || fit(item) < fit(best) ? item : best, undefined)
    return { domains: best?.positions ?? [], sections: [] as CanvasRegion[] }
  }
  if (ordered.length <= 16) {
    const paired = ordered.slice(0, 2).reduce((total, item) => total + item.region.size.width, 58)
    return { domains: pack(ordered, domain => domain.region.size, Math.max(1120, Math.min(paired, 2460)), 58).positions,
      sections: [] as CanvasRegion[] }
  }

  const related = (domain: DomainLayout) => domain.region.assetCount > 1 || connected.has(domain.region.id)
  const sections = [
    { kind: 'linked' as const, domains: ordered.filter(related) },
    ...domainKinds.map(kind => ({ kind, domains: ordered.filter(domain => domain.region.kind === kind && !related(domain)) })),
  ].filter(section => section.domains.length).map(section => {
    const arranged = pack(section.domains, domain => domain.region.size, 1000, 34)
    const top = section.kind === 'linked' ? 168 : 230
    return { ...section, arranged, top, size: { width: arranged.size.width + 60, height: arranged.size.height + top + 32 } }
  })
  const arranged = pack(sections, section => section.size, 1200, 72)
  return {
    sections: arranged.positions.map(({ item, position }): CanvasRegion => ({ id: item.kind, type: 'section',
      kind: item.kind, position, size: item.size, assetCount: item.domains.reduce((count, domain) => count + domain.region.assetCount, 0) })),
    domains: arranged.positions.flatMap(({ item, position }) => item.arranged.positions.map(entry => ({ item: entry.item,
      position: translatePoint(entry.position, { x: position.x + 30, y: position.y + item.top }) }))),
  }
}

export function layoutWorkspace(snapshot: CanvasSnapshot, catalog: CanvasCatalog, featured = false): CanvasGraph {
  const saved = new Map(snapshot.nodes.map(node => [node.id, node]))
  const assetFor = (node: CanvasNode) => node.reference ? catalog.byReference.get(referenceKey(node.reference)) : undefined
  const connectedAssets = new Set(catalog.relations.flatMap(link => [link.sourceId, link.targetId]))
  const streaming = Boolean(snapshot.root_tree)
  const tree = Boolean(streaming || snapshot.quarter)
  const roots = streaming ? catalog.roots : catalog.roots.slice().sort((first, second) =>
    (first.asset.details.created_at ?? '').localeCompare(second.asset.details.created_at ?? '')
    || first.asset.node_id.localeCompare(second.asset.node_id))
  const domains = roots.map(root => createDomain(catalog, root, saved,
    !tree && !featured && roots.length > 16 && !connectedAssets.has(root.asset.node_id), snapshot.quarter?.id, tree, snapshot.collapsedAssets))
  const placements = streaming ? arrangeTree(domains) : tree ? {
    sections: [] as CanvasRegion[],
    domains: pack(domains, item => item.region.size, 1450, 45, 1450).positions,
  } : arrangeDomains(catalog, domains, featured)
  const regions = placements.sections.slice()
  const scopeOffsets = new Map<string, Point>()
  const assetNodeIds = new Map<string, string>()
  const originByAsset = new Map<string, Point>()
  const nodes: CanvasNode[] = []
  const absoluteSaved = new Map<string, CanvasNode>()
  if (snapshot.quarter) scopeOffsets.set(`quarter-${snapshot.quarter.id}`, { x: 0, y: 0 })
  for (const node of snapshot.nodes) {
    const asset = assetFor(node)
    if (asset && !node.scope_id && !absoluteSaved.has(asset.node_id)) absoluteSaved.set(asset.node_id, node)
  }

  for (const { item, position } of placements.domains) {
    const region = { ...item.region, position }
    const offset = translatePoint(position, localOrigin, -1)
    regions.push(region)
    scopeOffsets.set(region.id, offset)
    for (const { node, assetId } of item.nodes) {
      const absolute = saved.has(node.id) ? undefined : absoluteSaved.get(assetId)
      const placed = absolute ? { ...node, ...absolute, automatic: true }
        : { ...node, position: translatePoint(node.position, offset) }
      nodes.push(placed)
      assetNodeIds.set(assetId, placed.id)
      originByAsset.set(assetId, translatePoint(placed.position, cardOrigin, -1))
    }
  }

  const aliases = new Map<string, string>()
  for (const node of snapshot.nodes) {
    const asset = assetFor(node)
    if (asset) {
      aliases.set(node.id, assetNodeIds.get(asset.node_id)!)
      continue
    }
    if (tree && node.reference && node.id.startsWith('asset-')) continue
    const origin = node.scope_id ? scopeOffsets.get(node.scope_id) ?? originByAsset.get(node.scope_id) : undefined
    if (snapshot.quarter && node.scope_id && !origin) continue
    if (node.scope_id && origin) scopeOffsets.set(node.scope_id, origin)
    nodes.push(origin ? { ...node, position: translatePoint(node.position, origin), domainId: node.scope_id ?? undefined } : node)
    aliases.set(node.id, node.id)
  }

  const relations = catalog.relations.flatMap(link => {
    const sourceNodeId = assetNodeIds.get(link.sourceId), targetNodeId = assetNodeIds.get(link.targetId)
    if (!sourceNodeId || !targetNodeId) return []
    return [{ ...link, sourceNodeId, targetNodeId, id: JSON.stringify([sourceNodeId, targetNodeId, link.relation_type]) }]
  })
  const edges = snapshot.edges.flatMap(edge => {
    const source = aliases.get(edge.source), target = aliases.get(edge.target)
    return source && target && source !== target ? [{ ...edge, source, target }] : []
  })
  return { revision: snapshot.revision, quarter: snapshot.quarter, root_tree: snapshot.root_tree, nodes, relations, edges, access: snapshot.access,
    regions, scopeOffsets, assetNodeIds }
}
