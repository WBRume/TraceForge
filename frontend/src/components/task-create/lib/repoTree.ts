import type { RepoGroupTreeNode } from '@/types/management'
import type { RepoSelectTreeNode, RepoSelectTreeRepo } from '@/components/workspace/create-workflow/RepoSelectTree.vue'
import type { WorkspaceRepo } from '../types'

/** “未分组”虚拟节点的 key（不与真实分组 id 冲突） */
export const UNGROUPED_NODE_KEY = '__ungrouped__'

/** 工作区仓库的绑定 id：优先 repository_id，回退仓库行自身 id */
export const workspaceRepoBindingId = (repo: WorkspaceRepo): string =>
  String(repo.repository_id || repo.id || '')

/**
 * 将工作区仓库挂载到仓库管理分组树上（纯函数）：
 * - 命中分组的仓库挂到对应组节点；未命中的进入“未分组”虚拟节点
 * - 没有任何仓库的分支被剪枝，避免展开一串空组
 */
export function buildRepoTreeNodes(
  groups: RepoGroupTreeNode[],
  repos: WorkspaceRepo[],
  ungroupedLabel: string,
): RepoSelectTreeNode[] {
  const groupIdByRepoId = new Map<string, string>()
  const nodeByKey = new Map<string, RepoSelectTreeNode>()

  const walkGroups = (items: RepoGroupTreeNode[]): void => {
    for (const item of items) {
      if (item.id) {
        const node: RepoSelectTreeNode = { key: item.id, name: item.name, repos: [], children: [] }
        nodeByKey.set(item.id, node)
        for (const r of item.repositories || []) {
          groupIdByRepoId.set(r.id, item.id)
        }
      }
      walkGroups(item.children || [])
    }
  }
  walkGroups(groups)

  const toTreeRepo = (repo: WorkspaceRepo): RepoSelectTreeRepo => ({
    id: workspaceRepoBindingId(repo),
    name: repo.repo_name,
    git_url: repo.repo_url,
  })

  const ungrouped: RepoSelectTreeRepo[] = []
  for (const repo of repos) {
    const repoId = workspaceRepoBindingId(repo)
    if (!repoId) continue
    const groupId = groupIdByRepoId.get(repoId)
    if (groupId && nodeByKey.has(groupId)) {
      nodeByKey.get(groupId)!.repos.push(toTreeRepo(repo))
    } else {
      ungrouped.push(toTreeRepo(repo))
    }
  }

  const build = (items: RepoGroupTreeNode[]): RepoSelectTreeNode[] => {
    const result: RepoSelectTreeNode[] = []
    for (const item of items) {
      const node = item.id ? nodeByKey.get(item.id) : undefined
      if (!node) continue
      const children = build(item.children || [])
      if (node.repos.length === 0 && children.length === 0) continue
      result.push({ ...node, children })
    }
    return result
  }

  const result = build(groups)
  if (ungrouped.length > 0) {
    result.push({ key: UNGROUPED_NODE_KEY, name: ungroupedLabel, repos: ungrouped, children: [] })
  }
  return result
}
