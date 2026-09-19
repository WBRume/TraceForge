<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";

const props = defineProps<{
  initialText: string;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  save: [text: string];
  cancel: [];
}>();

const editorRef = ref<HTMLDivElement | null>(null);
let saved = false;
let cancelledByEsc = false;

const normalizeText = (raw: string) =>
  String(raw || "").replace(/\r?\n+/g, " ").trim();

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
  const normalized = normalizeText(el.innerText);
  if (!normalized) {
    void focusAtEnd();
    return;
  }
  saved = true;
  emit("save", normalized);
};

const handleEsc = () => {
  if (saved || cancelledByEsc) return;
  cancelledByEsc = true;
  emit("cancel");
};

const handleBlur = () => {
  if (cancelledByEsc || saved) return;
  submitSave();
};

const handlePaste = (event: ClipboardEvent) => {
  event.preventDefault();
  const plain = String(event.clipboardData?.getData("text/plain") || "")
    .replace(/\r?\n+/g, " ");
  document.execCommand("insertText", false, plain);
};

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
    contenteditable="true"
    spellcheck="false"
    @keydown.enter.prevent="submitSave"
    @keydown.esc.prevent="handleEsc"
    @blur="handleBlur"
    @paste="handlePaste"
  >{{ initialText }}</div>
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
</style>
