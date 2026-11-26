<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, ChevronRight, ExternalLink, Link, PencilLine } from '@/components/icons'
import { cardStatus, isDocument, sourceIcons, type CanvasNode } from './model'

const props = defineProps<{
  node: CanvasNode; active: boolean; linked: boolean; entry?: boolean; compact?: boolean; quarterId?: string
  tree?: boolean; expanded?: boolean; busy?: boolean
}>()
const emit = defineEmits<{
  press: [event: PointerEvent, handle?: 'resize' | 'connect']
  open: []
  focus: []
  toggle: []
}>()
const { t, te } = useI18n()
const position = computed(() => ({
  width: `${props.node.size.width}px`,
  height: `${props.node.size.height}px`,
  transform: `translate(${props.node.position.x}px, ${props.node.position.y}px)`,
}))
const type = computed(() => props.node.reference?.kind === 'task' && props.node.details?.task_type === 'DIAGNOSIS'
  ? 'diagnosis_task' : props.node.reference?.kind || props.node.kind)
const label = computed(() => t(`workspace_canvas.kind.${type.value}`))
const name = computed(() => props.node.kind === 'card'
  ? props.node.details?.title || t('workspace_canvas.source_unavailable') : props.node.text || label.value)
const status = computed(() => {
  const { details, reference } = props.node
  return reference && details ? cardStatus({ reference, details }, t, te) : ''
})
const isParagraph = computed(() => !!props.node.reference && isDocument(props.node.reference) && Boolean(props.node.reference.block))
const detail = computed(() => props.node.details?.detail || (isParagraph.value ? props.node.text : ''))
const summaryQuarter = computed(() => props.node.historicalQuarter && t('workspace_canvas.quarter.name', {
  year: props.node.historicalQuarter.label_year, number: props.node.historicalQuarter.number,
}))
const summaryType = computed(() => t(props.node.historicalQuarter && props.quarterId && props.node.historicalQuarter.id > props.quarterId
  ? 'workspace_canvas.quarter.future_requirement' : 'workspace_canvas.quarter.historical_requirement'))
const branchAction = computed(() => t(props.expanded ? 'workspace_canvas.tree.collapse' : 'workspace_canvas.tree.expand'))
</script>

<template>
  <article
    class="canvas-item" :class="[`kind-${node.kind}`, `type-${type}`, `color-${node.color}`, { active, linked, entry, compact,
      'historical-card': !!node.historicalQuarter, 'tree-card': tree,
      tile: node.kind === 'card' && node.size.width < 200 }]"
    :style="position" :data-canvas-node="node.id" :data-node-kind="node.kind"
    :data-source-kind="node.reference?.kind" :data-domain-id="node.domainId" :tabindex="node.kind === 'frame' ? undefined : 0"
    :data-source-id="node.reference?.id" :data-automatic="node.automatic || undefined" :data-domain-entry="entry || undefined"
    :data-historical-quarter="node.historicalQuarter?.id"
    :aria-label="name" @focus.self="emit('focus')" @keydown.enter.self.prevent="emit('open')"
    @pointerdown.stop="node.kind !== 'frame' && !node.historicalQuarter && emit('press', $event)"
    @dblclick.stop="node.kind !== 'frame' && emit('open')"
  >
    <template v-if="node.kind === 'frame'">
      <button class="frame-label" type="button" @focus="emit('focus')" @pointerdown.stop="emit('press', $event)"
        @dblclick.stop="emit('open')" @keydown.enter.prevent="emit('open')">
        <span class="frame-color" />{{ name }}
      </button>
      <button class="resize-handle" type="button" tabindex="-1" :aria-label="t('workspace_canvas.resize_frame')"
        :title="t('workspace_canvas.resize_frame')" @pointerdown.stop="emit('press', $event, 'resize')" />
    </template>

    <template v-else-if="node.kind === 'note'">
      <header class="item-top note-top"><PencilLine :size="15" /><span>{{ label }}</span></header>
      <p class="note-body" :class="{ placeholder: !node.text }">{{ node.text || t('workspace_canvas.note_placeholder') }}</p>
    </template>

    <template v-else-if="node.reference">
      <header class="item-top">
        <component :is="sourceIcons[node.reference.kind]" class="source-icon" :size="16" />
        <span class="item-type">{{ summaryQuarter ? summaryType
          : isParagraph ? t('workspace_canvas.paragraph') : label }}</span>
        <span v-if="status" class="status" :data-status="node.details?.status" :title="status">{{ status }}</span>
        <button v-if="!summaryQuarter && node.details" class="open-source" type="button"
          :aria-label="t('workspace_canvas.open_asset')" :title="t('workspace_canvas.open_asset')"
          @pointerdown.stop @dblclick.stop @click.stop="emit('open')"><ExternalLink :size="15" /></button>
      </header>
      <h3 class="card-title" :title="name">{{ name }}</h3>
      <p v-if="detail && (!compact || summaryQuarter)" class="card-detail">{{ detail }}</p>
      <div v-if="summaryQuarter || (node.details?.context && !compact)" class="item-footer">
        <span v-if="summaryQuarter" class="historical-quarter">{{ summaryQuarter }}</span>
        <span v-else class="source-context" :title="node.details?.context ?? undefined">{{ node.details?.context }}</span>
        <button v-if="summaryQuarter" class="history-detail" type="button"
          @pointerdown.stop @dblclick.stop @click.stop="emit('open')">{{ t('workspace_canvas.quarter.view_detail') }}<ChevronRight :size="14" /></button>
      </div>
      <button v-if="node.expandable" type="button" class="tree-disclosure" :aria-expanded="!!expanded"
        :aria-label="branchAction" :title="branchAction" :disabled="busy"
        @pointerdown.stop @dblclick.stop @click.stop="emit('toggle')">
        <component :is="expanded ? ChevronDown : ChevronRight" :size="17" />
      </button>
    </template>

    <button v-if="node.kind !== 'frame' && !node.historicalQuarter" class="connect-handle" type="button" tabindex="-1"
      :aria-label="t('workspace_canvas.connect_from')" :title="t('workspace_canvas.connect_from')"
      @pointerdown.stop="emit('press', $event, 'connect')" @dblclick.stop><Link :size="13" /></button>
  </article>
