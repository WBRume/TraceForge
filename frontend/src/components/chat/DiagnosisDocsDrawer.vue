<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FileText,
  FolderGit2,
  GitFork,
  Loader2,
  Upload,
  X,
} from 'lucide-vue-next'
import { useDiagnosisDocs } from '@/composables/useDiagnosisDocs'

const props = defineProps<{
  open: boolean
  wsId: string
  taskId: string
}>()

const emit = defineEmits<{
  close: []
}>()

const { t } = useI18n()

const activeTab = shallowRef<'docs' | 'code'>('docs')

const docsModel = useDiagnosisDocs({
  wsId: () => props.wsId,
  taskId: () => props.taskId,
})

const {
  docs,
  docsLoading,
  activeDoc,
  activeDocLoading,
  uploading,
  codePath,
  repos,
  reposLoading,
  loadDocs,
  selectDoc,
  uploadDoc,
  loadCodePath,
} = docsModel

watch(
  () => props.open,
  async (visible) => {
    if (visible) {
      void loadDocs()
      void loadCodePath()
    }
  },
  { immediate: true },
)

watch(
  () => props.taskId,
  () => {
    activeTab.value = 'docs'
  },
)

const hasDocs = computed(() => docs.value.length > 0)

const handleFileSelect = (event: Event) => {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length === 0) return
  for (const file of files) {
    void uploadDoc(file)
  }
  input.value = ''
}

const formatDocMeta = (doc: { source_ext?: string | null; created_at?: string | null }) => {
  const parts: string[] = []
  if (doc.source_ext) parts.push(doc.source_ext)
  if (doc.created_at) parts.push(new Date(doc.created_at).toLocaleString())
  return parts.join(' · ')
}

const fileNameLabel = (name: string) => name.split('/').pop() || name
</script>

<template>
  <aside v-if="open" class="diag-drawer glass-panel" :class="{ 'is-open': open }">
    <div class="diag-drawer-head">
      <FolderGit2 class="diag-drawer-icon" />
      <span class="diag-drawer-title">{{ t('diagnosis.docs_drawer_title') }}</span>
      <button class="diag-drawer-close" type="button" :title="t('common.close')" @click="emit('close')">
        <X class="w-4 h-4" />
      </button>
    </div>

    <div class="diag-tabbar">
      <button
        type="button"
        class="diag-tab"
        :class="{ active: activeTab === 'docs' }"
        @click="activeTab = 'docs'"
      >
        <FileText class="w-3.5 h-3.5" />
        <span>{{ t('diagnosis.docs_tab') }}</span>
      </button>
      <button
        type="button"
        class="diag-tab"
        :class="{ active: activeTab === 'code' }"
        @click="activeTab = 'code'"
      >
        <GitFork class="w-3.5 h-3.5" />
        <span>{{ t('diagnosis.code_path_tab') }}</span>
      </button>
    </div>

    <div class="diag-drawer-body">
      <!-- 诊断文档 -->
      <template v-if="activeTab === 'docs'">
        <div class="diag-upload-row">
          <input
            id="diag-drawer-file"
            type="file"
            class="diag-hidden-input"
            multiple
            accept=".md,.markdown,.txt,.log,.json,.csv,.pdf,.doc,.docx"
            @change="handleFileSelect"
          />
          <label for="diag-drawer-file" class="diag-upload-btn" :class="{ disabled: uploading }">
            <Loader2 v-if="uploading" class="w-3.5 h-3.5 diag-spin" />
            <Upload v-else class="w-3.5 h-3.5" />
            <span>{{ t('diagnosis.upload_docs') }}</span>
          </label>
        </div>

        <div v-if="docsLoading" class="diag-state">
          <Loader2 class="w-4 h-4 diag-spin" />
          <span>{{ t('common.loading') }}</span>
        </div>
        <div v-else-if="!hasDocs" class="diag-state">{{ t('diagnosis.docs_empty') }}</div>
        <div v-else class="diag-doc-list">
          <button
            v-for="doc in docs"
            :key="doc.id"
            type="button"
            class="diag-doc-item"
            :class="{ active: activeDoc?.id === doc.id }"
            @click="selectDoc(doc)"
          >
            <FileText class="diag-doc-icon" />
            <div class="diag-doc-body">
              <div class="diag-doc-name">{{ fileNameLabel(doc.name) }}</div>
              <div class="diag-doc-meta">{{ formatDocMeta(doc) }}</div>
            </div>
          </button>
        </div>

        <div v-if="activeDocLoading" class="diag-preview-state">
          <Loader2 class="w-4 h-4 diag-spin" />
          <span>{{ t('common.loading') }}</span>
        </div>
        <div v-else-if="activeDoc" class="diag-doc-preview">
          <div class="diag-preview-title">
            <FileText class="w-3.5 h-3.5" />
            <span>{{ fileNameLabel(activeDoc.name) }}</span>
          </div>
          <pre v-if="activeDoc.content_text" class="diag-preview-content">{{ activeDoc.content_text }}</pre>
          <div v-else class="diag-state">{{ t('diagnosis.docs_preview_empty') }}</div>
        </div>
      </template>

      <!-- 代码路径 -->
      <template v-else>
        <div class="diag-section-label">{{ t('diagnosis.code_path_label') }}</div>
        <pre v-if="codePath" class="diag-code-path">{{ codePath }}</pre>
        <div v-else-if="reposLoading" class="diag-state">
          <Loader2 class="w-4 h-4 diag-spin" />
          <span>{{ t('common.loading') }}</span>
        </div>
        <div v-else class="diag-state">{{ t('diagnosis.code_path_empty') }}</div>

        <div class="diag-section-label diag-section-label-gap">{{ t('diagnosis.repo_list_label') }}</div>
        <div v-if="reposLoading" class="diag-state">
          <Loader2 class="w-4 h-4 diag-spin" />
          <span>{{ t('common.loading') }}</span>
        </div>
        <div v-else-if="repos.length === 0" class="diag-state">{{ t('diagnosis.repo_list_empty') }}</div>
        <div v-else class="diag-repo-list">
          <div v-for="repo in repos" :key="repo.id || repo.repo_name" class="diag-repo-item">
            <GitFork class="diag-repo-icon" />
            <div class="diag-repo-body">
              <div class="diag-repo-name">
                {{ repo.repo_name }}
                <span v-if="repo.state" class="diag-repo-state">{{ repo.state }}</span>
              </div>
              <div class="diag-repo-meta">
                {{ [repo.branch_name, repo.repo_url].filter(Boolean).join(' · ') }}
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.diag-drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(380px, 34vw);
  display: flex;
  flex-direction: column;
  border-left: 1px solid rgba(14, 165, 233, 0.18);
  border-radius: 0;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(6px);
  z-index: 30;
  box-shadow: -8px 0 24px rgba(15, 23, 42, 0.08);
}

