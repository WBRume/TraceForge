<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { uploadRequirementDocument } from '@/components/workspace-assets/requirements/requirementDocuments'
import type { CanvasDocumentOwner } from './model'

const props = defineProps<{
  workspaceId: string
  owners: readonly CanvasDocumentOwner[]
  initialOwner?: CanvasDocumentOwner
}>()
const emit = defineEmits<{ close: []; created: [owner: CanvasDocumentOwner, documentId: string] }>()
const { t } = useI18n()
const ownerKey = (owner: CanvasDocumentOwner) => `${owner.kind}:${owner.id}`
const target = shallowRef(props.initialOwner ? ownerKey(props.initialOwner) : '')
const file = shallowRef<File | null>(null)
const saving = shallowRef(false)
const error = shallowRef('')
const owner = computed(() => props.owners.find(item => ownerKey(item) === target.value))

function chooseFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  error.value = ''
}

async function save() {
  const selected = owner.value
  if (!selected || !file.value || saving.value) return
  saving.value = true
  error.value = ''
  try {
    let documentId: string
    if (selected.kind === 'requirement') {
      const result = await uploadRequirementDocument(props.workspaceId, selected.id, file.value)
      documentId = result.id
    } else {
      const data = new FormData()
      data.append('file', file.value)
      const uploadPath = selected.taskType === 'DIAGNOSIS' ? 'upload-diagnosis-doc' : 'upload-spec'
      const response = await api.post<{ asset_id: string }>(
        `/workspaces/${props.workspaceId}/tasks/${selected.id}/${uploadPath}`, data,
      )
      documentId = response.data.asset_id
    }
    ElMessage.success(t('workspace_canvas.actions.document_uploaded'))
    emit('created', selected, documentId)
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
        <span>{{ t('workspace_canvas.actions.document_owner') }}</span>
        <el-select v-model="target" filterable :disabled="saving" :aria-label="t('workspace_canvas.actions.document_owner')"
          :placeholder="t('workspace_canvas.actions.choose_document_owner')">
          <el-option v-for="item in owners" :key="ownerKey(item)" :value="ownerKey(item)"
            :label="`${t(`workspace_canvas.kind.${item.kind}`)} · ${item.title}`" />
        </el-select>
      </label>
      <label>
        <span>{{ t('workspace_canvas.actions.file') }}</span>
        <input type="file" accept=".docx,.md,.markdown,.txt" :disabled="saving" @change="chooseFile" />
      </label>
      <p v-if="error" class="upload-error" role="alert">{{ error }}</p>
      <footer>
        <el-button :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" native-type="submit" :disabled="!owner || !file" :loading="saving">
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
