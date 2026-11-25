<script setup lang="ts">
import { computed, onMounted, shallowRef, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, X } from '@/components/icons'
import { noteColors, type CanvasNode, type NodePatch } from './model'

const props = defineProps<{ node: CanvasNode; saving: boolean }>()
const emit = defineEmits<{ save: [patch: NodePatch]; close: [] }>()
const { t } = useI18n()
const input = useTemplateRef<HTMLTextAreaElement>('input')
const initialText = shallowRef(props.node.text)
const draft = shallowRef(props.node.text)
const color = shallowRef(props.node.color)
const conflict = computed(() => props.node.text !== initialText.value && props.node.text !== draft.value)
const title = computed(() => t(props.node.kind === 'frame' ? 'workspace_canvas.edit_frame' : 'workspace_canvas.edit_note'))

onMounted(() => input.value?.focus())

function useLatest() {
  draft.value = props.node.text
  initialText.value = props.node.text
  input.value?.focus()
}

function save() {
  emit('save', { text: draft.value, color: color.value, expected_text: conflict.value ? props.node.text : initialText.value })
}
</script>

<template>
  <form class="canvas-editor" :aria-label="title" @submit.prevent="save" @keydown.esc.stop.prevent="emit('close')">
    <header class="editor-head"><h2>{{ title }}</h2>
      <button type="button" class="editor-close" :aria-label="t('common.close')" :disabled="saving" @click="emit('close')"><X :size="16" /></button>
    </header>
    <textarea ref="input" v-model="draft" :rows="node.kind === 'frame' ? 2 : 5" :maxlength="node.kind === 'frame' ? 120 : 4000"
      :aria-label="title" :placeholder="t(node.kind === 'frame' ? 'workspace_canvas.kind.frame' : 'workspace_canvas.note_input')"
      @keydown.ctrl.enter.prevent="save" @keydown.meta.enter.prevent="save" />
    <div class="palette" :aria-label="t('workspace_canvas.color_label')">
      <button v-for="entry in noteColors" :key="entry" type="button" class="swatch" :class="`swatch-${entry}`"
        :title="t(`workspace_canvas.color.${entry}`)" :aria-label="t(`workspace_canvas.color.${entry}`)" :aria-pressed="color === entry"
        @click="color = entry"><Check v-if="color === entry" :size="14" /></button>
    </div>
    <p v-if="conflict" class="editor-conflict" role="status">{{ t('workspace_canvas.edit_conflict') }}</p>
    <div class="edit-actions">
      <button v-if="conflict" class="edit-secondary" type="button" @click="useLatest">{{ t('workspace_canvas.use_latest') }}</button>
      <button class="edit-primary" type="submit" :disabled="saving">{{ t(conflict ? 'workspace_canvas.save_mine' : 'common.save') }}</button>
    </div>
  </form>
</template>

<style scoped>
.canvas-editor { position: absolute; z-index: 6; inset: 67px 16px auto auto; width: min(320px, calc(100% - 82px)); display: grid; gap: 11px; padding: 14px; border: 1px solid var(--canvas-line); border-radius: 12px; background: var(--canvas-chrome); color: var(--canvas-ink); box-shadow: 0 12px 32px #25345928; }
.editor-head, .edit-actions { display: flex; align-items: center; justify-content: space-between; gap: 7px; }
.editor-head h2 { margin: 0; font-size: 14px; font-weight: 720; }
.editor-close { display: grid; place-items: center; border: 0; border-radius: 5px; padding: 4px; background: transparent; color: var(--canvas-muted); cursor: pointer; }
.editor-close:hover { background: var(--canvas-hover); }
.canvas-editor textarea { resize: vertical; width: 100%; min-height: 62px; max-height: 260px; border: 1px solid var(--canvas-line); border-radius: 7px; padding: 8px; box-sizing: border-box; background: var(--canvas-paper); font: inherit; color: var(--canvas-ink); font-size: 13px; line-height: 1.5; }
.canvas-editor textarea:focus-visible { outline: 1px solid var(--canvas-accent); }
.palette { display: flex; align-items: center; gap: 7px; }
.swatch { display: grid; place-items: center; width: 26px; height: 26px; padding: 0; border: 1px solid #24344e22; border-radius: 50%; color: #35415a; cursor: pointer; }
.swatch[aria-pressed='true'] { border-color: var(--canvas-accent); }
.swatch-yellow { background: #fff0b5; }.swatch-mint { background: #dcf3dd; }.swatch-blue { background: #deedff; }.swatch-lilac { background: #eee4ff; }.swatch-rose { background: #fce2e8; }
.edit-actions { justify-content: flex-end; }
.edit-primary, .edit-secondary { min-height: 33px; padding: 0 10px; border: 1px solid var(--canvas-accent); border-radius: 6px; color: #fff; background: var(--canvas-accent); font: inherit; font-size: 12px; cursor: pointer; }
.edit-secondary { border-color: var(--canvas-line); color: var(--canvas-ink); background: var(--canvas-chrome); }
.edit-primary:disabled { opacity: .55; }
.editor-conflict { margin: 0; font-size: 12px; color: var(--canvas-muted); }
</style>
