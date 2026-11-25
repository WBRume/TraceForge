import { describe, expect, it } from 'vitest'
import { layoutWorkspaceAssets } from '../assetLayout'
import { frameMembers } from '../geometry'
import { nodeSizes, type CanvasAsset, type CanvasNode, type CanvasSnapshot, type SourceReference } from '../model'

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

  it('points a document at both business owners without using a pinned paragraph as an endpoint', () => {
    const state = snapshot()
    function asset(id: string, reference: SourceReference): CanvasAsset {
      return { node_id: id, reference, details: { ...state.assets[0]!.details, title: id } }
    }
    const requirement = asset('asset-requirement', { kind: 'requirement', id: 'requirement' })
    const document = asset('asset-document', { kind: 'document', id: 'document' })
    const file = asset('asset-file', { kind: 'plan_document', id: 'task', section: 'plans', path: 'plan.md' })
    state.assets.push(requirement, document)
    state.nodes.push({
      id: 'paragraph', kind: 'card', position: { x: 30, y: 340 }, size: nodeSizes.card, color: 'blue', text: '',
      reference: { kind: 'document', id: 'document', block: 'paragraph' }, details: document.details,
    })
    state.relations = [
      { source: document.reference, target: state.assets[0]!.reference, relation_type: 'DOCUMENT_TASK' },
      { source: document.reference, target: requirement.reference, relation_type: 'DOCUMENT_REQUIREMENT' },
    ]

    const graph = layoutWorkspaceAssets(state, [file])

    expect(graph.relations.map(row => [row.sourceNodeId, row.targetNodeId, row.relation_type])).toEqual([
      ['asset-document', 'asset-task', 'DOCUMENT_TASK'],
      ['asset-document', 'asset-requirement', 'DOCUMENT_REQUIREMENT'],
      ['asset-file', 'asset-task', 'DOCUMENT_TASK'],
    ])
  })
})
