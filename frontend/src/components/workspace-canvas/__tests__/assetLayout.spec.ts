import { describe, expect, it } from 'vitest'
import { layoutWorkspaceAssets } from '../assetLayout'
import { frameMembers } from '../geometry'
import { nodeSizes, type CanvasNode, type CanvasSnapshot } from '../model'

function snapshot(nodes: CanvasNode[] = []): CanvasSnapshot {
  return {
    revision: 0,
    assets: [{
      node_id: 'asset-task', reference: { kind: 'task', id: 'task' },
      details: { title: 'Task', status: 'RUNNING', detail: null, context: null, version: null, historical: false,
        task_id: null },
    }],
    nodes,
    edges: [],
    relations: [],
    access: { source_kinds: ['task'], can_link_requirements: false },
  }
}

describe('workspace asset layout', () => {
  it('keeps an automatic card inside a frame drawn around it', () => {
    const card = layoutWorkspaceAssets(snapshot(), []).nodes[0]!
    const frame: CanvasNode = {
      id: 'frame', kind: 'frame', position: { x: card.position.x - 20, y: card.position.y - 20 },
      size: { width: 330, height: 220 }, color: 'blue', text: 'Related assets', reference: null, details: null,
    }
    const graph = layoutWorkspaceAssets(snapshot([frame]), [])

    expect(frameMembers(frame, graph.nodes).map(node => node.id)).toEqual([card.id])
    expect(graph.nodes.find(node => node.id === card.id)?.position).toEqual(card.position)
  })

  it('uses the shared layout only once for an existing source card', () => {
    const saved: CanvasNode = {
      id: 'older-card', kind: 'card', position: { x: -21, y: 20 }, size: nodeSizes.card, color: 'yellow', text: '',
      reference: { kind: 'task', id: 'task' }, details: null,
    }

    expect(layoutWorkspaceAssets(snapshot([saved]), []).nodes).toEqual([{ ...saved, automatic: true }])
  })
})
