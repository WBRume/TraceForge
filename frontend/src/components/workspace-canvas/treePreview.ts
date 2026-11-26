import { buildCanvasCatalog, type CanvasCatalog } from './assetDomains'
import { historicalCardHeight, treeCardSize, treeColumnStride, treeSiblingGap } from './assetLayout'
import { referenceKey, type CanvasAsset, type CanvasRelation, type CanvasRootWindow, type FiscalQuarter, type Size } from './model'

export function canvasEntryScale(width: number) {
  return width < 1000 ? 0.82 : 0.96
}

function previewSpace(viewport: Size) {
  const width = viewport.width || 1100
  const height = viewport.height || 640
  const scale = canvasEntryScale(width)
  const inset = Math.min(111, width * 0.18)
  return {
    width: Math.max(treeCardSize.width, (width - inset - 28) / scale),
    height: Math.max(treeCardSize.height, (height - 104) / scale),
  }
}

function branchHeight(catalog: CanvasCatalog, node: string, open: ReadonlySet<string>, quarter?: string): number {
  const asset = catalog.byId.get(node)
  const historical = asset?.reference.kind === 'requirement' && asset.quarter && asset.quarter.id !== quarter
  const cardHeight = historical ? historicalCardHeight : treeCardSize.height
  const children = open.has(node) ? catalog.children.get(node) ?? [] : []
  const height = children.reduce((total, child, index) =>
    total + (index ? treeSiblingGap : 0) + branchHeight(catalog, child, open, quarter), 0)
  return Math.max(cardHeight, height)
}

export function planTreePreview(pages: CanvasRootWindow[], quarter: FiscalQuarter | undefined, viewport: Size,
  collapsed: ReadonlySet<string>, pinnedOpen: ReadonlySet<string>, openReferences: ReadonlySet<string>) {
  const allAssets = new Map<string, CanvasAsset>()
  const allRelations = new Map<string, CanvasRelation>()
  const groups = new Map<string, ReadonlySet<string>>()
  const roots = new Set<string>()
  for (const page of pages) {
    for (const id of page.root_ids) roots.add(id)
    for (const asset of page.assets) allAssets.set(asset.node_id, asset)
    for (const relation of page.relations) {
      allRelations.set(JSON.stringify([referenceKey(relation.source), referenceKey(relation.target), relation.relation_type]), relation)
    }
    for (const [parent, children] of Object.entries(page.preview_children)) groups.set(parent, new Set(children))
  }
  const assets = [...roots].flatMap(id => allAssets.get(id) ?? [])
  for (const [id, asset] of allAssets) if (!roots.has(id)) assets.push(asset)
  const relations = [...allRelations.values()]
  const catalog = buildCanvasCatalog({ assets, relations, quarter }, [], { roots, children: groups })
  const owner = new Map([...catalog.children].flatMap(([parent, children]) =>
    children.map(child => [child, parent] as const)))
  const forced = new Set(pinnedOpen)
  for (const asset of assets) if (openReferences.has(referenceKey(asset.reference))) forced.add(asset.node_id)
  for (const id of forced) {
    const parent = owner.get(id)
    if (parent) forced.add(parent)
  }

  const space = previewSpace(viewport)
  const maxDepth = Math.max(0, Math.floor((space.width - treeCardSize.width - 14) / treeColumnStride))
  const selected: CanvasAsset[] = []
  const parents = new Map<string, string>()
  for (const { asset } of catalog.roots) {
    if (!roots.has(asset.node_id)) continue
    const open = new Set<string>()
    let level = [asset.node_id]
    selected.push(asset)
    for (let depth = 0; level.length; depth++) {
      const next: string[] = []
      level.sort((a, b) => (catalog.children.get(a)?.length ?? 0) - (catalog.children.get(b)?.length ?? 0))
      for (const id of level) {
        const children = catalog.children.get(id)
        if (!children?.length || collapsed.has(id) || (!forced.has(id) && depth >= maxDepth)) continue
        open.add(id)
        if (!forced.has(id) && branchHeight(catalog, asset.node_id, open, quarter?.id) > space.height) {
          open.delete(id)
          continue
        }
        for (const child of children) {
          parents.set(child, id)
          selected.push(catalog.byId.get(child)!)
          next.push(child)
        }
      }
      level = next
    }
  }
  return { assets: selected, relations, parents, owner, groups, roots, width: space.width }
}
