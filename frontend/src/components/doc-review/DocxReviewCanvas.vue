<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import type { AssetThreadMarker } from '@/composables/asset-discussion/types'
import WordPreview from '@/components/file-preview/WordPreview.vue'
import BlockInlineEditor from './BlockInlineEditor.vue'
import { prepareDocxReview, type ReviewBlock } from './docxReviewSource'
import { indexDocxReview } from './docxReviewRanges'

const props = defineProps<{
  wsId: string
  assetId: string
  versionId?: string
  name: string
  blocks: ReviewBlock[]
  markersByBlock: Record<string, AssetThreadMarker[]>
  selectedThreadId: string
  inlineReviewEnabled: boolean
  canManualEdit: boolean
  editingBlockId: string
}>()
const emit = defineEmits<{
  'select-range': [selection: {
    block_id: string; selected_text: string; char_start: number; char_end: number
    anchor: { top: number; left: number }
  }]
  'clear-selection': []
  'open-thread': [threadId: string]
  'start-edit': [blockId: string]
  'save-block-edit': [blockId: string, text: string]
  'cancel-block-edit': []
}>()
const { t } = useI18n()
const source = shallowRef<Awaited<ReturnType<typeof prepareDocxReview>>>()
const failed = shallowRef(false)
const surface = shallowRef<{
  frame: HTMLIFrameElement; content: HTMLElement; index: ReturnType<typeof indexDocxReview>
}>()
const editAnchor = shallowRef<{ top: number; left: number }>()
const editedBlock = computed(() => props.blocks.find(block => block.id === props.editingBlockId))
const highlightNames = ['traceforge-review-open', 'traceforge-review-closed', 'traceforge-review-selected'] as const

const iframeStyles = `
  ::highlight(traceforge-review-open) {background:#fde5a5;color:inherit}
  ::highlight(traceforge-review-closed) {background:#dce6ed;color:inherit}
  ::highlight(traceforge-review-selected) {background:#ffbd62;color:inherit}
  .tf-review-controls {position:relative}
  .tf-review-controls > span {
    position:absolute;inset-inline-end:0;top:0;z-index:1;
    display:flex;flex-direction:column;gap:2px;padding-inline-end:5px;user-select:none;
  }
  .tf-review-controls button {
    border:0;border-radius:4px;padding:0 4px;min-width:19px;
    min-height:18px;background:#e9eff5;color:#243649;cursor:pointer;
    font:11px system-ui;white-space:nowrap;
  }
  .tf-review-controls button[data-open] {background:#ffe1a3}
  .tf-review-controls button[data-edit] {opacity:0;pointer-events:none}
  p:hover .tf-review-controls button[data-edit],
  .tf-review-controls button[data-edit]:focus-visible {opacity:1;pointer-events:auto}
`

watch(() => [props.wsId, props.assetId, props.versionId] as const, async ([wsId, assetId, versionId], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  surface.value = undefined
  source.value = undefined
  editAnchor.value = undefined
  failed.value = false
  emit('clear-selection')
  if (!versionId) return

  const blocks = props.blocks
  try {
    const response = await api.get<ArrayBuffer>(
      `/workspaces/${encodeURIComponent(wsId)}/assets/${encodeURIComponent(assetId)}/file`,
      { responseType: 'arraybuffer', params: { version_id: versionId }, signal: request.signal },
    )
    if (request.signal.aborted) return
    const prepared = await prepareDocxReview(response.data, blocks)
    if (!request.signal.aborted) source.value = prepared
  } catch {
    if (!request.signal.aborted) failed.value = true
  }
}, { immediate: true })

function onRendered(frame: HTMLIFrameElement, content: HTMLElement) {
  if (!source.value) return
  const style = content.ownerDocument.createElement('style')
  style.textContent = iframeStyles
  content.append(style)
  surface.value = { frame, content, index: indexDocxReview(content, source.value.anchors) }
}

function viewportAnchor(frame: HTMLIFrameElement, rect: DOMRect) {
  const bounds = frame.getBoundingClientRect()
  return { top: bounds.top + rect.bottom, left: bounds.left + rect.left }
}

watch(surface, (current, _, cleanup) => {
  if (!current) return
  const { frame, content, index } = current
  const document = content.ownerDocument
  const events = new AbortController()
  const reportSelection = (event: Event) => {
    if (!props.inlineReviewEnabled || props.editingBlockId) return
    if ((event.target as Element | null)?.closest?.('.tf-review-controls')) return
    const selection = document.getSelection()
    const range = selection?.rangeCount && !selection.isCollapsed ? selection.getRangeAt(0) : null
    const text = range && index.selectedText(range)
    if (!range || !text) {
      emit('clear-selection')
      return
    }
    emit('select-range', { ...text, anchor: viewportAnchor(frame, range.getBoundingClientRect()) })
  }
  document.addEventListener('pointerup', reportSelection, { signal: events.signal })
  document.addEventListener('keyup', event => {
    if (event.shiftKey || event.key === 'Shift') reportSelection(event)
  }, { signal: events.signal })
  document.addEventListener('scroll', () => emit('clear-selection'), { signal: events.signal })
  cleanup(() => events.abort())
})

