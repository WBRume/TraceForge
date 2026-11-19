<script setup lang="ts">
import { computed, defineAsyncComponent, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type {
  AssetResolutionProposal, NativeDocumentRevision, ResolutionApplyPayload, RevisionChange,
} from '@/composables/asset-discussion/types'
import type { ReviewBlock } from './docxReviewSource'
import type { DocxRevisionMarker, DocxRevisionPoint } from './docxRevisionHighlights'

type Decision = 'accepted' | 'rejected'
type WordRevisionPreview = { bytes: ArrayBuffer; blocks: ReviewBlock[]; markers: DocxRevisionMarker[]; key: string }

const props = defineProps<{
  revision: NativeDocumentRevision
  proposal: Pick<AssetResolutionProposal, 'id' | 'status' | 'proposed_patch_json'> & { thread_id?: string }
  wsId: string
  assetId: string
  assetName: string
  markdown?: boolean
  busy?: boolean
}>()
const emit = defineEmits<{ ready: [payload: ResolutionApplyPayload | null] }>()
const { t } = useI18n()
const DocxReviewCanvas = defineAsyncComponent(() => import('./DocxReviewCanvas.vue'))
const MonacoDiffViewer = defineAsyncComponent(() => import('@/components/diff/MonacoDiffViewer.vue'))
const wordCanvas = useTemplateRef<InstanceType<typeof DocxReviewCanvas>>('wordCanvas')
const textEditor = useTemplateRef<InstanceType<typeof MonacoDiffViewer>>('textEditor')
const reviewSurface = useTemplateRef<HTMLElement>('reviewSurface')
const appliedIds = props.proposal.proposed_patch_json?.accepted_change_ids as string[] | undefined
const decisions = shallowRef<Record<string, Decision | undefined>>(appliedIds
  ? Object.fromEntries(props.revision.changes.map(change => [change.id, appliedIds.includes(change.id) ? 'accepted' : 'rejected']))
  : {})
const preview = shallowRef<WordRevisionPreview>()
const renderedKey = shallowRef<string>()
const reload = shallowRef(0)
const error = shallowRef('')
const hovered = shallowRef<DocxRevisionPoint | null>(null)
const pinned = shallowRef<DocxRevisionPoint | null>(null)
const manualDraft = shallowRef<string | null>(null)
const manualText = shallowRef<string | null>(null)
const docx = computed(() => props.revision.kind === 'docx')
const editable = computed(() => props.proposal.status === 'draft' && !props.busy)
const pending = computed(() => props.revision.changes.filter(change => !decisions.value[change.id]))
const accepted = computed(() => props.revision.changes.filter(change => decisions.value[change.id] === 'accepted'))
const previewKey = computed(() => docx.value
  ? props.revision.changes.filter(change => decisions.value[change.id] !== 'rejected').map(change => change.id).join(',')
  : null)
const originalCharacters = computed(() => props.revision.kind === 'text' ? Array.from(props.revision.original) : [])
const candidate = computed(() => {
  if (props.revision.kind !== 'text') return ''
  if (manualText.value !== null) return manualText.value
  const pieces: string[] = []
  let start = 0
  for (const change of props.revision.changes) {
    pieces.push(originalCharacters.value.slice(start, change.start).join(''))
    pieces.push(decisions.value[change.id] === 'rejected' ? change.before : change.after)
    start = change.end
  }
  pieces.push(originalCharacters.value.slice(start).join(''))
  return pieces.join('')
})

function label(change: RevisionChange) {
  if ('line' in change) return t('doc_review.revision_line', { line: change.line })
  if ('kind' in change && change.kind === 'append') return t('doc_review.revision_chapter')
  return t(change.after ? 'doc_review.revision_replacement' : 'doc_review.revision_deletion')
}

const names = computed(() => Object.fromEntries(props.revision.changes.map(change => [change.id, label(change)])))
const displayedPoint = computed(() => pinned.value || hovered.value)
const displayedChange = computed(() => props.revision.changes.find(change => change.id === displayedPoint.value?.id))
const popoverStyle = computed(() => {
  const point = displayedPoint.value
  const bounds = reviewSurface.value?.getBoundingClientRect()
  if (!point || !bounds) return {}
  return {
    left: `${Math.max(12, Math.min(point.left, window.innerWidth - 352)) - bounds.left}px`,
    top: `${Math.max(12, Math.min(point.top + 6, window.innerHeight - 228)) - bounds.top}px`,
  }
})

watch([previewKey, reload], async ([key], _, cleanup) => {
  if (key === null) return
  const controller = new AbortController()
  cleanup(() => controller.abort())
  preview.value = undefined
  renderedKey.value = undefined
  error.value = ''
  hovered.value = pinned.value = null
  const route = [props.wsId, props.assetId, props.proposal.thread_id || '', props.proposal.id].map(encodeURIComponent)
  try {
    const { data } = await api.post<{ content_base64: string; blocks: ReviewBlock[]; markers: DocxRevisionMarker[] }>(
      `/workspaces/${route[0]}/assets/${route[1]}/threads/${route[2]}/resolution/proposals/${route[3]}/docx-preview`,
      { revision_id: props.revision.id, change_ids: key ? key.split(',') : [] },
      { signal: controller.signal },
    )
    if (controller.signal.aborted) return
    const raw = atob(data.content_base64)
    const bytes = new Uint8Array(raw.length)
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
    preview.value = { bytes: bytes.buffer, blocks: data.blocks, markers: data.markers, key }
  } catch (reason) {
    if (!controller.signal.aborted) error.value = formatApiError(reason, t('file_preview.failed'), t)
  }
}, { immediate: true })

const ready = computed<ResolutionApplyPayload | null>(() => {
  if (manualDraft.value !== null) return null
  if (manualText.value !== null && props.revision.kind === 'text') {
    const normalize = (text: string) => text.replace(/\r\n?/g, '\n')
    return manualText.value.trim() && normalize(manualText.value) !== normalize(props.revision.original)
      ? { finalSourceText: manualText.value } : null
  }
  if (pending.value.length || !accepted.value.length || (docx.value && renderedKey.value !== previewKey.value)) return null
  return { acceptedChangeIds: accepted.value.map(change => change.id) }
})
watch(ready, payload => emit('ready', payload), { immediate: true })

function saveManualEdit() {
  manualText.value = manualDraft.value
  manualDraft.value = null
}

function choose(id: string, decision: Decision) {
  decisions.value = { ...decisions.value, [id]: decisions.value[id] === decision ? undefined : decision }
}

function chooseAll(decision: Decision) {
  decisions.value = { ...decisions.value, ...Object.fromEntries(pending.value.map(change => [change.id, decision])) }
}

function locate(change: RevisionChange) {
  if ('line' in change && typeof change.line === 'number') textEditor.value?.revealOriginalLine(change.line)
  else wordCanvas.value?.revealRevision(change.id)
}
</script>

<template>
  <div ref="reviewSurface" class="native-review">
    <section class="revision-preview">
      <template v-if="revision.kind === 'text'">
        <header class="diff-labels">
          <span>{{ t('doc_review.revision_original_text') }}</span>
          <div class="candidate-label">
            <span>{{ t('doc_review.revision_candidate_text') }}</span>
            <div v-if="editable" class="native-actions">
              <button v-if="manualDraft === null" class="btn-secondary" @click="manualDraft = candidate">
                {{ t('doc_review.revision_edit_document') }}
              </button>
              <template v-else>
                <button class="btn-secondary" @click="manualDraft = null">{{ t('common.cancel') }}</button>
                <button class="btn-primary" :disabled="!manualDraft.trim()" @click="saveManualEdit">
                  {{ t('doc_review.revision_edit_document_save') }}
                </button>
              </template>
            </div>
          </div>
        </header>
        <div class="text-revision-editor">
          <MonacoDiffViewer
            ref="textEditor" :original="revision.original" :modified="manualDraft ?? candidate"
            :editable="manualDraft !== null"
            :language="markdown ? 'markdown' : 'plaintext'" theme="vs" word-wrap="on" render-side-by-side
            @update:modified="manualDraft = $event"
          />
        </div>
      </template>
      <DocxReviewCanvas
        v-else-if="preview"
        ref="wordCanvas"
        :ws-id="wsId" :asset-id="assetId" :name="assetName" :preview-bytes="preview.bytes"
        :blocks="preview.blocks" :revision-markers="preview.markers" :revision-names="names"
        :markers-by-block="{}" selected-thread-id="" editing-block-id=""
        :inline-review-enabled="false" :can-manual-edit="false"
        @preview-rendered="renderedKey = preview?.key"
        @revision-hover="hovered = $event"
        @revision-open="pinned = pinned?.id === $event.id ? null : $event"
      />
      <div v-else class="preview-state">
        <template v-if="error">
          <span role="alert">{{ error }}</span>
          <button class="btn-secondary" type="button" @click="reload++">{{ t('common.retry') }}</button>
        </template>
        <span v-else role="status">{{ t('common.loading') }}</span>
      </div>
    </section>

    <aside v-if="manualText !== null || manualDraft !== null" class="native-changes">
      <header>{{ t('doc_review.revision_edit_document') }}</header>
      <div class="native-change-list">
        <p class="change-note">{{ t('doc_review.revision_edit_document_hint') }}</p>
        <button v-if="manualDraft === null" class="btn-secondary" @click="manualText = null">
          {{ t('doc_review.revision_manual_reset') }}
        </button>
      </div>
    </aside>
    <aside v-else class="native-changes">
      <header>
        <strong>{{ t('doc_review.revision_pending_count', { count: pending.length }) }}</strong>
        <div v-if="editable" class="native-actions">
          <button class="btn-secondary" :disabled="!pending.length" @click="chooseAll('accepted')">
            {{ t('doc_review.revision_accept_all') }}
          </button>
          <button class="btn-secondary" :disabled="!pending.length" @click="chooseAll('rejected')">
            {{ t('doc_review.revision_reject_all') }}
          </button>
        </div>
      </header>
      <div class="native-change-list">
        <p v-if="!revision.changes.length" class="change-note">{{ t('doc_review.revision_no_pending') }}</p>
        <p v-else-if="editable && !pending.length && !accepted.length" class="change-note">
          {{ t('doc_review.revision_nothing_selected') }}
        </p>
        <article
          v-for="change in revision.changes" :key="change.id" class="native-change"
          :data-change-id="change.id" :data-decision="decisions[change.id]"
        >
          <button class="locate-change" type="button" @click="locate(change)">{{ names[change.id] }}</button>
          <del v-if="change.before">{{ change.before }}</del>
          <ins v-if="change.after">{{ 'title' in change && change.title ? change.title : change.after }}</ins>
          <div v-if="editable" class="native-actions">
            <button class="btn-secondary" :aria-pressed="decisions[change.id] === 'accepted'" @click="choose(change.id, 'accepted')">
              {{ t('doc_review.revision_accept') }}
            </button>
            <button class="btn-secondary" :aria-pressed="decisions[change.id] === 'rejected'" @click="choose(change.id, 'rejected')">
              {{ t('doc_review.revision_reject') }}
            </button>
          </div>
        </article>
      </div>
    </aside>

    <div
      v-if="displayedChange" class="revision-popover" :class="{ pinned }" :style="popoverStyle"
      :role="pinned ? 'dialog' : 'tooltip'" :aria-label="names[displayedChange.id]"
      @keydown.esc="pinned = null"
    >
      <header>
        <strong>{{ names[displayedChange.id] }}</strong>
        <button v-if="pinned" type="button" :aria-label="t('common.close')" @click="pinned = null">×</button>
      </header>
      <del v-if="displayedChange.before">{{ displayedChange.before }}</del>
      <ins v-if="displayedChange.after">{{ displayedChange.after }}</ins>
      <div v-if="pinned && editable" class="native-actions">
        <button class="btn-secondary" :aria-pressed="decisions[displayedChange.id] === 'accepted'"
          @click="choose(displayedChange.id, 'accepted')">{{ t('doc_review.revision_accept') }}</button>
        <button class="btn-secondary" :aria-pressed="decisions[displayedChange.id] === 'rejected'"
          @click="choose(displayedChange.id, 'rejected')">{{ t('doc_review.revision_reject') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.native-review { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 25%); gap: 12px; height: min(61vh, 620px); min-height: 250px; }
.native-review > * { min-height: 0; min-width: 0; }
.revision-preview, .native-changes { display: flex; flex-direction: column; border: 1px solid #d8e0e9; border-radius: 10px; overflow: hidden; }
.revision-preview > :deep(.docx-review-canvas) { height: 100%; }
.diff-labels { display: grid; grid-template-columns: 1fr 1fr; padding: 9px 12px; background: #f6f8fa; border-bottom: 1px solid #d8e0e9; font-size: 12px; font-weight: 600; }
.candidate-label { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding-inline-start: 12px; }
.text-revision-editor { flex: 1; min-height: 0; }
.native-changes > header { display: flex; flex-direction: column; gap: 8px; padding: 10px; border-bottom: 1px solid #d8e0e9; font-size: 13px; }
.native-change-list { overflow: auto; padding: 8px; }
.native-change { display: grid; gap: 6px; margin-bottom: 8px; padding: 8px; border: 1px solid #d8e0e9; border-radius: 8px; font-size: 12px; }
.native-change[data-decision="accepted"] { border-color: #a4d6b3; }
.native-change[data-decision="rejected"] { background: #f6f8fa; }
.native-change[data-decision="rejected"] > :is(del, ins) { opacity: .65; }
.native-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.native-actions > button { padding: 3px 6px; font-size: 12px; }
.native-actions > button[aria-pressed="true"] { background: #dbeafe; border-color: #93c5fd; color: #1e3a8a; }
.locate-change { justify-self: start; padding: 0; border: 0; background: none; color: var(--color-text-muted); text-align: start; cursor: pointer; }
.locate-change:hover { text-decoration: underline; }
.change-note { margin: 6px 4px; font-size: 12px; color: var(--color-text-muted); }
.preview-state { margin: auto; display: grid; justify-items: center; gap: 8px; padding: 14px; color: var(--color-text-muted); }
del, ins { display: block; max-height: 7em; overflow: auto; padding: 3px 6px; border-radius: 4px; white-space: pre-wrap; overflow-wrap: anywhere; }
del { background: #fef2f2; color: #991b1b; }
ins { background: #ecfdf5; color: #065f46; text-decoration: none; }
.revision-popover { position: absolute; z-index: 2; width: min(340px, calc(100vw - 24px)); display: grid; gap: 6px; padding: 9px; background: #fff; border: 1px solid #c8d5e0; border-radius: 8px; box-shadow: 0 6px 18px #172f4a22; font-size: 12px; pointer-events: none; }
.revision-popover.pinned { pointer-events: auto; }
.revision-popover > header { display: flex; align-items: center; justify-content: space-between; }
.revision-popover button { border: 0; background: transparent; cursor: pointer; }
@media (max-width: 740px) {
  .native-review { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(190px, 1fr) minmax(100px, 32%); }
  .native-changes > header { flex-direction: row; flex-wrap: wrap; justify-content: space-between; align-items: center; }
}
</style>
