<script setup lang="ts">
import { computed } from 'vue'
import { Clock, FileText, Loader2, Upload, X } from '@/components/icons'

defineProps<{ wsId: string; isDiagnosisTask: boolean; creating: boolean }>()
const requirementDuration = defineModel<number | string>('requirementDuration', { required: true })
const priority = defineModel<string>('priority', { required: true })
const specFile = defineModel<File | null>('specFile', { required: true })
const diagnosisFiles = defineModel<File[]>('diagnosisFiles', { required: true })
const PRIORITIES = ['P0', 'P1', 'P2', 'P3'] as const
const isPdfSpecFile = computed(() => (specFile.value?.name || '').toLowerCase().endsWith('.pdf'))
function handleSpecFileUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) specFile.value = file
  input.value = ''
}
function handleDiagnosisFiles(event: Event) {
  const input = event.target as HTMLInputElement
  diagnosisFiles.value = [...diagnosisFiles.value, ...Array.from(input.files || [])]
  input.value = ''
}
function removeDiagnosisFile(index: number) {
  diagnosisFiles.value = diagnosisFiles.value.filter((_, i) => i !== index)
}
</script>
<template>
  <div class="attachment-fields">
    <!-- 行 2：双列网格（研发态：工时 + 规范文档上传；诊断态：优先级 + 文档上传） -->
    <div class="form-row form-grid-2">
      <!-- 研发态工时 -->
      <div v-if="!isDiagnosisTask" class="form-group">
        <label class="form-label">
          <Clock class="w-3.5 h-3.5 text-slate-400" />
          <span>{{ $t('dashboard.requirement_duration') }}</span>
        </label>
        <div class="input-with-suffix">
          <input
            v-model="requirementDuration"
            type="number"
            class="input-field"
            required
            min="0"
            step="0.5"
            :placeholder="$t('dashboard.requirement_placeholder')"
          />
          <span class="input-suffix">h</span>
        </div>
      </div>

      <!-- 诊断态优先级 -->
      <div v-if="isDiagnosisTask" class="form-group">
        <label class="form-label">
          <span>{{ $t('diagnosis.priority') }}</span>
        </label>
        <div class="priority-options">
          <button
            v-for="p in PRIORITIES"
            :key="p"
            type="button"
            class="priority-option"
            :class="{ active: priority === p, [`prio-${p.toLowerCase()}`]: true }"
            @click="priority = p"
          >
            {{ p }}
          </button>
        </div>
      </div>

      <!-- 规范文档上传（研发态） -->
      <div v-if="!isDiagnosisTask" class="form-group">
        <label class="form-label">
          <FileText class="w-3.5 h-3.5 text-slate-400" />
          <span>{{ $t('dashboard.spec_doc') }}</span>
        </label>
        <div class="file-upload-box glass-panel compact-upload">
          <Upload v-if="!creating" class="w-4 h-4 text-primary flex-shrink-0" />
          <Loader2 v-else class="w-4 h-4 spin text-primary flex-shrink-0" />
          <div class="file-name text-slate-600" :title="specFile?.name">
            {{ specFile?.name || $t('dashboard.spec_placeholder') }}
          </div>
          <input
            :id="`spec-upload-${wsId}`"
            type="file"
            class="hidden-input"
            accept=".pdf,.docx,.md,.txt"
            @change="handleSpecFileUpload"
          />
          <label :for="`spec-upload-${wsId}`" class="btn-primary file-choose-btn">
            {{ $t('common.select') }}
          </label>
        </div>
        <p v-if="isPdfSpecFile" class="pdf-agent-hint">
          {{ $t('dashboard.spec_pdf_agent_hint') }}
        </p>
      </div>

      <!-- 诊断态文档上传 -->
      <div v-if="isDiagnosisTask" class="form-group">
        <label class="form-label">
          <FileText class="w-3.5 h-3.5 text-slate-400" />
          <span>{{ $t('diagnosis.docs_upload_label') }}</span>
        </label>
        <div class="file-upload-box glass-panel compact-upload">
          <Upload v-if="!creating" class="w-4 h-4 text-primary flex-shrink-0" />
          <Loader2 v-else class="w-4 h-4 spin text-primary flex-shrink-0" />
          <div class="file-name text-slate-600">
            {{ $t('diagnosis.docs_upload_placeholder') }}
          </div>
          <input
            :id="`diag-docs-upload-${wsId}`"
            type="file"
            class="hidden-input"
            multiple
            @change="handleDiagnosisFiles"
          />
          <label :for="`diag-docs-upload-${wsId}`" class="btn-primary file-choose-btn">
            {{ $t('common.select') }}
          </label>
        </div>
      </div>
    </div>

    <!-- 诊断模式已选文件列表 -->
    <div v-if="isDiagnosisTask && diagnosisFiles.length > 0" class="diagnosis-files-list">
      <div v-for="(file, index) in diagnosisFiles" :key="`${file.name}-${index}`" class="diagnosis-file-row">
        <FileText class="w-3.5 h-3.5 diagnosis-file-icon" />
        <span class="diagnosis-file-name">{{ file.name }}</span>
        <button type="button" class="diagnosis-file-remove" :title="$t('common.delete')" @click="removeDiagnosisFile(index)">
          <X class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

  </div>
</template>
<style scoped src="@/styles/task-create/task-create-shared.css"></style>
<style scoped src="@/styles/task-create/task-create-form.css"></style>
<style scoped>
.attachment-fields { display: flex; flex-direction: column; gap: 12px; }
</style>