watch(() => [surface.value, props.markersByBlock, props.canManualEdit] as const, ([current], _, cleanup) => {
  if (!current) return
  const { frame, content, index } = current
  const document = content.ownerDocument
  const controls: Array<{ marker: HTMLElement; group: HTMLElement }> = []
  const seen = new Set<string>()
  for (const { marker, block } of index.paragraphs) {
    if (seen.has(block.id)) continue
    seen.add(block.id)
    const group = document.createElement('span')
    const markers = props.markersByBlock[block.id] ?? []
    const preferred = markers.find(item => item.status === 'open') ?? markers[0]
    if (preferred) {
      const button = document.createElement('button')
      button.type = 'button'
      button.title = t('doc_review.thread_count', { count: markers.length })
      button.textContent = String(markers.length)
      button.toggleAttribute('data-open', preferred.status === 'open')
      button.addEventListener('click', () => emit('open-thread', preferred.thread_id))
      group.append(button)
    }
    if (props.canManualEdit && block.type !== 'table') {
      const button = document.createElement('button')
      button.type = 'button'
      button.title = t('doc_review.manual_edit_button')
      button.textContent = '✎'
      button.setAttribute('aria-label', button.title)
      button.setAttribute('data-edit', '')
      button.addEventListener('click', () => {
        emit('clear-selection')
        editAnchor.value = viewportAnchor(frame, button.getBoundingClientRect())
        emit('start-edit', block.id)
      })
      group.append(button)
    }
    if (group.childElementCount) {
      marker.classList.add('tf-review-controls')
      marker.append(group)
      controls.push({ marker, group })
    }
  }
  cleanup(() => {
    for (const { marker, group } of controls) {
      marker.classList.remove('tf-review-controls')
      group.remove()
    }
  })
}, { flush: 'post' })

watch(() => [surface.value, props.markersByBlock, props.selectedThreadId] as const, ([current, markers, selected], _, cleanup) => {
  if (!current) return
  const win = current.frame.contentWindow as (Window & typeof globalThis) | null
  if (!win?.CSS.highlights || !win.Highlight) return
  const ranges: [Range[], Range[], Range[]] = [[], [], []]
  for (const marker of Object.values(markers).flat()) {
    const type = marker.thread_id === selected ? 2 : marker.status === 'open' ? 0 : 1
    ranges[type].push(...current.index.rangesForText(marker.block_id, marker.char_start, marker.char_end, marker.selected_text))
  }
  highlightNames.forEach((name, index) => {
    const highlight = new win.Highlight(...ranges[index])
    highlight.priority = index === 2 ? 1 : 0
    win.CSS.highlights.set(name, highlight)
  })
  cleanup(() => highlightNames.forEach(name => win.CSS.highlights.delete(name)))
}, { flush: 'post' })

watch(() => [surface.value, props.selectedThreadId] as const, ([current, selected]) => {
  if (!current || !selected) return
  const marker = Object.values(props.markersByBlock).flat().find(item => item.thread_id === selected)
  if (!marker) return
  const [range] = current.index.rangesForText(marker.block_id, marker.char_start, marker.char_end, marker.selected_text)
  const win = current.frame.contentWindow
  if (!range || !win) return
  const rect = range.getBoundingClientRect()
  if (rect.top < 0 || rect.bottom > win.innerHeight) win.scrollBy(0, rect.top - win.innerHeight / 3)
}, { flush: 'post' })
</script>

<template>
  <div class="docx-review-canvas">
    <p v-if="failed" class="docx-review-state" role="alert">{{ t('file_preview.failed') }}</p>
    <p v-else-if="!source" class="docx-review-state" role="status">{{ t('common.loading') }}</p>
    <WordPreview v-else :bytes="source.bytes" :name="name" tab-stops @rendered="onRendered" />
    <div
      v-if="editedBlock && editAnchor"
      class="docx-edit-popover glass-panel"
      :style="{ top: `${editAnchor.top + 4}px`, left: `${editAnchor.left}px` }"
    >
      <BlockInlineEditor
        :key="editedBlock.id"
        :initial-text="editedBlock.text"
        preserve-whitespace
        @save="text => emit('save-block-edit', editedBlock!.id, text)"
        @cancel="emit('cancel-block-edit')"
      />
    </div>
  </div>
</template>

<style scoped>
.docx-review-canvas { display: flex; height: 100%; min-height: 0; min-width: 0; }
.docx-review-state { margin: auto; padding: 16px; color: var(--color-text-muted, #64748b); }
.docx-edit-popover { position: fixed; z-index: 30; width: min(440px, 80vw); padding: 12px; }
</style>
