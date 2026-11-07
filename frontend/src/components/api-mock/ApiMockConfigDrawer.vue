<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CloudUpload, FolderCog, RefreshCw, Upload, X } from '@/components/icons'
import { Editor as MonacoEditor } from '@guolao/vue-monaco-editor'
import type { ApiMockProject, ApiMockSourceVersion } from '@/types/apiMock'

const props = defineProps<{
  open: boolean
  drawerMode: 'sync' | 'versions' | 'proxy' | 'import'
  taskName: string
  project: ApiMockProject | null
  sourceVersions: ApiMockSourceVersion[]
  canManage: boolean
  canPublish: boolean
  syncBusy: boolean
  importBusy: boolean
  swaggerMutationLocked: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'sync'): void
  (e: 'activate-source', sourceVersionId: string): void
  (e: 'update-proxy', payload: { proxy_enabled: boolean; proxy_base_url: string }): void
  (e: 'import-swagger', payload: { source_name?: string; raw_content?: string; file?: File | null }): void
}>()

const sourceName = ref('')
const rawContent = ref('')
const uploadFile = ref<File | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const proxyBaseUrl = ref('')
const proxyEnabled = ref(false)

watch(
  () => props.project,
  (project) => {
    proxyBaseUrl.value = project?.proxy_base_url || ''
    proxyEnabled.value = Boolean(project?.proxy_enabled)
  },
  { immediate: true },
)

const showSwaggerLockHint = computed(() => props.swaggerMutationLocked)

const onFileChange = (event: Event) => {
  const input = event.target as HTMLInputElement | null
  const file = input?.files?.[0] ?? null
  
  console.log('File input changed:', {
    input: input,
    files: input?.files,
    file: file,
    fileSize: file?.size,
    fileName: file?.name
  })
  
  uploadFile.value = file
  if (file && !sourceName.value) {
    sourceName.value = file.name
  }
  fileInputRef.value = input
}

const submitImport = () => {
  if (!props.canManage || props.importBusy) return
  
  let file = uploadFile.value
  
  if (!file && fileInputRef.value?.files?.[0]) {
    file = fileInputRef.value.files[0]
  }
  
  if (!file && sourceName.value) {
    console.error('No file selected!')
    return
  }
  
  emit('import-swagger', {
    source_name: sourceName.value || undefined,
    raw_content: rawContent.value || undefined,
    file: file,
  })
}

const saveProxy = () => {
  emit('update-proxy', {
    proxy_enabled: proxyEnabled.value,
    proxy_base_url: proxyBaseUrl.value.trim(),
  })
}
</script>

