<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import type { AssetThread, AssetThreadMarker } from '@/composables/asset-discussion/types'
import WordPreview from '@/components/file-preview/WordPreview.vue'
import BlockInlineEditor from './BlockInlineEditor.vue'
import ReviewAnnotationRail from './ReviewAnnotationRail.vue'
import { prepareDocxReview, type ReviewBlock } from './docxReviewSource'
import { indexDocxReview } from './docxReviewRanges'
import { addDocxRevisionHighlights, type DocxRevisionMarker, type DocxRevisionPoint } from './docxRevisionHighlights'
import { groupReviewAnnotations, reviewThreadIdsAt, type ReviewAnnotationTarget } from './reviewAnnotationRanges'

const props = defineProps<{
  wsId: string
  assetId: string
  versionId?: string
  draftRevision?: number
  name: string
  blocks: ReviewBlock[]
  markersByBlock: Record<string, AssetThreadMarker[]>
  threads?: AssetThread[]
  selectedThreadId: string
  inlineReviewEnabled: boolean
  canManualEdit: boolean
  editingBlockId: string
  saving?: boolean
  previewBytes?: ArrayBuffer
  revisionMarkers?: DocxRevisionMarker[]
  revisionNames?: Record<string, string>
}>()
const emit = defineEmits<{
  'select-range': [selection: {
    block_id: string; selected_text: string; char_start: number; char_end: number
    anchor: { top: number; left: number }
  }]
  'clear-selection': []
  'open-threads': [target: ReviewAnnotationTarget]
  'start-edit': [blockId: string]
  'save-block-edit': [blockId: string, text: string]
  'cancel-block-edit': []
  'revision-hover': [point: DocxRevisionPoint | null]
  'revision-open': [point: DocxRevisionPoint]
  'preview-rendered': []
}>()
const { t } = useI18n()
const source = shallowRef<Awaited<ReturnType<typeof prepareDocxReview>>>()
const failed = shallowRef(false)
const surface = shallowRef<{
  frame: HTMLIFrameElement; content: HTMLElement; index: ReturnType<typeof indexDocxReview>
}>()
const editAnchor = shallowRef<{ top: number; left: number }>()
const editedParagraph = computed(() => surface.value?.index.paragraphs
  .find(paragraph => paragraph.edit?.id === props.editingBlockId)?.edit)
const markerRanges = computed(() => {
  const index = surface.value?.index
  if (!index) return []
  return Object.values(props.markersByBlock).flat().flatMap(marker => {
    const ranges = index.rangesForText(marker.block_id, marker.char_start, marker.char_end, marker.selected_text)
    return ranges.length ? [{ marker, ranges }] : []
  })
})
const annotationGroups = computed(() => groupReviewAnnotations(markerRanges.value))
const highlightNames = ['traceforge-review-open', 'traceforge-review-closed', 'traceforge-review-selected'] as const

