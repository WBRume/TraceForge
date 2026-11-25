import { referenceKey, type CanvasAsset, type CanvasDomainKind, type CanvasRelation, type CanvasRelationType, type CanvasSnapshot } from './model'

export const domainKinds = ['delivery', 'standalone', 'diagnosis', 'knowledge'] as const

export interface CatalogRelation extends CanvasRelation {
  sourceId: string
  targetId: string
}

export interface CanvasDomain {
  asset: CanvasAsset
  kind: CanvasDomainKind
}

export interface CanvasCatalog {
  assets: CanvasAsset[]
  byId: Map<string, CanvasAsset>
  byReference: Map<string, CanvasAsset>
  relations: CatalogRelation[]
  roots: CanvasDomain[]
  rootByAsset: Map<string, string>
  children: Map<string, string[]>
}

const ownership: Partial<Record<CanvasRelationType, { priority: number; parent: 'source' | 'target' }>> = {
  SUB_REQUIREMENT: { priority: 0, parent: 'target' },
  COVERS: { priority: 0, parent: 'target' },
  RELATES_TO: { priority: 1, parent: 'target' },
  DOCUMENT_TASK: { priority: 0, parent: 'target' },
  DOCUMENT_REQUIREMENT: { priority: 1, parent: 'target' },
  CASE_TASK: { priority: 0, parent: 'target' },
  CASE_PROMOTION: { priority: 0, parent: 'source' },
  CASE_PLAYBOOK: { priority: 1, parent: 'source' },
  TASK_PLAYBOOK: { priority: 2, parent: 'source' },
}

function domainKind(asset: CanvasAsset): CanvasDomainKind {
  if (asset.reference.kind === 'requirement') return 'delivery'
  if (asset.reference.kind === 'task') return asset.details.task_type === 'DIAGNOSIS' ? 'diagnosis' : 'standalone'
  return 'knowledge'
}

export function buildCanvasCatalog(snapshot: CanvasSnapshot, planFiles: CanvasAsset[] = []): CanvasCatalog {
  const byReference = new Map([...snapshot.assets, ...planFiles].map(asset => [referenceKey(asset.reference), asset]))
  const assets = [...byReference.values()]
  const byId = new Map(assets.map(asset => [asset.node_id, asset]))
  const parents = new Map<string, { id: string; priority: number }>()
  for (const [child, parent] of snapshot.treeParents ?? []) parents.set(child, { id: parent, priority: 0 })
  const relations: CatalogRelation[] = []

  function link(relation: CanvasRelation) {
    const source = byReference.get(referenceKey(relation.source))
    const target = byReference.get(referenceKey(relation.target))
    const sourceId = source?.node_id
    const targetId = target?.node_id
    if (!sourceId || !targetId || sourceId === targetId) return
    relations.push({ ...relation, sourceId, targetId })
    if (snapshot.treeParents && relation.source.kind !== 'plan_document') return
    const rule = ownership[relation.relation_type]
    if (!rule) return
    const quarter = snapshot.quarter?.id
    const historical = quarter && relation.target.kind === 'requirement' && target?.quarter
      && target.quarter.id !== quarter && source?.quarter?.id === quarter
    const [parent, child] = historical || rule.parent === 'source' ? [sourceId, targetId] : [targetId, sourceId]
    const existing = parents.get(child)
    if (!existing || rule.priority < existing.priority || (rule.priority === existing.priority && parent < existing.id)) {
      parents.set(child, { id: parent, priority: rule.priority })
    }
  }

  snapshot.relations.forEach(link)
  for (const file of planFiles) {
    if (file.reference.kind === 'plan_document') {
      link({ source: file.reference, target: { kind: 'task', id: file.reference.id }, relation_type: 'DOCUMENT_TASK' })
    }
  }

  const children = new Map<string, string[]>()
  for (const asset of assets) {
    const parent = parents.get(asset.node_id)
    if (!parent) continue
    let entries = children.get(parent.id)
    if (!entries) children.set(parent.id, entries = [])
    entries.push(asset.node_id)
  }

  const roots: CanvasDomain[] = []
  const rootByAsset = new Map<string, string>()
  function addRoot(asset: CanvasAsset) {
    roots.push({ asset, kind: domainKind(asset) })
    const queue = [asset.node_id]
    for (const id of queue) {
      if (rootByAsset.has(id)) continue
      rootByAsset.set(id, asset.node_id)
      for (const child of children.get(id) ?? []) queue.push(child)
    }
  }
  for (const asset of assets) if (!parents.has(asset.node_id)) addRoot(asset)
  // Invalid or historical cycles still get an entry and keep their real links.
  for (const asset of assets) if (!rootByAsset.has(asset.node_id)) addRoot(asset)
  return { assets, byId, byReference, relations, roots, rootByAsset, children }
}

export interface DomainVisit { id: string; level: number }

export function domainMembers(catalog: CanvasCatalog, rootId: string): DomainVisit[] {
  const visited = new Set([rootId])
  const ordered: DomainVisit[] = [{ id: rootId, level: 0 }]
  for (const item of ordered) {
    for (const id of catalog.children.get(item.id) ?? []) {
      if (visited.has(id) || catalog.rootByAsset.get(id) !== rootId) continue
      visited.add(id)
      ordered.push({ id, level: item.level + 1 })
    }
  }
  return ordered
}
