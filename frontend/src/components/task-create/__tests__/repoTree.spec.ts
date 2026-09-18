import { describe, expect, it } from 'vitest'
import { buildRepoTreeNodes, UNGROUPED_NODE_KEY, workspaceRepoBindingId } from '../lib/repoTree'
import type { RepoGroupTreeNode } from '@/types/management'
import type { WorkspaceRepo } from '../types'

const groupNode = (
  id: string | null,
  name: string,
  overrides: Partial<RepoGroupTreeNode> = {},
): RepoGroupTreeNode => ({
  id,
  parent_id: null,
  name,
  order_index: 0,
  repositories: [],
  children: [],
  ...overrides,
})

const managedRepo = (id: string): RepoGroupTreeNode['repositories'][number] => ({
  id,
  name: `managed-${id}`,
  git_url: `git@github.com:org/${id}.git`,
  repo_type: 'CUSTOM',
})

const workspaceRepo = (id: string, name = id): WorkspaceRepo => ({
  repository_id: id,
  repo_name: name,
  repo_url: `git@github.com:org/${name}.git`,
})

describe('workspaceRepoBindingId', () => {
  it('prefers repository_id over the repo row id', () => {
    expect(workspaceRepoBindingId({ repository_id: 'r-1', id: 'row-9', repo_name: '', repo_url: '' })).toBe('r-1')
    expect(workspaceRepoBindingId({ id: 'row-9', repo_name: '', repo_url: '' })).toBe('row-9')
    expect(workspaceRepoBindingId({ repo_name: '', repo_url: '' })).toBe('')
  })
})

describe('buildRepoTreeNodes', () => {
  it('mounts workspace repos under their managed groups and prunes empty sub-groups', () => {
    const groups = [
      groupNode('g1', '平台', {
        repositories: [managedRepo('r-1')],
        children: [groupNode('g2', '空子组')],
      }),
    ]
    const nodes = buildRepoTreeNodes(groups, [workspaceRepo('r-1', 'frontend'), workspaceRepo('r-2', 'backend')], '未分组')

    expect(nodes).toHaveLength(2)
    expect(nodes[0].name).toBe('平台')
    expect(nodes[0].repos.map((r) => r.id)).toEqual(['r-1'])
    expect(nodes[0].children).toHaveLength(0)
    // 未命中分组的仓库进入“未分组”
    expect(nodes[1].key).toBe(UNGROUPED_NODE_KEY)
    expect(nodes[1].repos.map((r) => r.name)).toEqual(['backend'])
  })

  it('prunes fully empty groups and keeps the ungrouped node last', () => {
    const groups = [
      groupNode('g-empty', '空组'),
      groupNode('g2', '有仓库', { repositories: [managedRepo('r-2')] }),
    ]
    const nodes = buildRepoTreeNodes(groups, [workspaceRepo('r-1', 'standalone'), workspaceRepo('r-2', 'backend')], '未分组')

    expect(nodes.map((n) => n.name)).toEqual(['有仓库', '未分组'])
    expect(nodes[1].key).toBe(UNGROUPED_NODE_KEY)
    expect(nodes[1].repos.map((r) => r.name)).toEqual(['standalone'])
  })

  it('keeps nested groups that contain repos', () => {
    const groups = [
      groupNode('g1', '父组', {
        children: [groupNode('g2', '子组', { repositories: [managedRepo('r-1')] })],
      }),
    ]
    const nodes = buildRepoTreeNodes(groups, [workspaceRepo('r-1', 'frontend')], '未分组')

    expect(nodes).toHaveLength(1)
    expect(nodes[0].children).toHaveLength(1)
    expect(nodes[0].children[0].repos.map((r) => r.id)).toEqual(['r-1'])
  })

  it('returns an empty tree when there are neither groups nor repos', () => {
    expect(buildRepoTreeNodes([], [], '未分组')).toEqual([])
  })
})
