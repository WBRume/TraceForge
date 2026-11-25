<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import type { AssetThread, AssetThreadMarker } from '@/composables/asset-discussion/types'
import ReviewAnnotationRail from './ReviewAnnotationRail.vue'
import { renderMarkdownReview } from './markdownReviewSource'
import { groupReviewAnnotations, reviewThreadIdsAt, type ReviewAnnotationTarget } from './reviewAnnotationRanges'

const SOURCE_BLOCK = 'source-text'
const props = defineProps<{
  source: string
  markdown: boolean
  markersByBlock: Record<string, AssetThreadMarker[]>
  threads: AssetThread[]
  selectedThreadId: string
  inlineReviewEnabled: boolean
  focusText?: string
}>()
const emit = defineEmits<{
  'select-range': [selection: {
    block_id: string; selected_text: string; char_start: number; char_end: number
    anchor: { top: number; left: number }
  }]
  'clear-selection': []
  'open-threads': [target: ReviewAnnotationTarget]
}>()

const body = ref<HTMLElement>()
const rendered = computed(() => props.markdown ? renderMarkdownReview(props.source) : null)
const codePointOffsets = computed(() => {
  const offsets = [0]
  for (const codePoint of props.source) offsets.push(offsets[offsets.length - 1]! + codePoint.length)
  return offsets
})
const highlightId = useId()
const names = ['open', 'closed', 'current', 'focus'].map(kind => `tf-text-${highlightId}-${kind}`)
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

function rangesForSource(nodes: ReturnType<typeof sourceNodes>, start: number, end: number) {
  return nodes.flatMap(piece => {
    if (piece.start(0) >= end || piece.end(piece.node.length) <= start) return []
    let from = 0
    let to = piece.node.length
    while (from < to && piece.end(from + 1) <= start) from++
    while (to > from && piece.start(to - 1) >= end) to--
    if (to <= from) return []
    const range = document.createRange()
    range.setStart(piece.node, from)
    range.setEnd(piece.node, to)
    return [range]
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
    const ranges = rangesForSource(nodes, start, end)
    return ranges.length ? [{ marker, ranges }] : []
  })
})
const annotationGroups = computed(() => groupReviewAnnotations(markerRanges.value))
watch(() => [body.value, props.source, props.markdown] as const, () => { paintKey.value++ }, { flush: 'post' })

const focusRanges = computed(() => {
  void paintKey.value
  const text = props.focusText?.slice(0, 600).trim()
  if (!text) return []
  const start = props.source.indexOf(text)
  if (start >= 0) return rangesForSource(sourceNodes(), start, start + text.length)
  const pattern = text.split(/\s+/).map(word => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+')
  const match = new RegExp(pattern).exec(props.source)
  return match ? rangesForSource(sourceNodes(), match.index, match.index + match[0].length) : []
})

watch(() => [paintKey.value, markerRanges.value, props.selectedThreadId, focusRanges.value] as const, ([, entries, selected, focused], _, cleanup) => {
  if (!globalThis.CSS?.highlights || !globalThis.Highlight || !body.value) return
  const style = document.createElement('style')
  const colors = ['#e0f2fe', '#edf2f7', '#bae6fd', '#ffe9a6']
  style.textContent = names.map((name, index) => `::highlight(${name}){background:${colors[index]};color:inherit}`).join('')
  document.head.append(style)
  const groups: Range[][] = [[], [], [], focused]
  for (const { marker, ranges } of entries) {
    groups[marker.thread_id === selected ? 2 : marker.status === 'open' ? 0 : 1]!.push(...ranges)
  }
  names.forEach((name, index) => {
    const highlight = new Highlight(...groups[index]!)
    highlight.priority = [1, 0, 3, 2][index] || 0
    CSS.highlights.set(name, highlight)
  })
  cleanup(() => {
    names.forEach(name => CSS.highlights.delete(name))
    style.remove()
  })
}, { flush: 'post' })

watch(() => [props.selectedThreadId, paintKey.value, focusRanges.value] as const, ([selected, , focused]) => {
  const range = selected ? markerRanges.value.find(entry => entry.marker.thread_id === selected)?.ranges[0] : focused[0]
  if (!range) return
  const rect = range.getBoundingClientRect()
  const shell = body.value?.closest('.canvas-shell')
  const canvas = shell?.getBoundingClientRect()
  if (canvas && (rect.top < canvas.top || rect.bottom > canvas.bottom)) {
    shell?.scrollBy({ top: rect.top - canvas.top - canvas.height / 3 })
  }
}, { flush: 'post' })

function openMarker(event: MouseEvent) {
  if (window.getSelection()?.isCollapsed === false) return
  const threadIds = reviewThreadIdsAt(markerRanges.value, event)
  if (threadIds.length) emit('open-threads', { threadIds, left: event.clientX + 8, top: event.clientY + 8 })
}
</script>

<template>
  <div class="text-review-canvas">
    <ReviewAnnotationRail
      :groups="annotationGroups"
      :threads="threads"
      :content="body"
      :selected-thread-id="selectedThreadId"
      @open-threads="emit('open-threads', $event)"
    />
    <article class="text-page" @pointerup="reportSelection" @keyup.shift="reportSelection" @click="openMarker">
      <div v-if="rendered" ref="body" class="markdown-source" v-html="rendered.html" />
      <div v-else ref="body" class="plain-source" v-text="source" />
    </article>
  </div>
</template>

<style scoped>
.text-review-canvas {
  display: flex;
  min-height: 100%;
}
.text-page {
  box-sizing: border-box;
  width: min(100%, 55rem);
  min-width: 0;
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
