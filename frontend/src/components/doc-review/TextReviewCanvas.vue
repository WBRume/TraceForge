<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import type { AssetThreadMarker } from '@/composables/asset-discussion/types'
import { renderMarkdownReview } from './markdownReviewSource'

const SOURCE_BLOCK = 'source-text'
const props = defineProps<{
  source: string
  markdown: boolean
  markersByBlock: Record<string, AssetThreadMarker[]>
  selectedThreadId: string
  inlineReviewEnabled: boolean
}>()
const emit = defineEmits<{
  'select-range': [selection: {
    block_id: string; selected_text: string; char_start: number; char_end: number
    anchor: { top: number; left: number }
  }]
  'clear-selection': []
  'open-thread': [id: string]
}>()

const body = ref<HTMLElement>()
const rendered = computed(() => props.markdown ? renderMarkdownReview(props.source) : null)
const codePointOffsets = computed(() => {
  const offsets = [0]
  for (const codePoint of props.source) offsets.push(offsets[offsets.length - 1]! + codePoint.length)
  return offsets
})
const highlightId = useId()
const names = ['open', 'closed', 'current'].map(kind => `tf-text-${highlightId}-${kind}`)
const paintKey = ref(0)

function sourceNodes() {
  if (!body.value) return []
  if (!rendered.value) {
    const node = body.value.firstChild
    if (!node || node.nodeType !== Node.TEXT_NODE) return []
    return [{ node: node as Text, start: (i: number) => i, end: (i: number) => i }]
  }
  const { pieces } = rendered.value
  return Array.from(body.value.querySelectorAll<HTMLElement>('[data-source-piece]')).flatMap(element => {
    const piece = pieces[Number(element.dataset.sourcePiece)]
    const node = element.firstChild
    if (!piece || !node || node.nodeType !== Node.TEXT_NODE) return []
    return [{
      node: node as Text,
      start: (i: number) => piece.starts[i] ?? piece.ends[piece.ends.length - 1]!,
      end: (i: number) => piece.ends[i - 1] ?? piece.starts[0]!,
    }]
  })
}

function reportSelection() {
  if (!props.inlineReviewEnabled) return
  const selection = window.getSelection()
  const range = selection?.rangeCount && !selection.isCollapsed ? selection.getRangeAt(0) : null
  if (!range || !body.value?.contains(range.startContainer) || !body.value.contains(range.endContainer)) {
    emit('clear-selection')
    return
  }
  const parts = sourceNodes().flatMap(piece => {
    if (!range.intersectsNode(piece.node)) return []
    const from = range.startContainer === piece.node ? range.startOffset : 0
    const to = range.endContainer === piece.node ? range.endOffset : piece.node.length
    return to > from ? [{ start: piece.start(from), end: piece.end(to) }] : []
  })
  const first = parts[0]
  const last = parts[parts.length - 1]
  if (!first || !last || parts.some((item, i) => i > 0 && item.start < parts[i - 1]!.end)) {
    emit('clear-selection')
    return
  }
  const raw = props.source.slice(first.start, last.end)
  const quote = raw.trim()
  if (!quote) {
    emit('clear-selection')
    return
  }
  const start = Array.from(props.source.slice(0, first.start + raw.length - raw.trimStart().length)).length
  const rect = range.getBoundingClientRect()
  emit('select-range', {
    block_id: SOURCE_BLOCK, selected_text: quote, char_start: start, char_end: start + Array.from(quote).length,
    anchor: {
      top: Math.min(rect.bottom, Math.max(16, window.innerHeight - 240)),
      left: Math.min(rect.left, Math.max(16, window.innerWidth - 440)),
    },
  })
}

function markerOffsets(marker: AssetThreadMarker) {
  if (marker.block_id === SOURCE_BLOCK && marker.char_start != null && marker.char_end != null) {
    return [codePointOffsets.value[marker.char_start], codePointOffsets.value[marker.char_end]]
  }
  const quote = marker.selected_text
  const start = quote ? props.source.indexOf(quote) : -1
  if (quote && start >= 0 && props.source.indexOf(quote, start + 1) < 0) return [start, start + quote.length]
  return []
}

const markerRanges = computed(() => {
  // Observe the DOM after Vue replaces the rendered body.
  void paintKey.value
  const nodes = sourceNodes()
  return Object.values(props.markersByBlock).flat().flatMap(marker => {
    const [start, end] = markerOffsets(marker)
    if (start == null || end == null || end <= start) return []
    const ranges = nodes.flatMap(piece => {
      if (piece.start(0) >= end || piece.end(piece.node.length) <= start) return []
      let from = 0
      let to = piece.node.length
      while (from < to && piece.end(from + 1) <= start) from++
      while (to > from && piece.start(to - 1) >= end) to--
      const range = document.createRange()
      range.setStart(piece.node, from)
      range.setEnd(piece.node, to)
      return [range]
    })
    return [{ marker, ranges }]
  })
})
watch(() => [body.value, props.source] as const, () => { paintKey.value++ }, { flush: 'post' })