</template>

<style scoped>
.canvas-item {
  position: absolute;
  inset: 0 auto auto 0;
  box-sizing: border-box;
  pointer-events: auto;
  user-select: none;
  outline: none;
  cursor: grab;
  color: var(--canvas-ink);
  --source-color: #304d9b;
  --source-tint: #eef2ff;
  --note-fill: #fff0b5;
  --note-ink: #6c5113;
}
.type-task { --source-color: #186866; --source-tint: #e5f4f1; }
.type-diagnosis_task { --source-color: #235b8a; --source-tint: #e7f2fa; }
.type-document, .type-plan_document, .type-requirement_document { --source-color: #895021; --source-tint: #fff2e2; }
.type-case { --source-color: #78488c; --source-tint: #f7ecfe; }
.type-playbook { --source-color: #365b39; --source-tint: #e9f4e9; }
.color-mint { --note-fill: #dcf3dd; --note-ink: #2f623f; }
.color-blue { --note-fill: #deedff; --note-ink: #375d94; }
.color-lilac { --note-fill: #eee4ff; --note-ink: #67478d; }
.color-rose { --note-fill: #fce2e8; --note-ink: #91485d; }
.kind-card, .kind-note {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 13px 15px;
  border-radius: 12px;
  border: 1px solid var(--canvas-line);
  background: var(--canvas-chrome);
  box-shadow: 0 3px 8px #253b6010;
  transition: box-shadow 120ms ease, border-color 120ms ease;
}
.kind-card:hover, .kind-note:hover { box-shadow: 0 6px 18px #253b6020; }
.kind-card.entry { border-color: #7bb3da; background: #fafdff; }
.history-detail { display: inline-flex; gap: 3px; align-items: center; color: #17577d;
  background: #e9f4fe; border: 0; border-radius: 6px; padding: 4px 6px; font: inherit; font-size: 12px; cursor: pointer; white-space: nowrap; }
.historical-quarter { color: #576787; font-size: 12px; white-space: nowrap; }
.historical-card .item-footer { justify-content: space-between; gap: 3px; }
.kind-card.historical-card { border-color: #adc3de; background: #f8fbff; cursor: pointer; gap: 4px; padding: 10px 12px; }
.historical-card.compact .history-detail,
.historical-card.compact .historical-quarter { font-size: 18px; }
.historical-card.compact .card-title { font-size: var(--canvas-compact-title, 24px); line-height: 1.12; }
.historical-card .card-detail { flex: 0 0 auto; font-size: 15px; line-height: 1.26; }
.historical-card.compact .card-detail { font-size: var(--canvas-compact-summary, 18px); line-height: 1.1; -webkit-line-clamp: 1; }
.tree-card:not(.historical-card) .card-detail { display: none; }
.tree-disclosure {
  position: absolute;
  z-index: 1;
  inset: auto -14px -11px auto;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--canvas-line);
  border-radius: 50%;
  color: var(--canvas-accent);
  background: var(--canvas-chrome);
  box-shadow: 0 2px 5px #20355816;
  cursor: pointer;
}
.tree-disclosure:not(:disabled):hover { background: var(--canvas-hover); border-color: var(--canvas-accent); }
.tree-disclosure:disabled { opacity: .55; cursor: wait; }
.historical-card .item-top { height: 19px; }
.compact .card-title { font-size: var(--canvas-compact-title, 25px); }
.compact .item-type, .compact .status { font-size: var(--canvas-compact-meta, 16px); }
.compact .status { line-height: 1.25; }
.compact .source-icon { width: var(--canvas-compact-meta, 16px); height: var(--canvas-compact-meta, 16px); }
.kind-card.compact { gap: 10px; }
.kind-card.tile { gap: 4px; padding: 8px 10px; }
.tile .card-detail, .tile .source-context { display: none; }
.tile .item-footer { position: absolute; right: 6px; bottom: 3px; }
.tile .card-title { font-size: 14px; }
.tile.compact .card-title { font-size: 21px; }
.tile.compact .item-type, .tile.compact .status { font-size: 13px; }
.canvas-item.active, .canvas-item.linked, .canvas-item:focus-visible {
  border-color: var(--canvas-accent);
  box-shadow: 0 0 0 2px var(--canvas-accent), 0 6px 18px #253b6020;
}
.kind-note {
  border-color: color-mix(in srgb, var(--note-ink) 23%, transparent);
  color: #312b24;
  background: var(--note-fill);
  box-shadow: 0 4px 10px #58441618;
}
.item-top { display: flex; align-items: center; gap: 7px; min-width: 0; height: 22px; flex: 0 0 auto; }
.note-top { color: var(--note-ink); font-size: 11px; font-weight: 700; }
.source-icon { color: var(--source-color); flex: 0 0 auto; }
.item-type { color: var(--canvas-muted); font-size: 11px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.status {
  margin-inline-start: auto;
  max-width: 65%;
  padding: 2px 7px;
  border-radius: 5px;
  background: var(--source-tint);
  color: var(--source-color);
  font-size: 10px;
  line-height: 16px;
  font-weight: 750;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status:is([data-status='COMPLETED'], [data-status='APPROVED'], [data-status='VERIFIED']) { color: #216843; background: #e2f4e7; }
.status:is([data-status='FAILED'], [data-status='REJECTED'], [data-status='EXCERPT_CHANGED']) { color: #9c3043; background: #ffe8ed; }
.status:is([data-status='RUNNING'], [data-status='IN_PROGRESS'], [data-status='IN_REVIEW']) { color: #264fb0; background: #e9efff; }
.card-title, .card-detail, .note-body { margin: 0; overflow-wrap: anywhere; }
.card-title, .card-detail { overflow: hidden; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.card-title { font-size: 15px; font-weight: 720; line-height: 1.34; flex: 0 0 auto; }
.card-detail { font-size: 12px; line-height: 1.5; color: var(--canvas-muted); }
.item-footer { margin-top: auto; display: flex; align-items: center; justify-content: flex-end; gap: 6px; min-height: 20px; }
.source-context { flex: 1; min-width: 0; color: var(--canvas-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; }
.open-source, .connect-handle {
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 5px;
  padding: 3px;
  background: transparent;
  color: var(--canvas-muted);
  cursor: pointer;
}
.open-source { flex: 0 0 26px; width: 26px; height: 26px; }
.item-type + .open-source { margin-inline-start: auto; }
.open-source:is(:hover, :focus-visible) { background: var(--canvas-hover); color: var(--canvas-accent); }
.open-source:focus-visible, .tree-disclosure:focus-visible {
  outline: 2px solid var(--canvas-accent);
  outline-offset: 2px;
}
.connect-handle {
  position: absolute;
  z-index: 2;
  inset: 50% -12px auto auto;
  transform: translateY(-50%);
  width: 24px;
  height: 24px;
  border-radius: 50%;
  color: var(--canvas-accent);
  border: 1px solid var(--canvas-line);
  background: var(--canvas-chrome);
  box-shadow: 0 2px 6px #2035581c;
  opacity: 0;
  cursor: crosshair;
  pointer-events: none;
  transition: opacity 120ms ease;
}
.canvas-item:is(:hover, :focus-within, .active) .connect-handle { opacity: 1; pointer-events: auto; }
.note-body { white-space: pre-wrap; font-size: 15px; font-weight: 500; line-height: 1.48; overflow: hidden; }
.note-body.placeholder { color: var(--note-ink); font-weight: 400; }
.kind-frame {
  border: 1px solid color-mix(in srgb, var(--note-ink) 40%, transparent);
  border-radius: 15px;
  background: color-mix(in srgb, var(--note-fill) 20%, transparent);
  pointer-events: none;
}
.frame-label {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 6px;
  top: -30px;
  left: 0;
  height: 28px;
  max-width: 100%;
  padding: 0 9px;
  border: 1px solid color-mix(in srgb, var(--note-ink) 25%, transparent);
  border-radius: 6px;
  background: var(--note-fill);
  color: var(--note-ink);
  font: inherit;
  font-size: 12px;
  font-weight: 750;
  overflow: hidden;
  white-space: nowrap;
  cursor: grab;
  pointer-events: auto;
}
.frame-color { flex: 0 0 auto; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.resize-handle {
  position: absolute;
  right: -4px;
  bottom: -4px;
  width: 15px;
  height: 15px;
  border: 0;
  border-right: 3px solid var(--note-ink);
  border-bottom: 3px solid var(--note-ink);
  background: transparent;
  border-bottom-right-radius: 5px;
  cursor: nwse-resize;
  pointer-events: auto;
}
@media (prefers-reduced-motion: reduce) { .canvas-item, .connect-handle { transition: none; } }
</style>
