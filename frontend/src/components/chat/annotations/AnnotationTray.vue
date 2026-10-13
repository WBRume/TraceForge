<script setup lang="ts">
import { computed, nextTick, shallowRef, useId, useTemplateRef, watch } from 'vue'
import { MessageSquare, Pencil, Trash2, X } from '@/components/icons'
import { annotationLabel } from '@/composables/chat/annotations/contextAnnotations'
import { injectContextAnnotations } from '@/composables/chat/annotations/useContextAnnotations'
import { useAnnotationPreview } from '@/composables/chat/annotations/useAnnotationPreview'

const props = defineProps<{ disabled?: boolean }>()
const annotations = injectContextAnnotations()
const items = computed(() => annotations?.items.value || [])
const anchor = useTemplateRef<HTMLElement>('anchor')
const panel = useTemplateRef<HTMLElement>('panel')
const { expanded, position, enter, leave, toggle, cancelClose, focusOut } = useAnnotationPreview(
  () => annotations?.contextKey.value, () => items.value.length, anchor, panel,
)
const previewId = `annotation-preview-${useId()}`
const editingId = shallowRef('')
const draft = shallowRef('')
const editInput = shallowRef<HTMLTextAreaElement[] | null>(null)
watch(expanded, active => { if (!active) editingId.value = '' })
async function edit(id: string, comment: string) {
  editingId.value = id; draft.value = comment
  await nextTick()
  editInput.value?.[0]?.focus()
}
function save() { if (!props.disabled) { annotations?.update(editingId.value, draft.value); editingId.value = '' } }
</script>

<template>
  <section v-if="items.length" class="annotation-tray" aria-label="待发送批注">
    <div ref="anchor" class="annotation-summary" :class="{ 'is-open': expanded }" @pointerenter="enter" @pointerleave="leave" @focusin="enter()" @focusout="focusOut">
      <button type="button" class="annotation-toggle" :aria-expanded="expanded" :aria-controls="previewId" aria-haspopup="dialog" @click="toggle"><MessageSquare :size="12" />{{ items.length }} 条批注</button>
      <button type="button" class="annotation-clear" aria-label="清空批注" title="清空批注" :disabled="disabled" @click.stop="annotations?.clear()"><X :size="12" /></button>
    </div>
    <Teleport to="body">
      <div v-if="expanded" :id="previewId" ref="panel" class="annotation-preview" :style="position" role="dialog" aria-label="批注预览" @pointerenter="cancelClose" @pointerleave="leave" @focusout="focusOut">
        <ol class="annotation-list">
          <li v-for="(item, index) in items" :key="item.id" class="annotation-item">
            <span class="annotation-index">{{ index + 1 }}.</span>
            <div class="annotation-body">
              <div class="annotation-source" :title="item.source.kind === 'diff' ? annotationLabel(item.source) : undefined">{{ item.source.kind === 'diff' ? annotationLabel(item.source) : '所选文本：' }}</div>
              <blockquote :title="item.selectedText">{{ item.selectedText }}</blockquote>
              <form v-if="editingId === item.id" @submit.prevent="save">
                <textarea ref="editInput" v-model="draft" rows="2" aria-label="编辑批注内容" placeholder="补充说明（可选）" :disabled="disabled" @keydown.esc.prevent="editingId = ''" @keydown.ctrl.enter.prevent="save" />
                <div class="edit-actions"><button type="button" @click="editingId = ''">取消</button><button type="submit" :disabled="disabled">保存</button></div>
              </form>
              <p v-else-if="item.comment" class="annotation-comment">{{ item.comment }}</p>
            </div>
            <div class="annotation-actions">
              <button type="button" class="icon-button" :aria-label="`编辑批注 ${index + 1}`" title="编辑批注" :disabled="disabled" @click="edit(item.id, item.comment)"><Pencil :size="13" /></button>
              <button type="button" class="icon-button" :aria-label="`删除批注 ${index + 1}`" title="删除批注" :disabled="disabled" @click="annotations?.remove(item.id)"><Trash2 :size="13" /></button>
            </div>
          </li>
        </ol>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.annotation-tray { min-width: 0; margin: 4px 0 2px; font-size: 12px; color: #475569; }
.annotation-summary { display: inline-flex; align-items: center; gap: 1px; min-width: 0; max-width: 100%; border: 1px solid #e5e7eb; border-radius: 12px; padding: 2px 3px 2px 2px; background: #fff; }
button { font: inherit; color: inherit; cursor: pointer; border: 0; background: transparent; }
button:disabled { opacity: .4; cursor: default; }
.annotation-toggle { display: inline-flex; align-items: center; gap: 5px; border-radius: 8px; padding: 3px 4px; font-size: 11px; white-space: nowrap; }
.annotation-clear { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; flex: none; border: 1px solid #e5e7eb; border-radius: 50%; opacity: 0; pointer-events: none; transition: opacity 120ms ease; }
.annotation-summary:hover .annotation-clear, .annotation-summary:focus-within .annotation-clear, .annotation-summary.is-open .annotation-clear { opacity: 1; pointer-events: auto; }
.annotation-clear:hover { background: #f3f4f6; color: #111827; }
.icon-button { display: inline-flex; align-items: center; justify-content: center; flex: none; width: 28px; height: 28px; border-radius: 5px; color: #64748b; }
.icon-button:hover { background: #f1f5f9; color: #334155; }
.annotation-preview { position: fixed; z-index: 11000; box-sizing: border-box; border: 1px solid #e5e7eb; border-radius: 14px; background: #fff; color: #475569; font-size: 12px; box-shadow: 0 3px 10px #0f172a12; }
.annotation-preview::after { content: ''; position: absolute; bottom: -10px; left: 0; right: 0; height: 10px; }
.annotation-list { list-style: none; margin: 0; padding: 0; max-height: inherit; overflow-y: auto; overscroll-behavior: contain; border-radius: inherit; }
.annotation-item { display: flex; align-items: flex-start; gap: 8px; padding: 10px; }
.annotation-item + .annotation-item { border-top: 1px solid #f1f5f9; }
.annotation-index { color: #94a3b8; font-size: 11px; line-height: 19px; }
.annotation-body { flex: 1; min-width: 0; }
.annotation-source { color: #64748b; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 19px; }
blockquote { margin: 1px 0 0; color: #1f2937; white-space: pre-wrap; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.5; }
.annotation-comment { margin: 4px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; color: #0f172a; line-height: 1.5; }
.annotation-actions { display: flex; flex: none; }
textarea { box-sizing: border-box; width: 100%; resize: vertical; border: 1px solid #cbd5e1; border-radius: 5px; padding: 6px; font: inherit; }
.edit-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
.edit-actions button { padding: 4px 6px; color: #0284c7; }
@media (max-width: 480px) { .annotation-actions { flex-direction: column; } }
@media (hover: none) { .annotation-clear { opacity: 1; pointer-events: auto; } }
@media (prefers-reduced-motion: reduce) { .annotation-clear { transition: none; } }
</style>
