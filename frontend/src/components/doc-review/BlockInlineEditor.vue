<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{
  initialText: string;
  disabled?: boolean;
  preserveWhitespace?: boolean;
  allowEmpty?: boolean;
  saveLabel?: string;
  cancelLabel?: string;
}>();

const emit = defineEmits<{
  save: [text: string];
  cancel: [];
}>();

const editorRef = ref<HTMLDivElement | null>(null);
let saved = false;
let cancelledByEsc = false;

const normalizeText = (raw: string) =>
  props.preserveWhitespace ? raw.replace(/\r\n?/g, "\n") : raw.replace(/\r?\n+/g, " ").trim();

const focusAtEnd = async () => {
  await nextTick();
  const el = editorRef.value;
  if (!el) return;
  el.focus();
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
};

const submitSave = () => {
  if (saved || cancelledByEsc || props.disabled) return;
  const el = editorRef.value;
  if (!el) return;
  // Chromium leaves a single placeholder break after the editor is cleared.
  const emptyPlaceholder = el.childNodes.length === 1 && el.firstChild?.nodeName === "BR";
  const normalized = normalizeText(emptyPlaceholder ? "" : el.innerText);
  if (!props.allowEmpty && !normalized.trim()) {
    void focusAtEnd();
    return;
  }
  saved = true;
  emit("save", normalized);
};

const handleEsc = () => {
  if (cancelledByEsc) return;
  cancelledByEsc = true;
  emit("cancel");
};

const handleBlur = () => {
  if (cancelledByEsc || saved || props.saveLabel) return;
  submitSave();
};

const handlePaste = (event: ClipboardEvent) => {
  event.preventDefault();
  const plain = event.clipboardData?.getData("text/plain") || "";
  document.execCommand("insertText", false, props.preserveWhitespace ? plain : plain.replace(/\r?\n+/g, " "));
};

watch(() => props.disabled, (disabled) => {
  if (!disabled) saved = false;
});

onMounted(() => {
  void focusAtEnd();
});

onBeforeUnmount(() => {
  saved = true;
});
</script>

<template>
  <div
    ref="editorRef"
    class="doc-block-editor"
    :class="{ 'is-disabled': disabled }"
    :contenteditable="!disabled"
    spellcheck="false"
    @keydown.enter.prevent="submitSave"
    @keydown.esc.prevent="handleEsc"
    @blur="handleBlur"
    @input="saved = false"
    @paste="handlePaste"
  >{{ initialText }}</div>
  <div v-if="saveLabel" class="doc-block-actions">
    <button type="button" class="btn-secondary" :disabled="disabled" @click="handleEsc">{{ cancelLabel }}</button>
    <button type="button" class="btn-primary" :disabled="disabled" @click="submitSave">{{ saveLabel }}</button>
  </div>
</template>

<style scoped>
.doc-block-editor {
  outline: none;
  min-height: 1em;
  cursor: text;
  border-radius: 4px;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.45);
  background: rgba(14, 165, 233, 0.05);
  white-space: pre-wrap;
}

.doc-block-editor.is-disabled {
  pointer-events: none;
  opacity: 0.6;
}
.doc-block-actions { display: flex; justify-content: flex-end; gap: .5rem; margin-top: .75rem; }
</style>
