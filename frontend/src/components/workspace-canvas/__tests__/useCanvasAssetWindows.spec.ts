import { effectScope } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import api from '@/utils/api'
import { referenceKey, type CanvasAsset, type CanvasAssetWindow, type SourceReference } from '../model'
import { useCanvasAssetWindows } from '../useCanvasAssetWindows'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn() } }))

function asset(reference: SourceReference): CanvasAsset {
  return { reference, node_id: reference.id, details: { title: reference.id, status: null,
    detail: null, context: null, version: null, historical: false, task_id: null } }
}

function windowWith(assets: CanvasAsset[], next_cursor: string | null = null): CanvasAssetWindow {
  return { assets, next_cursor, relations: assets.slice(1).map(child => ({
    source: child.reference, target: assets[0].reference,
    relation_type: child.reference.kind === 'document' ? 'DOCUMENT_TASK' : 'COVERS',
  })) }
}

describe('workspace canvas branch windows', () => {
  it('keeps existing siblings, open subtrees and cursor continuity as a branch grows', async () => {
    const root = asset({ kind: 'requirement', id: 'root' })
    const first = asset({ kind: 'task', id: 'first' })
    const next = asset({ kind: 'task', id: 'next' })
    const doc = asset({ kind: 'document', id: 'doc' })
    const added = asset({ kind: 'task', id: 'added' })
    const scope = effectScope()
    const state = scope.run(() => useCanvasAssetWindows('workspace', () => '2026-Q4', () => [root]))!
    const rootKey = referenceKey(root.reference)
    const get = vi.mocked(api.get)
    try {
      get.mockResolvedValueOnce({ data: windowWith([root, first], 'task:first') })
        .mockResolvedValueOnce({ data: windowWith([first, doc]) })
        .mockResolvedValueOnce({ data: windowWith([root, first, next], 'task:next') })
        .mockResolvedValueOnce({ data: windowWith([root, added], 'task:added') })
      await state.load(root.reference, { children: true })
      await state.load(first.reference, { children: true })
      await state.load(root.reference, { cursor: 'task:first' })
      await state.load(root.reference, { reveal: added.reference })
      expect(state.treeParents.value).toEqual(new Map([['first', 'root'], ['next', 'root'], ['added', 'root'], ['doc', 'first']]))
      expect(state.expanded.value.get(rootKey)?.cursor).toBe('task:next')

      get.mockResolvedValueOnce({ data: windowWith([root, first, added], 'task:added') })
        .mockResolvedValueOnce({ data: windowWith([root, next]) })
        .mockResolvedValueOnce({ data: windowWith([root, added]) })
        .mockResolvedValueOnce({ data: windowWith([first, doc]) })
      await state.sync()
      expect(get.mock.calls[5][1]?.params.cursor).toBe('task:added')
      expect(state.treeParents.value.get('doc')).toBe('first')
      expect(state.treeParents.value.get('next')).toBe('root')
      expect(state.expanded.value.get(rootKey)?.cursor).toBeNull()
      state.collapse(root.reference)
      expect(state.treeParents.value.size).toBe(0)
      expect(state.expanded.value.size).toBe(0)
    } finally {
      scope.stop()
      get.mockReset()
    }
  })
})
