<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type { SourceItem } from './model'

const props = defineProps<{ workspaceId: string; tasks: readonly SourceItem[] }>()
const emit = defineEmits<{ close: []; created: [taskId: string, assetId: string] }>()
const { t } = useI18n()
const taskId = shallowRef('')
const file = shallowRef<File | null>(null)
const saving = shallowRef(false)
const error = shallowRef('')
const options = computed(() => props.tasks.map(task => ({ id: task.reference.id, label: task.details.title })))

function chooseFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  error.value = ''
}

async function save() {
  if (!taskId.value || !file.value || saving.value) return
  saving.value = true
  error.value = ''
  const data = new FormData()
  data.append('file', file.value)
  try {
    const response = await api.post<{ asset_id: string }>(
      `/workspaces/${props.workspaceId}/tasks/${taskId.value}/upload-spec`, data,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
    ElMessage.success(t('workspace_canvas.actions.document_uploaded'))
    emit('created', taskId.value, response.data.asset_id)
  } catch (cause) {
    error.value = formatApiError(cause, t('workspace_canvas.actions.upload_failed'), t)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog :model-value="true" :title="t('workspace_canvas.actions.create_document')" width="min(510px, 95vw)"
    :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" @close="emit('close')">
    <form class="document-form" @submit.prevent="save">
      <label>
        <span>{{ t('workspace_canvas.kind.task') }}</span>
        <el-select v-model="taskId" filterable :disabled="saving" :aria-label="t('workspace_canvas.kind.task')"
          :placeholder="t('workspace_canvas.actions.choose_task')">
          <el-option v-for="task in options" :key="task.id" :label="task.label" :value="task.id" />
        </el-select>
      </label>
      <label>
        <span>{{ t('workspace_canvas.actions.file') }}</span>
        <input type="file" accept=".docx,.md,.txt" :disabled="saving" @change="chooseFile" />
      </label>
      <p v-if="error" class="upload-error" role="alert">{{ error }}</p>
      <footer>
        <el-button :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" native-type="submit" :disabled="!taskId || !file" :loading="saving">
          {{ t('workspace_canvas.actions.upload') }}
        </el-button>
      </footer>
    </form>
  </el-dialog>
</template>

<style scoped>
.document-form { display: grid; gap: 16px; }
.document-form label { display: grid; gap: 6px; font-weight: 600; }
.document-form input { padding: 8px; border-radius: 8px; border: 1px solid #dbeafe; font: inherit; font-weight: 400; }
.upload-error { margin: 0; color: #b91c1c; }
footer { display: flex; justify-content: flex-end; }
</style>
