import { arrowGeometry, branchArrowGeometry, crossDomainGeometry, fanArrowGeometry } from './geometry'
import { relationStyles } from './relationStyles'
import type { CanvasBranchRoute, CanvasEdge, CanvasGraphRelation, CanvasNode, CanvasRegion, CanvasRelationType } from './model'

const pairKey = (source: string, target: string) => [source, target].sort().join(':')

interface PathInput {
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  relations: CanvasGraphRelation[]
  regions: CanvasRegion[]
  branchRoutes: ReadonlyMap<string, CanvasBranchRoute>
  tree: boolean
}

function matchingRoute(routes: PathInput['branchRoutes'], source: string, target: string) {
  const first = routes.get(source)
  if (first?.parentId === target) return first
  const second = routes.get(target)
  return second?.parentId === source ? second : undefined
}

export function buildCanvasPaths({ nodes, edges, relations, regions, branchRoutes, tree }: PathInput) {
  const nodesById = new Map(nodes.map(node => [node.id, node]))
  const regionsById = new Map(regions.map(region => [region.id, region]))
  const groups = new Map<string, CanvasGraphRelation[]>()
  const incoming = new Map<string, CanvasGraphRelation[]>()
  const routed = new Map<string, CanvasBranchRoute>()
  const typesByParent = new Map<string, Set<CanvasRelationType>>()
  for (const relation of relations) {
    const key = pairKey(relation.sourceNodeId, relation.targetNodeId)
    const pairs = groups.get(key) ?? []
    pairs.push(relation)
    groups.set(key, pairs)
    if (!tree) continue
    const source = nodesById.get(relation.sourceNodeId), target = nodesById.get(relation.targetNodeId)
    if (!source || !target) continue
    const route = matchingRoute(branchRoutes, source.id, target.id)
    if (route) {
      routed.set(relation.id, route)
      const types = typesByParent.get(route.parentId) ?? new Set<CanvasRelationType>()
      types.add(relation.relation_type)
      typesByParent.set(route.parentId, types)
    } else if (Math.abs(source.position.x - target.position.x) >= target.size.width) {
      const lane = `${target.id}:${source.position.x > target.position.x ? 'right' : 'left'}`
      const list = incoming.get(lane) ?? []
      list.push(relation)
      incoming.set(lane, list)
    }
  }
  const branchPorts = new Map([...typesByParent].map(([id, used]) => {
    const types = [...used].sort()
    const step = Math.min(7, 28 / types.length)
    return [id, new Map(types.map((type, index) => [type, (index - (types.length - 1) / 2) * step]))]
  }))
  const ports = new Map<string, number>()
  const sharedPorts = new Map<string, number>()
  for (const list of incoming.values()) {
    list.sort((a, b) => nodesById.get(a.sourceNodeId)!.position.y - nodesById.get(b.sourceNodeId)!.position.y)
    const step = Math.min(7, 72 / list.length)
    list.forEach((link, index) => ports.set(link.id, (index - (list.length - 1) / 2) * step))
    const siblings = new Map<CanvasRelationType, CanvasGraphRelation[]>()
    for (const link of list) {
      const source = nodesById.get(link.sourceNodeId)!, target = nodesById.get(link.targetNodeId)!
      if (source.domainId !== target.domainId || Math.abs(source.position.x - target.position.x) >= source.size.width + 155) continue
      const related = siblings.get(link.relation_type) ?? []
      related.push(link)
      siblings.set(link.relation_type, related)
    }
    for (const links of siblings.values()) {
      if (links.length < 3) continue
      const port = links.reduce((total, link) => total + (ports.get(link.id) ?? 0), 0) / links.length
      links.forEach(link => sharedPorts.set(link.id, port))
    }
  }
  const business = [...groups.values()].flatMap(list => list.flatMap((relation, index) => {
    const source = nodesById.get(relation.sourceNodeId), target = nodesById.get(relation.targetNodeId)
    if (!source || !target) return []
    const sourceRegion = source.domainId ? regionsById.get(source.domainId) : undefined
    const targetRegion = target.domainId ? regionsById.get(target.domainId) : undefined
    const offset = (index - (list.length - 1) / 2) * 14
    const route = routed.get(relation.id)
    const fan = route && fanArrowGeometry(source, target, route, branchPorts.get(route.parentId)?.get(relation.relation_type) ?? 0)
    const sharedPort = sharedPorts.get(relation.id)
    const innerLane = sourceRegion && sourceRegion === targetRegion
      ? Math.min(sourceRegion.position.y + 5 + index * 4, source.position.y - 9, target.position.y - 9) : undefined
    const geometry = fan ?? (sharedPort !== undefined ? branchArrowGeometry(source, target, sharedPort)
      : tree ? arrowGeometry(source, target, (ports.get(relation.id) ?? 0) + offset, true, innerLane)
      : sourceRegion && targetRegion && sourceRegion !== targetRegion
      ? crossDomainGeometry(source, target, sourceRegion, targetRegion, offset, relation.relation_type === 'PREREQUISITE' ? -15 : 0)
      : arrowGeometry(source, target, offset, true, sourceRegion && sourceRegion.position.y + 63 + index * 6))
    return [{ relation, style: relationStyles[relation.relation_type], ...geometry,
      branchParentId: fan ? route?.parentId : undefined }]
  }))
  const arrows = edges.flatMap(edge => {
    const source = nodesById.get(edge.source), target = nodesById.get(edge.target)
    if (!source || !target) return []
    const shared = groups.get(pairKey(source.id, target.id))?.length ?? 0
    return [{ id: edge.id, ...arrowGeometry(source, target, shared ? (shared + 1) * 8 : 0) }]
  })
  return { business, arrows }
}

export type CanvasPaths = ReturnType<typeof buildCanvasPaths>