<template>
  <transition name="drawer-fade">
    <div v-if="open" class="drawer-shell" @click.self="emit('close')">
      <aside class="drawer-panel glass-panel" @click.stop>
        <header class="drawer-head">
          <div>
            <span class="drawer-kicker">{{ $t('api_mock.config_button') }}</span>
            <h2>{{ drawerMode === 'sync' ? $t('api_mock.source_title') : drawerMode === 'versions' ? $t('api_mock.version_management') : drawerMode === 'proxy' ? $t('api_mock.proxy_title') : $t('api_mock.import_manage_title') }}</h2>
            <p>{{ taskName || $t('api_mock.task_empty') }}</p>
          </div>
          <button type="button" class="icon-btn" @click="emit('close')">
            <X class="w-4 h-4" />
          </button>
        </header>

        <div class="drawer-body custom-scrollbar">
          <section class="config-card" v-if="drawerMode === 'sync'">
            <div class="card-head inline">
              <div>
                <span>{{ $t('api_mock.source_sync_title') }}</span>
                <h3>{{ $t('api_mock.source_title') }}</h3>
              </div>
              <button
                type="button"
                class="btn-primary mini"
                :disabled="!canManage || syncBusy || swaggerMutationLocked"
                @click="emit('sync')"
              >
                <RefreshCw class="w-4 h-4" :class="{ spin: syncBusy }" />
                {{ syncBusy ? $t('api_mock.syncing') : $t('api_mock.sync_now') }}
              </button>
            </div>
            <p class="card-copy">{{ $t('api_mock.config_sync_hint') }}</p>
            <p v-if="showSwaggerLockHint" class="lock-copy">{{ $t('api_mock.ai_auto_mock_locked_project_swagger_mutation') }}</p>
          </section>

          <section v-if="drawerMode === 'versions'" class="config-card">
            <div class="card-head">
              <span>{{ $t('api_mock.source_version') }}</span>
              <h3>{{ $t('api_mock.version_management') }}</h3>
            </div>
            <div v-if="sourceVersions.length === 0" class="empty-line">{{ $t('api_mock.source_empty_hint') }}</div>
            <div v-else class="version-list">
              <button
                v-for="version in sourceVersions"
                :key="version.id"
                type="button"
                class="version-item"
                :class="{ active: version.is_active }"
                :disabled="swaggerMutationLocked"
                @click="emit('activate-source', version.id)"
              >
                <div>
                  <strong>{{ version.source_name || version.id.slice(0, 8) }}</strong>
                  <p>{{ version.source_type }} · {{ new Date(version.created_at).toLocaleString() }}</p>
                </div>
                <span class="version-pill">{{ version.is_active ? $t('api_mock.active_version') : $t('api_mock.switch_version') }}</span>
              </button>
            </div>
            <p v-if="showSwaggerLockHint" class="lock-copy">{{ $t('api_mock.ai_auto_mock_locked_project_swagger_mutation') }}</p>
          </section>

          <section v-if="drawerMode === 'proxy'" class="config-card">
            <div class="card-head">
              <span>{{ $t('api_mock.proxy_settings') }}</span>
              <h3>{{ $t('api_mock.proxy_title') }}</h3>
            </div>
            <p class="card-copy proxy-hint">{{ $t('api_mock.proxy_optional_hint') }}</p>
            <label class="switch-row">
              <input v-model="proxyEnabled" type="checkbox" :disabled="!canPublish">
              <span>{{ proxyEnabled ? $t('api_mock.enabled') : $t('api_mock.disabled') }}</span>
            </label>
            <label class="field">
              <span>{{ $t('api_mock.proxy_base_url') }}</span>
              <input v-model="proxyBaseUrl" class="input-field" :disabled="!canPublish" :placeholder="$t('api_mock.proxy_placeholder')">
            </label>
            <button type="button" class="btn-secondary mini" :disabled="!canPublish" @click="saveProxy">
              <FolderCog class="w-4 h-4" />
              {{ $t('common.save') }}
            </button>
          </section>

          <section v-if="drawerMode === 'import'" class="config-card">
            <div class="card-head">
              <span>{{ $t('api_mock.import_title') }}</span>
              <h3>{{ $t('api_mock.import_manage_title') }}</h3>
            </div>
            <label class="field">
              <span>{{ $t('api_mock.import_name') }}</span>
              <input v-model="sourceName" class="input-field" :disabled="!canManage || swaggerMutationLocked">
            </label>
            <label class="field">
              <span>{{ $t('api_mock.import_content') }}</span>
              <div class="monaco-editor-container" :style="{ height: '300px' }" :disabled="!canManage || swaggerMutationLocked">
                <MonacoEditor
                  v-model="rawContent"
                  :options="{
                    language: 'yaml',
                    theme: 'vs',
                    minimap: { enabled: true },
                    scrollBeyondLastLine: false,
                    automaticLayout: true
                  }"
                  :disabled="!canManage || swaggerMutationLocked"
                />
              </div>
            </label>
            <div class="import-actions">
              <label class="upload-btn">
                <Upload class="w-4 h-4" />
                <span>{{ uploadFile?.name || $t('api_mock.upload_file') }}</span>
                <input ref="fileInputRef" type="file" accept=".json,.yaml,.yml" class="hidden" :disabled="!canManage || swaggerMutationLocked" @change="onFileChange">
              </label>
              <button
                type="button"
                class="btn-primary mini"
                :disabled="!canManage || importBusy || swaggerMutationLocked"
                @click="submitImport"
              >
                <CloudUpload class="w-4 h-4" :class="{ spin: importBusy }" />
                {{ importBusy ? $t('api_mock.importing') : $t('api_mock.import_now') }}
              </button>
            </div>
            <p v-if="showSwaggerLockHint" class="lock-copy">{{ $t('api_mock.ai_auto_mock_locked_project_swagger_mutation') }}</p>
          </section>
        </div>
      </aside>
    </div>
  </transition>
