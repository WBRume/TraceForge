<script setup lang="ts">
import { computed, ref } from 'vue'

export type DiffLineClickEvent = {
  lineNumber: number
  text: string
  type: string
  filePath: string | null
}

export type DiffRangeSelectEvent = {
  filePath: string
  lineStart: number
  lineEnd: number
  selectedText: string
}

const props = withDefaults(defineProps<{
  diffText: string
  selectedFilePath?: string | null
  maxHeight?: string
  loading?: boolean
  clickable?: boolean
  rangeSelectable?: boolean
}>(), {
  selectedFilePath: null,
  maxHeight: '100%',
  loading: false,
  clickable: false,
  rangeSelectable: false,
})

const emit = defineEmits<{
  (e: 'line-click', payload: DiffLineClickEvent): void
  (e: 'range-select', payload: DiffRangeSelectEvent): void
}>()

const displayText = computed(() => {
  if (!props.diffText) return ''

  if (props.selectedFilePath) {
    const escapedPath = props.selectedFilePath.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const regex = new RegExp(`diff --git a/${escapedPath} b/${escapedPath}[\\s\\S]*?(?=diff --git|$)`)
    const match = props.diffText.match(regex)
    return match ? match[0] : ''
  }

  const lines = props.diffText.split('\n')
  const MAX_LINES = 3000
  if (lines.length > MAX_LINES) {
    return `${lines.slice(0, MAX_LINES).join('\n')}\n\n... (${lines.length} lines total, truncated)`
  }

  return props.diffText
})

const highlightedLines = computed(() => {
  const text = displayText.value
  if (!text) return []

  let currentFile: string | null = null

  return text.split('\n').map((line) => {
    let type = 'plain'
    if (line.startsWith('+') && !line.startsWith('+++')) type = 'add'
    else if (line.startsWith('-') && !line.startsWith('---')) type = 'del'
    else if (line.startsWith('@@')) type = 'hunk'
    else if (line.startsWith('diff --git')) {
      type = 'header'
      const match = line.match(/diff --git a\/(.+?) b\//)
      if (match) currentFile = match[1]
    }
    else if (line.startsWith('index ') || line.startsWith('new file mode ') || line.startsWith('deleted file mode ')) type = 'header'
    else if (line.startsWith('--- ') || line.startsWith('+++ ')) {
      type = 'file'
      if (line.startsWith('+++ b/')) currentFile = line.slice(6)
    }

    return { text: line || ' ', type, filePath: currentFile }
  })
})

// --- Range selection state ---
const isDragging = ref(false)
const selectionAnchor = ref<number | null>(null)
const selectionHead = ref<number | null>(null)

const selectedRange = computed(() => {
  if (selectionAnchor.value === null || selectionHead.value === null) return null
  const start = Math.min(selectionAnchor.value, selectionHead.value)
  const end = Math.max(selectionAnchor.value, selectionHead.value)
  return { start, end }
})

function isSelectable(line: { type: string }) {
  return line.type !== 'header' && line.type !== 'hunk' && line.type !== 'file'
}

function isLineSelected(idx: number) {
  const range = selectedRange.value
  if (!range) return false
  if (idx < range.start || idx > range.end) return false
  return isSelectable(highlightedLines.value[idx])
}

function handleMouseDown(idx: number, line: { text: string; type: string; filePath: string | null }) {
  if (!props.rangeSelectable) return
  if (!isSelectable(line)) return
  isDragging.value = true
  selectionAnchor.value = idx
  selectionHead.value = idx
}

function handleMouseMove(idx: number) {
  if (!isDragging.value) return
  selectionHead.value = idx
}

function commitRangeSelection() {
  const range = selectedRange.value
  if (!range) return
  const lines = highlightedLines.value
  let filePath: string | null = null
  const selectedLines: string[] = []
  for (let i = range.start; i <= range.end; i++) {
    const line = lines[i]
    if (!line || !isSelectable(line)) continue
    if (!filePath && line.filePath) filePath = line.filePath
    selectedLines.push(line.text)
  }
  if (!filePath || !selectedLines.length) {
    clearSelection()
    return
  }
  emit('range-select', {
    filePath,
    lineStart: range.start + 1,
    lineEnd: range.end + 1,
    selectedText: selectedLines.join('\n'),
  })
}

function clearSelection() {
  isDragging.value = false
  selectionAnchor.value = null
  selectionHead.value = null
}

function handleMouseUp() {
  if (!isDragging.value) return
  isDragging.value = false
  commitRangeSelection()
}

function handleLineClick(idx: number, line: { text: string; type: string; filePath: string | null }) {
  if (!props.clickable) return
  if (!isSelectable(line)) return
  emit('line-click', {
    lineNumber: idx + 1,
    text: line.text,
    type: line.type,
    filePath: line.filePath,
  })
}
</script>

<template>
  <div class="diff-viewer" :style="{ maxHeight }">
    <div v-if="loading" class="diff-loading">
      <span>Loading diff...</span>
    </div>
    <div v-else-if="!highlightedLines.length" class="diff-empty">
      <span>No diff content available</span>
    </div>
    <div
      v-else
      class="diff-lines"
      @mouseup="handleMouseUp"
      @mouseleave="handleMouseUp"
    >
      <div
        v-for="(line, idx) in highlightedLines"
        :key="idx"
        :class="['diff-line', line.type, {
          clickable: (clickable || rangeSelectable) && isSelectable(line),
          selected: isLineSelected(idx),
          'range-anchor': selectionAnchor === idx,
        }]"
        @click="handleLineClick(idx, line)"
        @mousedown="handleMouseDown(idx, line)"
        @mousemove="handleMouseMove(idx)"
      >
        <span class="line-number">{{ idx + 1 }}</span>
        <span class="line-content">{{ line.text }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.diff-viewer {
  overflow: auto;
  background: #0f172a;
  border-radius: 8px;
  font-family: var(--font-mono, 'Consolas', 'Monaco', monospace);
  font-size: 0.8125rem;
  line-height: 1.5;
  contain: layout size;
}

.diff-loading,
.diff-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  color: #94a3b8;
  font-size: 0.875rem;
}

