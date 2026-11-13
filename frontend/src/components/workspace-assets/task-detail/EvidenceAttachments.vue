<script setup lang="ts">
import { computed, onScopeDispose, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Download, Eye, FileText } from '@/components/icons'
import ArtifactPreview from '@/components/file-preview/ArtifactPreview.vue'
import { fileType, formatFileSize } from '@/components/file-preview/fileTypes'
import type { EvidenceAttachment } from '@/types/workspaceAssets'
import api from '@/utils/api'

const props = defineProps<{
  workspaceId: string
  taskId: string
  evidenceId: string
  attachments: EvidenceAttachment[]
}>()

const { t } = useI18n()
const key = 'workspace_assets.task_detail.workbench.evidence_detail'
const selected = shallowRef<EvidenceAttachment>()
const pending = shallowRef('')
const error = shallowRef('')
let request: AbortController | undefined

const files = computed(() => props.attachments.map(attachment => {
  const type = fileType(attachment.filename)
  return { ...attachment, type: type.label, previewable: type.engine !== 'code' && type.engine !== 'patch' }
}))
const preview = shallowRef<ArrayBuffer>()
const previewSource = computed(() => {
  const bytes = preview.value
  return bytes ? async () => bytes : undefined
})

function resetPreview() {
  request?.abort()
  request = undefined
  selected.value = undefined
  preview.value = undefined
  pending.value = ''
  error.value = ''
}
onScopeDispose(resetPreview)

async function openAttachment(attachment: EvidenceAttachment, action: 'preview' | 'download') {
  resetPreview()
  if (action === 'preview') selected.value = attachment
  const controller = new AbortController()
  request = controller
  pending.value = attachment.id
  const { workspaceId, taskId, evidenceId } = props
  const path = `/workspaces/${encodeURIComponent(workspaceId)}/workspace-assets/tasks/${encodeURIComponent(taskId)}/evidence/${encodeURIComponent(evidenceId)}/attachments/${encodeURIComponent(attachment.id)}`
  try {
    const response = await api.get<ArrayBuffer>(path, { responseType: 'arraybuffer', signal: controller.signal })
    if (controller.signal.aborted) return
    if (action === 'preview') {
      preview.value = response.data
      return
    }
    const url = URL.createObjectURL(new Blob([response.data], { type: 'application/octet-stream' }))
    const link = document.createElement('a')
    link.href = url
    link.download = attachment.filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (reason) {
    if (controller.signal.aborted) return
    const status = (reason as { response?: { status?: number } } | null)?.response?.status
    error.value = t(`${key}.${status === 403 ? 'attachment_forbidden' : status === 404 ? 'attachment_missing' : 'attachment_failed'}`)
  } finally {
    if (request === controller) pending.value = ''
  }
}
</script>

<template>
  <section class="attachments" :aria-label="t(`${key}.attachments`)">
    <h4>{{ t(`${key}.attachments`) }}</h4>
    <ul class="attachment-list">
      <li v-for="file in files" :key="file.id" class="attachment">
        <FileText :size="18" class="file-icon" aria-hidden="true" />
        <div class="file-info">
          <strong>{{ file.filename }}</strong>
          <small>{{ file.type }} · {{ formatFileSize(file.size) }}</small>
        </div>
        <div class="actions">
          <el-button v-if="file.previewable" size="small" :disabled="Boolean(pending)" @click="openAttachment(file, 'preview')">
            <Eye :size="14" />{{ t(`${key}.attachment_preview`) }}
          </el-button>
          <el-button size="small" :disabled="Boolean(pending)" @click="openAttachment(file, 'download')">
            <Download :size="14" />{{ t(`${key}.attachment_download`) }}
          </el-button>
        </div>
      </li>
    </ul>
    <p v-if="error" class="attachment-error" role="alert">{{ error }}</p>
    <p v-else-if="pending" class="attachment-status" role="status">{{ t('common.loading') }}</p>
    <div v-if="selected && previewSource" class="attachment-preview">
      <div class="preview-toolbar">
        <strong>{{ selected.filename }}</strong>
        <el-button size="small" @click="resetPreview">{{ t(`${key}.attachment_close_preview`) }}</el-button>
      </div>
      <div class="preview-body">
        <ArtifactPreview :name="selected.filename" :source="previewSource" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.attachments, .attachment-list, .file-info { display: flex; flex-direction: column; gap: 0.5rem; min-width: 0; }
.attachments h4 { margin: 0; color: #475569; font-size: 0.8125rem; }
.attachment-list { padding: 0; margin: 0; list-style: none; }
.attachment, .preview-toolbar { display: flex; align-items: center; gap: 0.625rem; padding: 0.625rem 0.75rem; }
.attachment { border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; flex-wrap: wrap; }
.file-info { flex: 1; gap: 0.125rem; overflow-wrap: anywhere; }
.file-info strong, .preview-toolbar strong { font-weight: 600; color: #334155; overflow-wrap: anywhere; }
.file-info small, .file-icon, .attachment-status { color: #64748b; }
.file-icon { flex: none; }
.actions { display: flex; flex: none; gap: 0.375rem; }
.actions :deep(button) { margin: 0; }
.actions :deep(button > span) { gap: 0.25rem; }
.attachment-error, .attachment-status { margin: 0; font-size: 0.8125rem; }
.attachment-error { color: #be123c; }
.attachment-preview { overflow: hidden; border: 1px solid #e2e8f0; border-radius: 8px; }
.preview-toolbar { justify-content: space-between; border-bottom: 1px solid #e2e8f0; }
.preview-body { display: flex; height: min(480px, 58vh); min-height: 0; }
</style>
