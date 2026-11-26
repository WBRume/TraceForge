<script setup lang="ts">
import { computed, shallowRef, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { InputInstance } from 'element-plus'
import { Check } from '@/components/icons'
import { noteColors, type CanvasNode, type NodePatch } from './model'

const props = defineProps<{ node: CanvasNode; saving: boolean }>()
const emit = defineEmits<{ save: [patch: NodePatch]; close: [] }>()
const { t } = useI18n()
const input = useTemplateRef<InputInstance>('input')
const initialText = shallowRef(props.node.text)
const draft = shallowRef(props.node.text)
const color = shallowRef(props.node.color)
const conflict = computed(() => props.node.text !== initialText.value && props.node.text !== draft.value)
const title = computed(() => t(props.node.kind === 'frame' ? 'workspace_canvas.edit_frame' : 'workspace_canvas.edit_note'))

function useLatest() {
  draft.value = props.node.text
  initialText.value = props.node.text
  input.value?.focus()
}

function save() {
  if (props.saving) return
  emit('save', { text: draft.value, color: color.value, expected_text: conflict.value ? props.node.text : initialText.value })
}
</script>

<template>
  <el-dialog :model-value="true" :title="title" width="min(520px, 95vw)" append-to-body
    :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving"
    @opened="input?.focus()" @close="emit('close')">
    <div class="canvas-editor">
      <el-input ref="input" v-model="draft" type="textarea" :rows="node.kind === 'frame' ? 2 : 5"
        :maxlength="node.kind === 'frame' ? 120 : 4000" :disabled="saving"
        :aria-label="title" :placeholder="t(node.kind === 'frame' ? 'workspace_canvas.kind.frame' : 'workspace_canvas.note_input')"
        @keydown.ctrl.enter.prevent="save" @keydown.meta.enter.prevent="save" />
      <div class="palette" :aria-label="t('workspace_canvas.color_label')">
        <button v-for="entry in noteColors" :key="entry" type="button" class="swatch" :class="`swatch-${entry}`"
          :title="t(`workspace_canvas.color.${entry}`)" :aria-label="t(`workspace_canvas.color.${entry}`)" :aria-pressed="color === entry"
          :disabled="saving" @click="color = entry"><Check v-if="color === entry" :size="14" /></button>
      </div>
      <el-alert v-if="conflict" type="warning" :closable="false" :title="t('workspace_canvas.edit_conflict')" />
    </div>
    <template #footer>
      <el-button :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</el-button>
      <el-button v-if="conflict" :disabled="saving" @click="useLatest">{{ t('workspace_canvas.use_latest') }}</el-button>
      <el-button type="primary" :loading="saving" @click="save">{{ t(conflict ? 'workspace_canvas.save_mine' : 'common.save') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.canvas-editor { display: grid; gap: 12px; }
.palette { display: flex; align-items: center; gap: 7px; }
.swatch { display: grid; place-items: center; width: 26px; height: 26px; padding: 0; border: 1px solid #24344e22; border-radius: 50%; color: #35415a; cursor: pointer; }
.swatch[aria-pressed='true'] { border-color: var(--el-color-primary); }
.swatch-yellow { background: #fff0b5; }.swatch-mint { background: #dcf3dd; }.swatch-blue { background: #deedff; }.swatch-lilac { background: #eee4ff; }.swatch-rose { background: #fce2e8; }
</style>