</template>

<style scoped>
.drawer-shell {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  justify-content: flex-end;
  background: rgba(15, 23, 42, 0.18);
  backdrop-filter: blur(6px);
}

.drawer-panel {
  width: min(34rem, calc(100vw - 1.25rem));
  height: 100%;
  border-radius: 24px 0 0 24px;
  border-right: none;
  background: #ffffff;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.05);
  display: flex;
  flex-direction: column;
}

.drawer-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.2rem 1.2rem 1rem;
  border-bottom: 1px solid #e2e8f0;
}

.drawer-kicker,
.card-head span {
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.drawer-head h2,
.card-head h3 {
  margin: 0.35rem 0 0;
}

.drawer-head p,
.card-copy {
  margin: 0.32rem 0 0;
  color: #64748b;
  line-height: 1.65;
}

.lock-copy {
  margin: 0.45rem 0 0;
  color: #9a3412;
  background: rgba(255, 247, 237, 0.88);
  border: 1px solid rgba(251, 146, 60, 0.35);
  border-radius: 10px;
  padding: 0.45rem 0.6rem;
  font-size: 0.78rem;
  font-weight: 600;
}

.icon-btn {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.88);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.drawer-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 1rem 1.2rem 1.2rem;
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.config-card {
  padding: 1rem;
  border-radius: 22px;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.03);
}

.card-head {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  margin-bottom: 0.75rem;
}

.card-head.inline {
  flex-direction: row;
  justify-content: space-between;
  align-items: flex-start;
}

.version-list {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.version-item {
  width: 100%;
  padding: 0.85rem 0.9rem;
  border-radius: 18px;
  border: 1px solid #e2e8f0;
  background: rgba(248, 250, 252, 0.92);
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  text-align: left;
}

.version-item.active {
  border-color: rgba(14, 165, 233, 0.92);
  background: #f8fafc;
}

.version-item strong {
  display: block;
  color: #0f172a;
}

.version-item p {
  margin: 0.26rem 0 0;
  color: #64748b;
  font-size: 0.78rem;
}

.version-pill {
  white-space: nowrap;
  align-self: center;
  padding: 0.28rem 0.6rem;
  border-radius: 999px;
  background: #f1f5f9;
  color: #0369a1;
  font-size: 0.75rem;
  font-weight: 700;
}

.switch-row {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.8rem;
  color: #0f172a;
  font-weight: 600;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.field span {
  color: #475569;
  font-size: 0.8rem;
  font-weight: 600;
}

.dual-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.import-area {
  min-height: 10rem;
  resize: vertical;
  padding-top: 0.7rem;
}

.import-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-top: 0.85rem;
}

.upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: rgba(240, 249, 255, 0.92);
  padding: 0.78rem 0.9rem;
  color: #0369a1;
  font-weight: 700;
}

.empty-line {
  color: #64748b;
}

.hidden {
  display: none;
}

.mini {
  min-height: 2.9rem;
}

.drawer-fade-enter-active,
.drawer-fade-leave-active {
  transition: opacity 0.22s ease;
}

.drawer-fade-enter-active .drawer-panel,
.drawer-fade-leave-active .drawer-panel {
  transition: transform 0.24s ease;
}

.drawer-fade-enter-from,
.drawer-fade-leave-to {
  opacity: 0;
}

.drawer-fade-enter-from .drawer-panel,
.drawer-fade-leave-to .drawer-panel {
  transform: translateX(1.5rem);
}

@media (max-width: 900px) {
  .dual-grid {
    grid-template-columns: 1fr;
  }

  .import-actions {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