watch(() => [paintKey.value, markerRanges.value, props.selectedThreadId] as const, ([, entries, selected], _, cleanup) => {
  if (!CSS.highlights || !body.value) return
  const style = document.createElement('style')
  const colors = ['#fde5a5', '#dce6ed', '#ffbd62']
  style.textContent = names.map((name, index) => `::highlight(${name}){background:${colors[index]};color:inherit}`).join('')
  document.head.append(style)
  const groups: Range[][] = [[], [], []]
  for (const { marker, ranges } of entries) {
    groups[marker.thread_id === selected ? 2 : marker.status === 'open' ? 0 : 1]!.push(...ranges)
  }
  names.forEach((name, index) => {
    const highlight = new Highlight(...groups[index]!)
    highlight.priority = index === 2 ? 1 : 0
    CSS.highlights.set(name, highlight)
  })
  cleanup(() => {
    names.forEach(name => CSS.highlights.delete(name))
    style.remove()
  })
}, { flush: 'post' })

watch(() => [props.selectedThreadId, paintKey.value] as const, ([selected]) => {
  if (!selected) return
  const range = markerRanges.value.find(entry => entry.marker.thread_id === selected)?.ranges[0]
  if (!range) return
  const rect = range.getBoundingClientRect()
  const shell = body.value?.closest('.canvas-shell')
  const canvas = shell?.getBoundingClientRect()
  if (canvas && (rect.top < canvas.top || rect.bottom > canvas.bottom)) {
    shell?.scrollBy({ top: rect.top - canvas.top - canvas.height / 3 })
  }
}, { flush: 'post' })

function openMarker(event: MouseEvent) {
  if (!window.getSelection()?.isCollapsed) return
  const { clientX, clientY } = event
  const match = markerRanges.value.find(entry => entry.ranges.some(range =>
    Array.from(range.getClientRects()).some(rect =>
      clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom),
  ))
  if (match) emit('open-thread', match.marker.thread_id)
}
</script>

<template>
  <article
    class="text-page"
    @pointerup="reportSelection"
    @keyup.shift="reportSelection"
    @click="openMarker"
  >
    <div v-if="rendered" ref="body" class="markdown-source" v-html="rendered.html" />
    <div v-else ref="body" class="plain-source" v-text="source" />
  </article>
</template>

<style scoped>
.text-page {
  box-sizing: border-box;
  width: min(100%, 55rem);
  min-height: 100%;
  margin: 0 auto;
  padding: clamp(1rem, 4vw, 3rem);
  background: var(--color-bg-card, white);
  color: var(--color-text-primary, #22324b);
  line-height: 1.65;
  overflow-wrap: anywhere;
}
.plain-source { white-space: pre-wrap; tab-size: 4; font-family: ui-monospace, monospace; }
.markdown-source :deep(h1), .markdown-source :deep(h2), .markdown-source :deep(h3) { font-weight: 650; }
.markdown-source :deep(h1) { font-size: 1.85em; }
.markdown-source :deep(h2) { font-size: 1.5em; }
.markdown-source :deep(h3) { font-size: 1.25em; }
.markdown-source :deep(h4), .markdown-source :deep(h5), .markdown-source :deep(h6) { font-weight: 650; }
.markdown-source :deep(p), .markdown-source :deep(ul), .markdown-source :deep(ol),
.markdown-source :deep(pre), .markdown-source :deep(blockquote), .markdown-source :deep(table) { margin: .65em 0 1em; }
.markdown-source :deep(p:empty) { margin: 0; }
.markdown-source :deep(ul) { list-style: disc; padding-inline-start: 1.8em; }
.markdown-source :deep(ol) { list-style: decimal; padding-inline-start: 1.8em; }
.markdown-source :deep(.task-list-item) { list-style: none; }
.markdown-source :deep(blockquote) { border-inline-start: 3px solid #cbd5e1; padding-inline-start: 1em; }
.markdown-source :deep(a) { color: #0369a1; text-decoration: underline; }
.markdown-source :deep(td), .markdown-source :deep(th) { border: 1px solid #cbd5e1; padding: .3em .6em; }
.markdown-source :deep(code) { font-family: ui-monospace, monospace; background: #edf2f7; }
.markdown-source :deep(pre) { background: #edf2f7; padding: .7em 1em; overflow: auto; white-space: pre; }
.markdown-source :deep(img) { max-width: 100%; height: auto; }
</style>
