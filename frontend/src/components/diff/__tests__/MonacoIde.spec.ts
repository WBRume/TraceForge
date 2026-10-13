import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MonacoDiffViewer from '../MonacoDiffViewer.vue'

vi.mock('@/utils/monaco', () => ({ ensureMonacoViteSetup: vi.fn() }))
vi.mock('@guolao/vue-monaco-editor', () => ({ VueMonacoDiffEditor: { name: 'Monaco', template: '<div />' } }))

describe('Diff gutter IDE navigation', () => {
  it('opens the exact clicked line on either side and disposes listeners on close', () => {
    const wrapper = mount(MonacoDiffViewer, { props: { original: 'old', modified: 'new', openInIde: true } })
    const makePane = () => {
      const callbacks: Record<string, (event?: any) => void> = {}
      const dispose = vi.fn(), glyphs = { set: vi.fn(), clear: vi.fn() }
      const pane = { createDecorationsCollection: () => glyphs,
        ...Object.fromEntries(['onMouseMove', 'onMouseLeave', 'onMouseDown', 'onMouseUp'].map(name => [name, (fn: any) => { callbacks[name] = fn; return { dispose } }])),
      }
      return { pane, callbacks, dispose, glyphs }
    }
    const original = makePane(), modified = makePane(), setModel = vi.fn()
    wrapper.findComponent({ name: 'Monaco' }).vm.$emit('mount', { getOriginalEditor: () => original.pane, getModifiedEditor: () => modified.pane, setModel },
      { Range: class { startLineNumber: number; constructor(line: number) { this.startLineNumber = line } }, editor: { MouseTargetType: { GUTTER_GLYPH_MARGIN: 2 } } })
    original.callbacks.onMouseMove!({ target: { position: { lineNumber: 12 } } })
    expect(original.glyphs.set.mock.calls[0]![0][0].range.startLineNumber).toBe(12)
    original.callbacks.onMouseDown!({ target: { type: 2, position: { lineNumber: 12 } } })
    modified.callbacks.onMouseDown!({ target: { type: 2, position: { lineNumber: 24 } } })
    modified.callbacks.onMouseDown!({ target: { type: 6, position: { lineNumber: 30 } } })
    expect(wrapper.emitted('open-in-ide')).toEqual([[{ line: 12, column: 1 }], [{ line: 24, column: 1 }]])
    wrapper.unmount()
    expect(original.dispose).toHaveBeenCalledTimes(3)
    expect(modified.dispose).toHaveBeenCalledTimes(3)
  })
})