const iframeStyles = `
  ::highlight(traceforge-review-open) {background:#e0f2fe;color:inherit}
  ::highlight(traceforge-review-closed) {background:#edf2f7;color:inherit}
  ::highlight(traceforge-review-selected) {background:#bae6fd;color:inherit}
  ::highlight(traceforge-revision) {background:#d3eddc;color:inherit}
  .tf-revision-markers {display:inline-block;position:relative;width:0;height:0;vertical-align:baseline;white-space:nowrap}
  .tf-revision-marker {
    margin-inline-start:3px;border:0;border-radius:4px;padding:0 4px;
    color:#075340;background:#d3eddc;font:12px system-ui;cursor:pointer;
  }
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

watch(() => [props.wsId, props.assetId, props.versionId, props.draftRevision, props.previewBytes] as const, async (
  [wsId, assetId, versionId, draftRevision, previewBytes], _, cleanup,
) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  surface.value = undefined
  source.value = undefined
  editAnchor.value = undefined
  failed.value = false
  emit('clear-selection')
  if (!versionId && !previewBytes) return

  const blocks = props.blocks
  try {
    const root = `/workspaces/${encodeURIComponent(wsId)}/assets/${encodeURIComponent(assetId)}`
    const bytes = previewBytes ?? (await api.get<ArrayBuffer>(
      draftRevision ? `${root}/draft/file` : `${root}/file`,
      {
        responseType: 'arraybuffer',
        params: draftRevision ? { revision: draftRevision } : { version_id: versionId },
        signal: request.signal,
      },
    )).data
    if (request.signal.aborted) return
    const prepared = await prepareDocxReview(bytes, blocks)
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
  emit('preview-rendered')
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
  content.addEventListener('click', event => {
    const target = event.target as Element | null
    if (props.editingBlockId || document.getSelection()?.isCollapsed === false
      || target?.closest?.('button')) return
    const threadIds = reviewThreadIdsAt(markerRanges.value, event)
    if (!threadIds.length) return
    const bounds = frame.getBoundingClientRect()
    emit('open-threads', {
      threadIds, left: bounds.left + event.clientX + 8, top: bounds.top + event.clientY + 8, frame,
    })
  }, { signal: events.signal })
  document.addEventListener('scroll', () => emit('clear-selection'), { signal: events.signal })
  cleanup(() => events.abort())
})

watch(() => [surface.value, markerRanges.value, props.markersByBlock, props.canManualEdit] as const, ([current, entries], _, cleanup) => {
  if (!current) return
  const { frame, content, index } = current
  const document = content.ownerDocument
  const controls: Array<{ marker: HTMLElement; group: HTMLElement }> = []
  const preciseIds = new Set(entries.map(({ marker }) => marker.thread_id))
  const seen = new Set<string>()
  for (const { marker, block, edit, hasTextRange } of index.paragraphs) {
    const group = document.createElement('span')
    // Older annotations with an ambiguous quote can still be opened from their paragraph.
    const markers = (props.markersByBlock[block.id] ?? []).filter(item => !preciseIds.has(item.thread_id))
    if (markers.length && hasTextRange && !seen.has(block.id)) {
      seen.add(block.id)
      const button = document.createElement('button')
      button.type = 'button'
      button.title = t('doc_review.thread_count', { count: markers.length })
      button.setAttribute('aria-label', button.title)
      button.textContent = String(markers.length)
      button.toggleAttribute('data-open', markers.some(item => item.status === 'open'))
      button.addEventListener('click', () => {
        const frameBounds = frame.getBoundingClientRect()
        const bounds = button.getBoundingClientRect()
        emit('open-threads', {
          threadIds: markers.map(item => item.thread_id),
          left: frameBounds.left + bounds.right + 8, top: frameBounds.top + bounds.top, trigger: button, frame,
        })
      })
      group.append(button)
    }
    if (props.canManualEdit && edit) {
      const button = document.createElement('button')
      button.type = 'button'
      button.title = t('doc_review.manual_edit_button')
      button.textContent = '✎'
      button.setAttribute('aria-label', button.title)
      button.setAttribute('data-edit', '')
      button.addEventListener('click', () => {
        emit('clear-selection')
        const anchor = viewportAnchor(frame, button.getBoundingClientRect())
        editAnchor.value = {
          top: Math.min(anchor.top, Math.max(16, window.innerHeight - 260)),
          left: Math.min(anchor.left, Math.max(16, window.innerWidth - 456)),
        }
        emit('start-edit', edit.id)
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

watch(() => [surface.value, markerRanges.value, props.selectedThreadId] as const, ([current, entries, selected], _, cleanup) => {
  if (!current) return
  const win = current.frame.contentWindow as (Window & typeof globalThis) | null
  if (!win?.CSS.highlights || !win.Highlight) return
  const ranges: [Range[], Range[], Range[]] = [[], [], []]
  for (const { marker, ranges: markerRanges } of entries) {
    const type = marker.thread_id === selected ? 2 : marker.status === 'open' ? 0 : 1
    ranges[type].push(...markerRanges)
  }
  highlightNames.forEach((name, index) => {
    const highlight = new win.Highlight(...ranges[index])
    highlight.priority = index === 1 ? 0 : index === 0 ? 1 : 2
    win.CSS.highlights.set(name, highlight)
  })
  cleanup(() => highlightNames.forEach(name => win.CSS.highlights.delete(name)))
}, { flush: 'post' })

watch(() => [surface.value, markerRanges.value, props.selectedThreadId] as const, ([current, entries, selected]) => {
  if (!current || !selected) return
  const range = entries.find(entry => entry.marker.thread_id === selected)?.ranges[0]
  const win = current.frame.contentWindow
  if (!range || !win) return
  const rect = range.getBoundingClientRect()
  if (rect.top < 0 || rect.bottom > win.innerHeight) win.scrollBy(0, rect.top - win.innerHeight / 3)
}, { flush: 'post' })
watch(() => [surface.value, props.revisionMarkers, props.revisionNames] as const, ([current, markers, names], _, cleanup) => {
  if (!current || !markers?.length || !names) return
  cleanup(addDocxRevisionHighlights(current.frame, current.content, current.index, markers, names, {
    hover: point => emit('revision-hover', point),
    open: point => emit('revision-open', point),
  }))
}, { flush: 'post' })

defineExpose({
  revealRevision(id: string) {
    const buttons = surface.value?.content.querySelectorAll<HTMLButtonElement>('[data-docx-revision]')
    const button = [...(buttons ?? [])].find(item => item.dataset.docxRevision === id)
    button?.scrollIntoView({ block: 'center' })
  },
})
</script>

<template>
  <div class="docx-review-canvas">
    <ReviewAnnotationRail
      :groups="annotationGroups"
      :threads="threads"
      :content="surface?.content"
      :frame="surface?.frame"
      :selected-thread-id="selectedThreadId"
      @open-threads="emit('open-threads', $event)"
    />
    <p v-if="failed" class="docx-review-state" role="alert">{{ t('file_preview.failed') }}</p>
    <p v-else-if="!source" class="docx-review-state" role="status">{{ t('common.loading') }}</p>
    <WordPreview v-else :bytes="source.bytes" :name="name" tab-stops @rendered="onRendered" />
    <div
      v-if="editedParagraph && editAnchor"
      class="docx-edit-popover glass-panel"
      :style="{ top: `${editAnchor.top + 4}px`, left: `${editAnchor.left}px` }"
    >
      <BlockInlineEditor
        :key="editedParagraph.id"
        :initial-text="editedParagraph.text"
        :allow-empty="editedParagraph.inTable"
        :disabled="saving"
        :save-label="t('doc_review.draft_save')"
        :cancel-label="t('common.cancel')"
        preserve-whitespace
        @save="text => emit('save-block-edit', editedParagraph!.id, text)"
        @cancel="emit('cancel-block-edit')"
      />
    </div>
  </div>
</template>

<style scoped>
.docx-review-canvas { position: relative; display: flex; height: 100%; min-height: 0; min-width: 0; }
.docx-review-state { margin: auto; padding: 16px; color: var(--color-text-muted, #64748b); }
.docx-edit-popover {
  position: fixed; z-index: 30; width: min(440px, 80vw); padding: 12px;
  max-height: min(50vh, 248px); overflow: auto;
}
</style>
