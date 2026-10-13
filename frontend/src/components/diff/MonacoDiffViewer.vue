<script setup lang="ts">
import { shallowRef, computed, onBeforeUnmount, watch } from 'vue'
import { VueMonacoDiffEditor } from '@guolao/vue-monaco-editor'
import type * as Monaco from 'monaco-editor'
import type { DiffHunk } from '@/types/workspaceAssets'
import { ensureMonacoViteSetup } from '@/utils/monaco'
import { injectContextAnnotations } from '@/composables/chat/annotations/useContextAnnotations'

const props = defineProps<{
  aiHunks?: DiffHunk[]
  humanHunks?: DiffHunk[]
  original?: string
  modified?: string
  renderSideBySide?: boolean
  wordWrap?: 'on' | 'off'
  language?: string
  theme?: 'vs' | 'vs-dark'
  height?: string
  openInIde?: boolean
  ideTitle?: string
  filePath?: string
  originalLabel?: string
  modifiedLabel?: string
  originalRevision?: string
  modifiedRevision?: string
}>()
ensureMonacoViteSetup()

const emit = defineEmits<{
  'open-in-ide': [position: { line: number; column: number }]
  'range-select': [payload: { lineStart: number; lineEnd: number; side: 'ai' | 'human'; selectedText: string }]
}>()

const diffEditorRef = shallowRef<Monaco.editor.IStandaloneDiffEditor | null>(null)
const monacoRef = shallowRef<typeof Monaco | null>(null)
const disposables: Monaco.IDisposable[] = []
const annotations = injectContextAnnotations()

watch(() => [props.filePath, props.original, props.modified], () => annotations?.dismiss())

function extractOutputText(hunks: DiffHunk[]): string {
  const lines: string[] = []
  for (const hunk of hunks) {
    for (const line of hunk.lines) {
      if (line.type === 'add' || line.type === 'context') {
        lines.push(line.content)
      }
    }
  }
  return lines.join('\n')
}

const originalText = computed(() => props.original ?? extractOutputText(props.aiHunks || []))
const modifiedText = computed(() => props.modified ?? extractOutputText(props.humanHunks || []))

const diffEditorOptions = computed<Monaco.editor.IDiffEditorConstructionOptions>(() => ({
  automaticLayout: true,
  readOnly: true,
  renderSideBySide: props.renderSideBySide !== false,
  useInlineViewWhenSpaceIsLimited: false,
  originalEditable: false,
  enableSplitViewResizing: true,
  minimap: { enabled: false },
  lineNumbers: 'on',
  glyphMargin: Boolean(props.openInIde),
  lineNumbersMinChars: 3,
  scrollBeyondLastLine: false,
  wordWrap: props.wordWrap || 'off',
  fontSize: 13,
  fontFamily: "'Consolas', 'Monaco', 'Courier New', monospace",
  renderLineHighlight: 'none',
  renderOverviewRuler: false,
  overviewRulerBorder: false,
  scrollbar: {
    verticalScrollbarSize: 8,
    horizontalScrollbarSize: 8,
  },
}))

function handleDiffMount(editor: Monaco.editor.IStandaloneDiffEditor, monaco: typeof Monaco) {
  diffEditorRef.value = editor
  monacoRef.value = monaco

  const modifiedEditor = editor.getModifiedEditor()

  for (const pane of [editor.getOriginalEditor(), modifiedEditor]) {
    const glyphs = pane.createDecorationsCollection()
    let hoveredLine = 0
    disposables.push(pane.onMouseMove(event => {
      const line = props.openInIde ? event.target.position?.lineNumber || 0 : 0
      if (line === hoveredLine) return
      hoveredLine = line
      glyphs.set(line ? [{ range: new monaco.Range(line, 1, line, 1), options: {
        glyphMarginClassName: 'traceforge-open-in-ide',
        glyphMarginHoverMessage: { value: props.ideTitle || '在 IDE 中打开本地文件' },
      } }] : [])
    }), pane.onMouseLeave(() => { hoveredLine = 0; glyphs.clear() }), pane.onMouseDown(event => {
      if (props.openInIde && event.target.type === monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN && event.target.position) {
        emit('open-in-ide', { line: event.target.position.lineNumber, column: 1 })
      }
    }))
  }

  for (const [pane, side] of [[editor.getOriginalEditor(), 'original'], [modifiedEditor, 'modified']] as const) {
    const select = () => {
      const selection = pane.getSelection()
      if (!selection || selection.isEmpty()) { annotations?.dismiss(); return }
      const model = pane.getModel()
      if (!model) return

      const start = selection.getStartPosition()
      const end = selection.getEndPosition()
      const selectedText = model.getValueInRange(selection)

      emit('range-select', {
        lineStart: start.lineNumber,
        lineEnd: end.column === 1 && end.lineNumber > start.lineNumber ? end.lineNumber - 1 : end.lineNumber,
        side: side === 'original' ? 'ai' : 'human',
        selectedText,
      })
      if (!props.filePath || !annotations) return
      const rect = pane.getDomNode()?.getBoundingClientRect()
      const position = pane.getScrolledVisiblePosition(end)
      annotations.select({ selectedText, source: {
        kind: 'diff', filePath: props.filePath, side,
        version: side === 'original' ? props.originalLabel : props.modifiedLabel,
        revision: side === 'original' ? props.originalRevision : props.modifiedRevision,
        lineStart: start.lineNumber,
        lineEnd: end.column === 1 && end.lineNumber > start.lineNumber ? end.lineNumber - 1 : end.lineNumber,
        startColumn: start.column, endColumn: end.column,
        selectionEndLine: end.lineNumber,
      } }, { x: (rect?.left || 0) + (position?.left || 0), y: (rect?.top || 0) + (position?.top || 0) + (position?.height || 20) + 6 })
    }
    disposables.push(pane.onMouseUp(select))
    if (annotations) disposables.push(pane.onKeyUp(event => { if (event.browserEvent.key !== 'Escape') select() }))
  }
}

watch(() => [props.aiHunks, props.humanHunks], () => {
  if (diffEditorRef.value) {
    diffEditorRef.value.revealFirstDiff()
  }
})

onBeforeUnmount(() => {
  annotations?.dismiss()
  disposables.forEach(item => item.dispose())
  if (diffEditorRef.value) {
    diffEditorRef.value.setModel(null)
  }
})
</script>

<template>
  <div class="monaco-diff-viewer">
    <VueMonacoDiffEditor
      :original="originalText"
      :modified="modifiedText"
      :language="language || 'plaintext'"
      :theme="theme || 'vs-dark'"
      :options="diffEditorOptions"
      width="100%"
      :height="height || '100%'"
      @mount="handleDiffMount"
    />
  </div>
</template>

<style scoped>
:deep(.traceforge-open-in-ide) {
  cursor: pointer;
  background: center / 13px 13px no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='none' stroke='%230284c7' stroke-width='1.5'%3E%3Cpath d='M9 2h5v5M14 2 7 9M7 3H3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V9'/%3E%3C/svg%3E");
}
.monaco-diff-viewer {
  width: 100%;
  height: 100%;
  min-height: 200px;
  border-radius: 8px;
  overflow: hidden;
}
</style>
