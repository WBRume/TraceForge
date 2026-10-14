import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MonacoDiffViewer from '../MonacoDiffViewer.vue'
import { effectScope } from 'vue'
import { contextAnnotationsKey, useContextAnnotations } from '@/composables/chat/annotations/useContextAnnotations'

vi.mock('@/utils/monaco', () => ({ ensureMonacoViteSetup: vi.fn() }))
vi.mock('@guolao/vue-monaco-editor', () => ({ VueMonacoDiffEditor: { name: 'Monaco', props:['options'], template: '<div />' } }))

describe('Diff gutter IDE navigation', () => {
  it('emits edits only for the editable task pane and disposes detached models', async () => {
    const wrapper = mount(MonacoDiffViewer, { props:{ original:'remote', modified:'task' } })
    let changed!: () => void
    const pane = { getValue:() => 'edited task', createDecorationsCollection:() => ({ set:vi.fn(), clear:vi.fn() }),
      onDidChangeModelContent:(fn: () => void) => { changed = fn; return { dispose:vi.fn() } },
      ...Object.fromEntries(['onMouseMove','onMouseLeave','onMouseDown','onMouseUp'].map(name => [name, () => ({ dispose:vi.fn() })])),
    }
    const models = { original:{ dispose:vi.fn() }, modified:{ dispose:vi.fn() } }
    wrapper.findComponent({ name:'Monaco' }).vm.$emit('mount', { getOriginalEditor:() => pane, getModifiedEditor:() => pane, getModel:() => models, setModel:vi.fn() }, {})
    changed(); expect(wrapper.emitted('update:modified')).toBeUndefined()
    await wrapper.setProps({ editable:true })
    expect(wrapper.findComponent({ name:'Monaco' }).props('options')).toMatchObject({ readOnly:false, originalEditable:false })
    changed(); expect(wrapper.emitted('update:modified')).toEqual([['edited task']])
    await wrapper.setProps({ modified:'edited task' }); changed()
    expect(wrapper.emitted('update:modified')).toHaveLength(1)
    wrapper.unmount()
    expect(models.original.dispose).toHaveBeenCalledOnce(); expect(models.modified.dispose).toHaveBeenCalledOnce()
  })
  it('captures both panes with path, revision and exact selection coordinates', () => {
    const scope = effectScope()
    const annotations = scope.run(() => useContextAnnotations(() => 'task'))!
    const wrapper = mount(MonacoDiffViewer, { props: { filePath: 'repo/a.ts', original: 'old', modified: 'new', originalRevision: 'old-hash', modifiedRevision: 'new-hash' }, global: { provide: { [contextAnnotationsKey as symbol]: annotations } } })
    const makePane = () => {
      const callbacks: Record<string, (event?: any) => void> = {}
      return { callbacks, pane: {
        createDecorationsCollection: () => ({ set: vi.fn(), clear: vi.fn() }),
        getSelection: () => ({ isEmpty: () => false, getStartPosition: () => ({ lineNumber: 35, column: 3 }), getEndPosition: () => ({ lineNumber: 37, column: 1 }) }),
        getModel: () => ({ getValueInRange: () => 'selected\ncode\n' }),
        getDomNode: () => ({ getBoundingClientRect: () => ({ left: 10, top: 20 }) }),
        getScrolledVisiblePosition: () => ({ left: 10, top: 15, height: 20 }),
        ...Object.fromEntries(['onDidChangeModelContent', 'onMouseMove', 'onMouseLeave', 'onMouseDown', 'onMouseUp', 'onKeyUp'].map(name => [name, (fn: () => void) => { callbacks[name] = fn; return { dispose: vi.fn() } }])),
      } }
    }
    const original = makePane(), modified = makePane()
    wrapper.findComponent({ name: 'Monaco' }).vm.$emit('mount', { getOriginalEditor: () => original.pane, getModifiedEditor: () => modified.pane, setModel: vi.fn(), getModel: () => null }, {})
    original.callbacks.onMouseUp!()
    expect(annotations.pending.value).toMatchObject({ selectedText: 'selected\ncode\n', source: { filePath: 'repo/a.ts', side: 'original', revision: 'old-hash', lineStart: 35, lineEnd: 36, selectionEndLine: 37, startColumn: 3, endColumn: 1 } })
    annotations.dismiss()
    modified.callbacks.onKeyUp!({ browserEvent: { key: 'Escape' } })
    expect(annotations.pending.value).toBeNull()
    modified.callbacks.onKeyUp!({ browserEvent: { key: 'Shift' } })
    expect(annotations.pending.value?.source).toMatchObject({ side: 'modified', revision: 'new-hash' })
    wrapper.unmount(); scope.stop()
  })
  it('opens the exact clicked line on either side and disposes listeners on close', () => {
    const wrapper = mount(MonacoDiffViewer, { props: { original: 'old', modified: 'new', openInIde: true } })
    const makePane = () => {
      const callbacks: Record<string, (event?: any) => void> = {}
      const dispose = vi.fn(), glyphs = { set: vi.fn(), clear: vi.fn() }
      const pane = { createDecorationsCollection: () => glyphs,
        ...Object.fromEntries(['onDidChangeModelContent', 'onMouseMove', 'onMouseLeave', 'onMouseDown', 'onMouseUp'].map(name => [name, (fn: any) => { callbacks[name] = fn; return { dispose } }])),
      }
      return { pane, callbacks, dispose, glyphs }
    }
    const original = makePane(), modified = makePane(), setModel = vi.fn()
    wrapper.findComponent({ name: 'Monaco' }).vm.$emit('mount', { getOriginalEditor: () => original.pane, getModifiedEditor: () => modified.pane, setModel, getModel: () => null },
      { Range: class { startLineNumber: number; constructor(line: number) { this.startLineNumber = line } }, editor: { MouseTargetType: { GUTTER_GLYPH_MARGIN: 2 } } })
    original.callbacks.onMouseMove!({ target: { position: { lineNumber: 12 } } })
    expect(original.glyphs.set.mock.calls[0]![0][0].range.startLineNumber).toBe(12)
    original.callbacks.onMouseDown!({ target: { type: 2, position: { lineNumber: 12 } } })
    modified.callbacks.onMouseDown!({ target: { type: 2, position: { lineNumber: 24 } } })
    modified.callbacks.onMouseDown!({ target: { type: 6, position: { lineNumber: 30 } } })
    expect(wrapper.emitted('open-in-ide')).toEqual([[{ line: 12, column: 1 }], [{ line: 24, column: 1 }]])
    wrapper.unmount()
    expect(original.dispose).toHaveBeenCalledTimes(4)
    expect(modified.dispose).toHaveBeenCalledTimes(5)
  })
})
