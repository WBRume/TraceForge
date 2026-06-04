import type { SkillFileNode, SkillNodeType } from './skillEditorTypes'
import { normalizePathValue } from './skillEditorPathUtils'

export const flattenFiles = (nodes: SkillFileNode[]): string[] => {
  const result: string[] = []
  const walk = (items: SkillFileNode[]) => {
    items.forEach((item) => {
      if (item.node_type === 'file') {
        result.push(item.path)
        return
      }
      walk(item.children || [])
    })
  }
  walk(nodes)
  return result
}

export const findNodeByPath = (nodes: SkillFileNode[], path: string): SkillFileNode | null => {
  for (const node of nodes) {
    if (node.path === path) return node
    if (node.node_type === 'directory' && node.children?.length) {
      const nested = findNodeByPath(node.children, path)
      if (nested) return nested
    }
  }
  return null
}

export const flattenTreeEntries = (nodes: SkillFileNode[]): Array<{ path: string, node_type: SkillNodeType }> => {
  const entries: Array<{ path: string, node_type: SkillNodeType }> = []
  const walk = (items: SkillFileNode[]) => {
    items.forEach((item) => {
      entries.push({ path: item.path, node_type: item.node_type })
      if (item.node_type === 'directory' && item.children?.length) {
        walk(item.children)
      }
    })
  }
  walk(nodes)
  return entries
}

export const buildTreeFromEntries = (entries: Array<{ path: string, node_type: SkillNodeType }>): SkillFileNode[] => {
  type TreeNode = SkillFileNode & { _childrenMap: Map<string, TreeNode> }
  const rootMap = new Map<string, TreeNode>()

  const ensureNode = (
    children: Map<string, TreeNode>,
    name: string,
    path: string,
    nodeType: SkillNodeType,
  ): TreeNode => {
    const existing = children.get(name)
    if (existing) {
      if (nodeType === 'directory') {
        existing.node_type = 'directory'
      }
      return existing
    }
    const created: TreeNode = {
      name,
      path,
      node_type: nodeType,
      children: [],
      _childrenMap: new Map<string, TreeNode>(),
    }
    children.set(name, created)
    return created
  }

  entries.forEach((entry) => {
    const normalizedPath = normalizePathValue(entry.path)
    if (!normalizedPath) return
    const segments = normalizedPath.split('/').filter(Boolean)
    if (!segments.length) return

    let cursor = rootMap
    let currentPath = ''
    segments.forEach((segment, index) => {
      currentPath = currentPath ? `${currentPath}/${segment}` : segment
      const isLast = index === segments.length - 1
      const nodeType: SkillNodeType = isLast ? entry.node_type : 'directory'
      const node = ensureNode(cursor, segment, currentPath, nodeType)
      cursor = node._childrenMap
    })
  })

  const toArray = (children: Map<string, TreeNode>): SkillFileNode[] => (
    [...children.values()]
      .sort((a, b) => {
        if (a.node_type !== b.node_type) {
          return a.node_type === 'directory' ? -1 : 1
        }
        return a.name.localeCompare(b.name)
      })
      .map((node) => ({
        path: node.path,
        name: node.name,
        node_type: node.node_type,
        children: toArray(node._childrenMap),
      }))
  )

  return toArray(rootMap)
}

export const collectDirectoryPaths = (nodes: SkillFileNode[]) => {
  const directories = new Set<string>([''])
  const walk = (items: SkillFileNode[]) => {
    items.forEach((item) => {
      if (item.node_type !== 'directory') return
      directories.add(item.path)
      walk(item.children || [])
    })
  }
  walk(nodes)
  return [...directories].sort((a, b) => a.localeCompare(b))
}

export const pickDefaultFilePath = (fileTree: SkillFileNode[], entryFilePath: string) => {
  const paths = flattenFiles(fileTree)
  if (entryFilePath && paths.includes(entryFilePath)) return entryFilePath
  return paths[0] || ''
}
