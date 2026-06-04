<script setup lang="ts">
import { UploadCloud, X } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  files: File[]
  disabled?: boolean
  invalid?: boolean
}>()

const emit = defineEmits<{
  'update:files': [files: File[]]
}>()

const { t } = useI18n()

function addFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const selected = Array.from(input.files || [])
  emit('update:files', [...props.files, ...selected])
  input.value = ''
}

function removeFile(index: number) {
  emit('update:files', props.files.filter((_, fileIndex) => fileIndex !== index))
}
</script>

<template>
  <div class="evidence-uploader">
    <label class="upload-box" :class="{ disabled, invalid }">
      <UploadCloud class="w-4 h-4" />
      <span>{{ t('chat.closeout.evidence_upload') }}</span>
      <input type="file" multiple :disabled="disabled" @change="addFiles" />
    </label>
    <div v-if="files.length" class="file-list">
      <div v-for="(file, index) in files" :key="`${file.name}-${index}`" class="file-row">
        <span>{{ file.name }}</span>
        <button type="button" :disabled="disabled" @click="removeFile(index)">
          <X class="w-3 h-3" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.evidence-uploader {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.upload-box {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 56px;
  border: 1px dashed var(--color-border, #d7dce5);
  border-radius: 8px;
  color: var(--color-primary-700, #1d4ed8);
  background: rgba(248, 250, 252, 0.86);
  cursor: pointer;
}

.upload-box.disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.upload-box.invalid {
  border-color: #ef4444;
  background: #fef2f2;
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.08);
}

.upload-box input {
  display: none;
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.file-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  border: 1px solid var(--color-border, #d7dce5);
  border-radius: 8px;
  font-size: 12px;
  color: var(--color-text, #1f2937);
}

.file-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-row button {
  border: 0;
  background: transparent;
  color: var(--color-muted, #64748b);
  cursor: pointer;
}
</style>
