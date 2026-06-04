<script setup lang="ts">
import { computed } from 'vue'
import type { DiffHunk } from '@/types/workspaceAssets'

const props = defineProps<{
  hunks: DiffHunk[]
  height?: string
}>()

const emit = defineEmits<{
  'range-select': [payload: { lineStart: number; lineEnd: number; side: 'ai' | 'human'; selectedText: string }]
}>()

type Cell = {
  content: string
  lineNo: number | null | undefined
  source: string
}

type Row = {
  ai: Cell | null
  human: Cell | null
  source: string
}

function inAiOutput(type: string, source: string): boolean {
  if (type === 'context') return true
  if (type === 'add') return source !== 'human'
  if (type === 'del') return source === 'human'
  return false
}

function inHumanOutput(type: string, source: string): boolean {
  if (type === 'context') return true
  if (type === 'add') return source !== 'ai'
  if (type === 'del') return source === 'ai'
  return false
}

const rows = computed<Row[]>(() => {
  const result: Row[] = []
  for (const hunk of props.hunks) {
    for (const line of hunk.lines) {
      const src = line.source || 'context'
      const a = inAiOutput(line.type, src)
      const h = inHumanOutput(line.type, src)
      if (!a && !h) continue
      result.push({
        ai: a ? { content: line.content, lineNo: line.new_line_no, source: src } : null,
        human: h ? { content: line.content, lineNo: line.new_line_no, source: src } : null,
        source: src,
      })
    }
  }
  return result
})

function rowClass(row: Row): string {
  if (row.source === 'ai') return 'row-ai-only'
  if (row.source === 'human') return 'row-human-only'
  if (row.source === 'both') return 'row-both'
  return 'row-context'
}

function onSideMouseUp(side: 'ai' | 'human', e: MouseEvent) {
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed) return

  const range = selection.getRangeAt(0)
  const container = (e.currentTarget as HTMLElement).closest('.sbh-body')
  if (!container) return

  const rowEls = container.querySelectorAll('.sbh-row')
  if (!rowEls.length) return

  let startLine = -1
  let endLine = -1

  rowEls.forEach((rowEl, idx) => {
    const sideEl = rowEl.querySelector(`.sbh-${side}`)
    if (sideEl && range.intersectsNode(sideEl)) {
      if (startLine === -1) startLine = idx
      endLine = idx
    }
  })

  if (startLine === -1) return

  const selectedText = selection.toString().trim()
  if (!selectedText) return

  const row = rows.value[startLine]
  const lineStart = (side === 'ai' ? row.ai?.lineNo : row.human?.lineNo) ?? startLine + 1
  const endRow = rows.value[endLine]
  const lineEnd = (side === 'ai' ? endRow.ai?.lineNo : endRow.human?.lineNo) ?? endLine + 1

  emit('range-select', {
    lineStart: lineStart,
    lineEnd: lineEnd,
    side,
    selectedText,
  })

  selection.removeAllRanges()
}
</script>

<template>
  <div class="sbh-viewer">
    <div class="sbh-header">
      <div class="sbh-label sbh-label-ai">AI Output</div>
      <div class="sbh-label sbh-label-human">Human Output</div>
    </div>
    <div class="sbh-body">
      <div
        v-for="(row, i) in rows"
        :key="i"
        class="sbh-row"
        :class="rowClass(row)"
      >
        <div
          class="sbh-side sbh-ai"
          @mouseup="(e) => onSideMouseUp('ai', e)"
        >
          <template v-if="row.ai">
            <span class="sbh-num">{{ row.ai.lineNo }}</span>
            <span class="sbh-text">{{ row.ai.content }}</span>
          </template>
        </div>
        <div
          class="sbh-side sbh-human"
          @mouseup="(e) => onSideMouseUp('human', e)"
        >
          <template v-if="row.human">
            <span class="sbh-num">{{ row.human.lineNo }}</span>
            <span class="sbh-text">{{ row.human.content }}</span>
          </template>
        </div>
      </div>
      <div v-if="rows.length === 0" class="sbh-empty">
        No differences found
      </div>
    </div>
  </div>
</template>

<style scoped>
.sbh-viewer {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  overflow: hidden;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 0.8rem;
  line-height: 1.5;
}

.sbh-header {
  display: flex;
  flex-shrink: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.sbh-label {
  flex: 1;
  padding: 4px 12px;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  text-align: center;
}

.sbh-label-ai {
  color: #fb923c;
  background: rgba(249, 115, 22, 0.06);
  border-right: 1px solid rgba(255, 255, 255, 0.06);
}

.sbh-label-human {
  color: #34d399;
  background: rgba(16, 185, 129, 0.06);
}

.sbh-body {
  flex: 1;
  overflow: auto;
}

.sbh-row {
  display: flex;
  min-height: 20px;
}

.sbh-side {
  flex: 1;
  display: flex;
  min-width: 0;
  white-space: pre;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  cursor: text;
  user-select: text;
}

.sbh-side:last-child {
  border-right: none;
}

.sbh-num {
  width: 40px;
  padding: 0 6px;
  text-align: right;
  color: #475569;
  font-size: 0.72rem;
  flex-shrink: 0;
  user-select: none;
  border-right: 1px solid rgba(255, 255, 255, 0.04);
}

.sbh-text {
  flex: 1;
  padding: 0 8px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-context .sbh-text {
  color: #cbd5e1;
}

.row-both .sbh-side {
  background: rgba(16, 185, 129, 0.05);
}
.row-both .sbh-text {
  color: #a7f3d0;
}

.row-ai-only .sbh-ai {
  background: rgba(249, 115, 22, 0.1);
}
.row-ai-only .sbh-ai .sbh-text {
  color: #fb923c;
}
.row-ai-only .sbh-human {
  background: rgba(255, 255, 255, 0.01);
}

.row-human-only .sbh-human {
  background: rgba(16, 185, 129, 0.1);
}
.row-human-only .sbh-human .sbh-text {
  color: #34d399;
}
.row-human-only .sbh-ai {
  background: rgba(255, 255, 255, 0.01);
}

.sbh-empty {
  padding: 24px;
  text-align: center;
  color: #475569;
  font-style: italic;
}
</style>
