<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CloudUpload, RefreshCw, DatabaseZap, Upload } from 'lucide-vue-next'
import type { ApiMockProject, ApiMockSourceVersion } from '@/types/apiMock'

type TaskOption = {
  id: string
  name: string
}

type JobState = {
  id: string
  job_type: string
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'
  progress: number
  message?: string | null
}

const { t } = useI18n()

const props = withDefaults(defineProps<{
  tasks: TaskOption[]
  selectedTaskId: string
  project: ApiMockProject | null
  sourceVersions: ApiMockSourceVersion[]
  selectedSourceVersionId: string
  canManage: boolean
  canPublish: boolean
  syncBusy: boolean
  importBusy: boolean
  jobState?: JobState | null
  showTaskPicker?: boolean
  showSourceVersionPicker?: boolean
}>(), {
  jobState: null,
  showTaskPicker: true,
  showSourceVersionPicker: true,
})

const emit = defineEmits<{
  (e: 'update:task-id', value: string): void
  (e: 'sync'): void
  (e: 'source-change', sourceVersionId: string): void
  (e: 'update-proxy', payload: { proxy_enabled: boolean; proxy_base_url: string }): void
  (e: 'import-swagger', payload: { source_name?: string; source_url?: string; raw_content?: string; file?: File | null }): void
}>()

const sourceName = ref('')
const sourceUrl = ref('')
const rawContent = ref('')
const uploadFile = ref<File | null>(null)
const proxyBaseUrl = ref('')

const taskOptions = computed(() => props.tasks)
const jobTitle = computed(() => {
  if (!props.jobState) return ''
  return props.jobState.job_type === 'IMPORT_SWAGGER'
    ? t('api_mock.import_activity_title')
    : t('api_mock.sync_activity_title')
})
const jobStatusLabel = computed(() => {
  if (!props.jobState) return ''
  if (props.jobState.status === 'PENDING') return t('api_mock.job_status_pending')
  if (props.jobState.status === 'RUNNING') return t('api_mock.job_status_running')
  if (props.jobState.status === 'SUCCESS') return t('api_mock.job_status_success')
  return t('api_mock.job_status_failed')
})
const jobProgressWidth = computed(() => {
  if (!props.jobState) return '0%'
  return `${Math.max(6, Math.min(100, Number(props.jobState.progress || 0)))}%`
})

const onFileChange = (event: Event) => {
  const input = event.target as HTMLInputElement | null
  uploadFile.value = input?.files?.[0] ?? null
  if (uploadFile.value && !sourceName.value) {
    sourceName.value = uploadFile.value.name
  }
}

const submitImport = () => {
  if (!props.canManage || props.importBusy) return
  emit('import-swagger', {
    source_name: sourceName.value || undefined,
    source_url: sourceUrl.value || undefined,
    raw_content: rawContent.value || undefined,
    file: uploadFile.value,
  })
}

const saveProxy = () => {
  if (!props.canPublish) return
  emit('update-proxy', {
    proxy_enabled: Boolean(props.project?.proxy_enabled),
    proxy_base_url: proxyBaseUrl.value.trim(),
  })
}

const refreshProxyBase = () => {
  proxyBaseUrl.value = props.project?.proxy_base_url || ''
}

refreshProxyBase()
watch(() => props.project?.proxy_base_url, refreshProxyBase)
</script>

