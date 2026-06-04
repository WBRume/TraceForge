<script setup lang="ts">
import { shallowRef, computed, onBeforeUnmount, watch } from 'vue'
import { VueMonacoDiffEditor } from '@guolao/vue-monaco-editor'
import type * as Monaco from 'monaco-editor'
import type { DiffHunk } from '@/types/workspaceAssets'

const props = defineProps<{
  aiHunks: DiffHunk[]
  humanHunks: DiffHunk[]
  language?: string
  height?: string
}>()

const emit = defineEmits<{
  'range-select': [payload: { lineStart: number; lineEnd: number; side: 'ai' | 'human'; selectedText: string }]
}>()

const diffEditorRef = shallowRef<Monaco.editor.IStandaloneDiffEditor | null>(null)
const monacoRef = shallowRef<typeof Monaco | null>(null)

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

const originalText = computed(() => extractOutputText(props.aiHunks))
const modifiedText = computed(() => extractOutputText(props.humanHunks))

const diffEditorOptions: Monaco.editor.IDiffEditorConstructionOptions = {
  automaticLayout: true,
  readOnly: true,
  renderSideBySide: true,
  originalEditable: false,
  enableSplitViewResizing: true,
  minimap: { enabled: false },
  lineNumbers: 'on',
  lineNumbersMinChars: 3,
  scrollBeyondLastLine: false,
  wordWrap: 'off',
  fontSize: 13,
  fontFamily: "'Consolas', 'Monaco', 'Courier New', monospace",
  renderLineHighlight: 'none',
  overviewRulerBorder: false,
  scrollbar: {
    verticalScrollbarSize: 8,
    horizontalScrollbarSize: 8,
  },
}

function handleDiffMount(editor: Monaco.editor.IStandaloneDiffEditor, monaco: typeof Monaco) {
  diffEditorRef.value = editor
  monacoRef.value = monaco

  const modifiedEditor = editor.getModifiedEditor()

  modifiedEditor.onMouseUp(() => {
    const selection = modifiedEditor.getSelection()
    if (!selection || selection.isEmpty()) return
    const model = modifiedEditor.getModel()
    if (!model) return

    const start = selection.getStartPosition()
    const end = selection.getEndPosition()
    const selectedText = model.getValueInRange(selection)

    emit('range-select', {
      lineStart: start.lineNumber,
      lineEnd: end.lineNumber,
      side: 'human',
      selectedText,
    })
  })
}

watch(() => [props.aiHunks, props.humanHunks], () => {
  if (diffEditorRef.value) {
    diffEditorRef.value.revealFirstDiff()
  }
})

onBeforeUnmount(() => {
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
      theme="vs-dark"
      :options="diffEditorOptions"
      width="100%"
      :height="height || '100%'"
      @mount="handleDiffMount"
    />
  </div>
</template>

<style scoped>
.monaco-diff-viewer {
  width: 100%;
  height: 100%;
  min-height: 200px;
  border-radius: 8px;
  overflow: hidden;
}
</style>