.diag-drawer-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid #eef2f7;
}

.diag-drawer-icon {
  width: 17px;
  height: 17px;
  color: var(--color-primary-600, #0284c7);
  flex-shrink: 0;
}

.diag-drawer-title {
  flex: 1;
  font-weight: 700;
  font-size: 0.9rem;
  color: #0f172a;
}

.diag-drawer-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
}

.diag-drawer-close:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.diag-tabbar {
  display: flex;
  gap: 4px;
  padding: 8px 10px 0;
  border-bottom: 1px solid #eef2f7;
}

.diag-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: #64748b;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}

.diag-tab.active {
  color: var(--color-primary-600, #0284c7);
  border-bottom-color: var(--color-primary-500, #0ea5e9);
}

.diag-drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.diag-upload-row {
  display: flex;
}

.diag-hidden-input {
  display: none;
}

.diag-upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  color: #475569;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
}

.diag-upload-btn:hover:not(.disabled) {
  border-color: var(--color-primary-500, #0ea5e9);
  color: var(--color-primary-600, #0284c7);
  background: #f0f9ff;
}

.diag-upload-btn.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.diag-state {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 4px;
  color: #94a3b8;
  font-size: 0.8rem;
}

.diag-doc-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.diag-doc-item {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 7px 8px;
  border: 1px solid #e8eef5;
  border-radius: 8px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  width: 100%;
}

.diag-doc-item:hover {
  border-color: #bfdbfe;
  background: #f0f9ff;
}

.diag-doc-item.active {
  border-color: var(--color-primary-500, #0ea5e9);
  background: #eff6ff;
}

.diag-doc-icon {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  color: #64748b;
  margin-top: 1px;
}

.diag-doc-body {
  min-width: 0;
  flex: 1;
}

.diag-doc-name {
  font-size: 0.8rem;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diag-doc-meta {
  margin-top: 2px;
  font-size: 0.68rem;
  color: #94a3b8;
}

.diag-preview-state {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 4px;
  color: #94a3b8;
  font-size: 0.8rem;
}

.diag-doc-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: 1px solid #e8eef5;
  border-radius: 10px;
  background: #fcfdff;
  overflow: hidden;
}

.diag-preview-title {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 8px 10px;
  border-bottom: 1px solid #eef2f7;
  font-size: 0.76rem;
  font-weight: 700;
  color: #334155;
}

.diag-preview-content {
  margin: 0;
  padding: 10px 12px;
  max-height: 46vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 0.78rem;
  line-height: 1.6;
  color: #334155;
}

.diag-section-label {
  font-size: 0.74rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.diag-section-label-gap {
  margin-top: 6px;
}

.diag-code-path {
  margin: 0;
  padding: 8px 10px;
  border: 1px solid #e8eef5;
  border-radius: 8px;
  background: #f8fafc;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.75rem;
  line-height: 1.5;
  color: #334155;
  overflow: auto;
  word-break: break-all;
}

.diag-repo-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.diag-repo-item {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 7px 8px;
  border: 1px solid #e8eef5;
  border-radius: 8px;
  background: #ffffff;
}

.diag-repo-icon {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  color: #64748b;
  margin-top: 1px;
}

.diag-repo-body {
  min-width: 0;
  flex: 1;
}

.diag-repo-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  color: #1e293b;
}

.diag-repo-state {
  padding: 0 6px;
  border-radius: 999px;
  font-size: 0.62rem;
  font-weight: 700;
  color: #475569;
  background: #f1f5f9;
}

.diag-repo-meta {
  margin-top: 2px;
  font-size: 0.68rem;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diag-spin {
  animation: diag-spin 1s linear infinite;
}

@keyframes diag-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