<template>
  <section class="panel glass-panel">
    <header class="head">
      <h3>{{ $t('api_mock.source_title') }}</h3>
      <button
        type="button"
        class="btn-primary mini"
        :disabled="!canManage || syncBusy || !selectedTaskId"
        @click="emit('sync')"
      >
        <RefreshCw class="w-4 h-4" :class="{ spin: syncBusy }" />
        {{ syncBusy ? $t('api_mock.syncing') : $t('api_mock.sync_now') }}
      </button>
    </header>

    <div v-if="jobState" class="job-banner" :class="`state-${jobState.status.toLowerCase()}`">
      <div class="job-head">
        <div class="job-copy">
          <span class="job-kicker">{{ jobTitle }}</span>
          <strong>{{ jobState.message || jobTitle }}</strong>
        </div>
        <span class="job-pill">{{ jobState.progress }}%</span>
      </div>
      <div class="job-progress">
        <span :style="{ width: jobProgressWidth }"></span>
      </div>
      <p class="job-hint">{{ jobStatusLabel }}</p>
    </div>

    <div
      v-if="showTaskPicker || showSourceVersionPicker"
      class="row"
      :class="{ single: (showTaskPicker ? 1 : 0) + (showSourceVersionPicker ? 1 : 0) === 1 }"
    >
      <label v-if="showTaskPicker" class="field">
        <span>{{ $t('api_mock.task') }}</span>
        <select
          class="input-field"
          :value="selectedTaskId"
          @change="emit('update:task-id', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="task in taskOptions" :key="task.id" :value="task.id">{{ task.name }}</option>
        </select>
      </label>
      <label v-if="showSourceVersionPicker" class="field">
        <span>{{ $t('api_mock.source_version') }}</span>
        <select
          class="input-field"
          :value="selectedSourceVersionId"
          :disabled="!canManage"
          @change="emit('source-change', ($event.target as HTMLSelectElement).value)"
        >
          <option value="">{{ $t('api_mock.source_auto') }}</option>
          <option v-for="version in sourceVersions" :key="version.id" :value="version.id">
            {{ version.source_type }} · {{ version.source_name || version.id.slice(0, 8) }}
          </option>
        </select>
      </label>
    </div>

    <div class="proxy-box">
      <div class="proxy-head">
        <h4>{{ $t('api_mock.proxy_settings') }}</h4>
        <label class="switch">
          <input
            type="checkbox"
            :disabled="!canPublish"
            :checked="Boolean(project?.proxy_enabled)"
            @change="emit('update-proxy', { proxy_enabled: ($event.target as HTMLInputElement).checked, proxy_base_url: proxyBaseUrl })"
          />
          <span>{{ project?.proxy_enabled ? $t('api_mock.enabled') : $t('api_mock.disabled') }}</span>
        </label>
      </div>
      <div class="row">
        <label class="field stretch">
          <span>{{ $t('api_mock.proxy_base_url') }}</span>
          <input
            v-model="proxyBaseUrl"
            class="input-field"
            :placeholder="$t('api_mock.proxy_placeholder')"
            :disabled="!canPublish"
          />
        </label>
        <button type="button" class="btn-secondary mini" :disabled="!canPublish" @click="saveProxy">
          {{ $t('common.save') }}
        </button>
      </div>
      <p class="hint">{{ project?.temp_workspace_path }}</p>
    </div>

    <div class="import-box">
      <div class="import-title">
        <DatabaseZap class="w-4 h-4" />
        <span>{{ $t('api_mock.import_title') }}</span>
      </div>
      <div class="row">
        <label class="field stretch">
          <span>{{ $t('api_mock.import_name') }}</span>
          <input v-model="sourceName" class="input-field" :disabled="!canManage" />
        </label>
        <label class="field stretch">
          <span>{{ $t('api_mock.import_url') }}</span>
          <input v-model="sourceUrl" class="input-field" :disabled="!canManage" />
        </label>
      </div>
      <label class="field">
        <span>{{ $t('api_mock.import_content') }}</span>
        <textarea
          v-model="rawContent"
          class="input-field textarea"
          :disabled="!canManage"
          :placeholder="$t('api_mock.import_content_placeholder')"
        />
      </label>
      <div class="actions">
        <label class="upload-btn">
          <Upload class="w-4 h-4" />
          <span>{{ uploadFile?.name || $t('api_mock.upload_file') }}</span>
          <input type="file" accept=".json,.yaml,.yml" class="hidden" @change="onFileChange" />
        </label>
        <button type="button" class="btn-primary mini" :disabled="!canManage || importBusy" @click="submitImport">
          <CloudUpload class="w-4 h-4" :class="{ spin: importBusy }" />
          {{ importBusy ? $t('api_mock.importing') : $t('api_mock.import_now') }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  padding: 1rem;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
}

.head h3 {
  margin: 0;
  font-size: 0.98rem;
  color: #0f172a;
}

.row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.6rem;
}

.row.single {
  grid-template-columns: minmax(0, 1fr);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.field.stretch {
  grid-column: span 1;
}

.field span {
  font-size: 0.75rem;
  color: #475569;
}

.textarea {
  min-height: 88px;
  resize: vertical;
  padding-top: 0.6rem;
}

.proxy-box,
.import-box {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 0.7rem;
  background: #f8fafc;
}

.job-banner {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 0.85rem 0.9rem;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
}

.job-banner.state-running {
  border-color: #cbd5e1;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
}

.job-banner.state-success {
  border-color: #86efac;
  background: #ffffff;
}

.job-banner.state-failed {
  border-color: #fca5a5;
  background: #ffffff;
}

.job-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
}

.job-copy {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.job-kicker {
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.job-copy strong {
  color: #0f172a;
  font-size: 0.88rem;
}

.job-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 3.2rem;
  min-height: 2rem;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #f1f5f9;
  color: #475569;
  font-size: 0.76rem;
  font-weight: 700;
}

.job-progress {
  position: relative;
  width: 100%;
  height: 0.5rem;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.job-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #0ea5e9, #2563eb);
  transition: width 0.24s ease;
}

.job-banner.state-success .job-progress span {
  background: linear-gradient(90deg, #10b981, #22c55e);
}

.job-banner.state-failed .job-progress span {
  background: linear-gradient(90deg, #ef4444, #f97316);
}

.job-hint {
  margin: 0;
  color: #475569;
  font-size: 0.76rem;
  line-height: 1.6;
}

.proxy-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.55rem;
}

.proxy-head h4 {
  margin: 0;
  font-size: 0.85rem;
  color: #0c4a6e;
}

.switch {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  color: #334155;
}

.hint {
  margin: 0.45rem 0 0;
  font-size: 0.72rem;
  color: #64748b;
  word-break: break-all;
}

.import-title {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: #0c4a6e;
  font-size: 0.84rem;
  font-weight: 700;
  margin-bottom: 0.55rem;
}

.actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.55rem;
}

.upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.75rem;
  color: #475569;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  padding: 0.45rem 0.55rem;
  cursor: pointer;
  min-width: 0;
}

.upload-btn span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.hidden {
  display: none;
}

.mini {
  padding: 0.45rem 0.75rem;
  font-size: 0.78rem;
}

.spin {
  animation: spin 1s linear infinite;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .row {
    grid-template-columns: 1fr;
  }
}
</style>
