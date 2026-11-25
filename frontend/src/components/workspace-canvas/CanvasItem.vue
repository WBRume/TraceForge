<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronRight, Link, PencilLine } from '@/components/icons'
import { cardStatus, isDocument, sourceIcons, type CanvasNode } from './model'

const props = defineProps<{ node: CanvasNode; active: boolean; linked: boolean }>()
const emit = defineEmits<{
  press: [event: PointerEvent, handle?: 'resize' | 'connect']
  open: []
  focus: []
}>()
const { t, te } = useI18n()
const position = computed(() => ({
  width: `${props.node.size.width}px`,
  height: `${props.node.size.height}px`,
  transform: `translate(${props.node.position.x}px, ${props.node.position.y}px)`,
}))
const type = computed(() => props.node.reference?.kind || props.node.kind)
const label = computed(() => t(`workspace_canvas.kind.${type.value}`))
const name = computed(() => props.node.kind === 'card'
  ? props.node.details?.title || t('workspace_canvas.source_unavailable') : props.node.text || label.value)
const status = computed(() => {
  const { details, reference } = props.node
  return reference && details ? cardStatus({ reference, details }, t, te) : ''
})
const isParagraph = computed(() => !!props.node.reference && isDocument(props.node.reference) && Boolean(props.node.reference.block))
</script>

<template>
  <article
    class="canvas-item" :class="[`kind-${node.kind}`, `type-${type}`, `color-${node.color}`, { active, linked }]"
    :style="position" :data-canvas-node="node.id" :data-node-kind="node.kind"
    :data-source-kind="node.reference?.kind" :tabindex="node.kind === 'frame' ? undefined : 0"
    :data-source-id="node.reference?.id" :data-automatic="node.automatic || undefined"
    :aria-label="name" @focus.self="emit('focus')" @keydown.enter.self.prevent="emit('open')"
    @pointerdown.stop="node.kind !== 'frame' && emit('press', $event)" @dblclick.stop="node.kind !== 'frame' && emit('open')"
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
        <span class="item-type">{{ isParagraph ? t('workspace_canvas.paragraph') : label }}</span>
        <span v-if="status" class="status" :data-status="node.details?.status" :title="status">{{ status }}</span>
      </header>
      <h3 class="card-title" :title="name">{{ name }}</h3>
      <p v-if="node.details?.detail" class="card-detail">{{ node.details.detail }}</p>
      <div v-if="node.details" class="item-footer">
        <span v-if="node.details.context" class="source-context" :title="node.details.context">{{ node.details.context }}</span>
        <button class="open-source" type="button" :aria-label="t('workspace_canvas.open_asset')"
          :title="t('workspace_canvas.open_asset')" @pointerdown.stop @click.stop="emit('open')"><ChevronRight :size="16" /></button>
      </div>
    </template>

    <button v-if="node.kind !== 'frame'" class="connect-handle" type="button" tabindex="-1"
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
.type-document, .type-plan_document { --source-color: #895021; --source-tint: #fff2e2; }
.type-case { --source-color: #78488c; --source-tint: #f7ecfe; }
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
.item-type { color: var(--canvas-muted); font-size: 11px; font-weight: 700; white-space: nowrap; }
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
.open-source:is(:hover, :focus-visible) { background: var(--canvas-hover); color: var(--canvas-accent); }
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
