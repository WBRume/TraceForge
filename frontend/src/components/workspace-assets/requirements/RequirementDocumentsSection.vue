<script setup lang="ts">
import { shallowRef, useTemplateRef, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { FileText, Upload } from '@/components/icons'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { requirementDocumentsUrl, uploadRequirementDocument, type RequirementDocumentSummary } from './requirementDocuments'

const props = defineProps<{ workspaceId: string; requirementId: string; canManage: boolean }>()
const { t } = useI18n()
const fileInput = useTemplateRef<HTMLInputElement>('fileInput')
const items = shallowRef<RequirementDocumentSummary[]>([])
const error = shallowRef('')
const saving = shallowRef(false)

async function load(signal?: AbortSignal) {
  const { workspaceId, requirementId } = props
  try {
    const { data } = await api.get<{ items: RequirementDocumentSummary[] }>(
      requirementDocumentsUrl(workspaceId, requirementId), { signal },
    )
    if (workspaceId === props.workspaceId && requirementId === props.requirementId) items.value = data.items
  } catch (cause) {
    if (!signal?.aborted && requirementId === props.requirementId) {
      error.value = formatApiError(cause, t('workspace_canvas.load_failed'), t)
    }
  }
}

watch(() => [props.workspaceId, props.requirementId], (_, _old, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  items.value = []
  error.value = ''
  void load(controller.signal)
}, { immediate: true })

async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || saving.value) return
  const { workspaceId, requirementId } = props
  saving.value = true
  error.value = ''
  try {
    await uploadRequirementDocument(workspaceId, requirementId, file)
    if (requirementId === props.requirementId) await load()
  } catch (cause) {
    error.value = formatApiError(cause, t('workspace_canvas.actions.upload_failed'), t)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section v-if="items.length || canManage || error" class="requirement-documents">
    <header>
      <h3>{{ t('workspace_canvas.kind.requirement_document') }}</h3>
      <button v-if="canManage" class="btn-secondary" type="button" :disabled="saving" @click="fileInput?.click()">
        <Upload :size="15" />{{ t('workspace_canvas.actions.upload') }}
      </button>
      <input ref="fileInput" type="file" accept=".docx,.md,.markdown,.txt" hidden @change="upload" />
    </header>
    <p v-if="error" role="alert">{{ error }}</p>
    <ul v-if="items.length">
      <li v-for="item in items" :key="item.link_id">
        <RouterLink :to="item.task_id
          ? { name: 'taskSpec', params: { wsId: workspaceId, taskId: item.task_id }, query: { asset: item.id } }
          : { name: 'workspaceRequirementDocument', params: { wsId: workspaceId, documentId: item.id } }">
          <FileText :size="16" />{{ item.name }}
        </RouterLink>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.requirement-documents { padding: 14px; border-radius: 13px; border: 1px solid #e2e8f0; background: #fff; }
header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
h3 { margin: 0; font-size: 15px; color: #1e3a8a; }
button, a { display: inline-flex; align-items: center; gap: 6px; }
ul { display: grid; gap: 6px; padding: 0; margin: 8px 0 0; list-style: none; }
a { color: #0369a1; font-size: 13px; overflow-wrap: anywhere; }
p { margin: 7px 0 0; color: #b91c1c; }
</style>
