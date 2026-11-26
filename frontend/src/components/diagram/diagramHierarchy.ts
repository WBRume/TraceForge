import { isTopic, type DiagramDocument, type DiagramNode } from './diagramModel'

type Tree = { node: DiagramNode; children: Tree[]; crossSize: number }
const childGap = 28
const levelGap = 84

export function layoutHierarchy(doc: DiagramDocument, selected: ReadonlySet<string>, mindMap: boolean) {
  const nodes = doc.nodes.filter(node => (!selected.size || selected.has(node.id))
    && (mindMap ? isTopic(node.shape) : node.shape === 'person'))
  if (nodes.length < 2) return doc.nodes
  const byId = new Map(nodes.map(node => [node.id, node]))
  const outgoing = new Map<string, string[]>()
  const targets = new Set<string>()
  for (const { source, target, relation } of doc.edges) {
    if (relation !== (mindMap ? 'branch' : 'reporting') || !byId.has(source) || !byId.has(target)) continue
    const children = outgoing.get(source) ?? []
    children.push(target)
    outgoing.set(source, children)
    targets.add(target)
  }
  const root = (mindMap ? nodes.find(node => node.shape === 'topicRoot' && outgoing.has(node.id)) : undefined)
    ?? nodes.find(node => !targets.has(node.id) && outgoing.has(node.id))
    ?? nodes.find(node => outgoing.has(node.id))
  if (!root) return doc.nodes
  const cross = mindMap ? 'height' : 'width'
  const seen = new Set<string>()
  const span = (trees: Tree[]) => trees.reduce((sum, tree) => sum + tree.crossSize + childGap, -childGap)
  function collect(node: DiagramNode): Tree {
    seen.add(node.id)
    const children: Tree[] = []
    for (const id of outgoing.get(node.id) ?? []) {
      if (!seen.has(id)) children.push(collect(byId.get(id)!))
    }
    return { node, children, crossSize: Math.max(node[cross], span(children)) }
  }

  const tree = collect(root)
  const result = new Map([[root.id, root]])
  function place(children: Tree[], parent: DiagramNode, side: number) {
    const center = mindMap ? parent.y + parent.height / 2 : parent.x + parent.width / 2
    let cursor = center - span(children) / 2
    for (const child of children) {
      const item = child.node
      const childCenter = cursor + child.crossSize / 2
      const positioned = mindMap ? {
        ...item, x: side > 0 ? parent.x + parent.width + levelGap : parent.x - levelGap - item.width,
        y: childCenter - item.height / 2,
      } : {
        ...item, x: childCenter - item.width / 2, y: parent.y + parent.height + levelGap,
      }
      result.set(item.id, positioned)
      place(child.children, positioned, side)
      cursor += child.crossSize + childGap
    }
  }
  if (mindMap) {
    place(tree.children.filter((_, i) => i % 2 === 0), root, 1)
    place(tree.children.filter((_, i) => i % 2 === 1), root, -1)
  } else place(tree.children, root, 1)
  return doc.nodes.map(node => result.get(node.id) ?? node)
}