.diff-lines {
  padding: 1rem 0;
  counter-reset: line;
  contain: layout style;
}

.diff-line {
  display: flex;
  white-space: pre;
  min-width: fit-content;
  contain: layout style;
}

.diff-line:hover {
  background: rgba(255, 255, 255, 0.03);
}
.diff-line.clickable {
  cursor: pointer;
}
.diff-line.clickable:hover {
  background: rgba(255, 255, 255, 0.06);
}

.line-number {
  width: 45px;
  padding: 0 10px;
  text-align: right;
  color: #475569;
  user-select: none;
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  margin-right: 12px;
  font-size: 0.7rem;
}

.line-content {
  flex: 1;
  padding-right: 1.5rem;
}

.diff-line.add {
  background: rgba(16, 185, 129, 0.1);
}
.diff-line.add .line-content {
  color: #10b981;
}
.diff-line.add .line-number {
  color: rgba(16, 185, 129, 0.5);
}

.diff-line.del {
  background: rgba(244, 63, 94, 0.1);
}
.diff-line.del .line-content {
  color: #f43f5e;
}
.diff-line.del .line-number {
  color: rgba(244, 63, 94, 0.5);
}

.diff-line.hunk {
  background: rgba(14, 165, 233, 0.05);
}
.diff-line.hunk .line-content {
  color: #7dd3fc;
  opacity: 0.8;
  font-weight: 600;
}

.diff-line.header {
  font-weight: 700;
  color: #94a3b8;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  background: rgba(255, 255, 255, 0.02);
}
.diff-line.file {
  font-weight: 700;
  color: #e2e8f0;
}

.diff-line.selected {
  background: rgba(59, 130, 246, 0.15) !important;
}
</style>
