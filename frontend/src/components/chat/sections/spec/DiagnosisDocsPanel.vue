<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { FileText, Loader2, Upload } from 'lucide-vue-next'
import type { DiagnosisDocItem, DiagnosisDocsModelView } from '@/composables/useDiagnosisDocs'

/**
 * 问题定位任务：诊断文档面板（上传 / 文档列表 / 文本预览）。
 * 数据由 SpecSidebar 持有的 DiagnosisDocsModel 注入，本组件只做展示与交互。
 */
const props = defineProps<{
  model: DiagnosisDocsModelView
}>()

const { t } = useI18n()

const handleDocSelect = (event: Event) => {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length === 0) return
  for (const file of files) {
    void props.model.uploadDoc(file)
  }
  input.value = ''
}

const docMeta = (doc: DiagnosisDocItem) => {
  const parts: string[] = []
  if (doc.source_ext) parts.push(doc.source_ext)
  if (doc.created_at) parts.push(new Date(doc.created_at).toLocaleString())
  return parts.join(' · ')
}
</script>

<template>
  <div class="diag-panel">
    <header class="diag-panel-header">
      <div class="diag-panel-title-group">
        <div class="diag-panel-title-line">
          <div class="diag-panel-title-icon">
            <FileText :size="18" :stroke-width="2.5" />
          </div>
          <span>{{ t('diagnosis.docs_drawer_title') }}</span>
        </div>
        <p class="diag-panel-subtitle">{{ t('diagnosis.docs_upload_hint') }}</p>
      </div>
      <div class="diag-panel-actions">
        <!-- 问题定位诊断文档：类型不限（日志/CSV/压缩包等），后端 upload-diagnosis-doc 无扩展名限制 -->
        <input
          id="diag-panel-file"
          type="file"
          class="diag-hidden-input"
          multiple
          @change="handleDocSelect"
        />
        <label for="diag-panel-file" class="btn-ghost diag-upload-btn" :class="{ disabled: props.model.uploading }">
          <Loader2 v-if="props.model.uploading" class="w-4 h-4 diag-spin" />
          <Upload v-else class="w-4 h-4" />
          <span>{{ t('diagnosis.upload_docs') }}</span>
        </label>
      </div>
    </header>

    <div class="diag-body">
      <aside class="diag-doc-list-pane">
        <div v-if="props.model.docsLoading" class="diag-state">
          <Loader2 class="w-4 h-4 diag-spin" />
          <span>{{ t('common.loading') }}</span>
        </div>
        <div v-else-if="props.model.docs.length === 0" class="diag-state">{{ t('diagnosis.docs_empty') }}</div>
        <div v-else class="diag-doc-list">
          <button
            v-for="doc in props.model.docs"
            :key="doc.id"
            type="button"
            class="diag-doc-item"
            :class="{ active: props.model.activeDoc?.id === doc.id }"
            @click="props.model.selectDoc(doc)"
          >
            <div class="diag-doc-icon-container blue">
              <FileText :size="14" :stroke-width="2.5" />
            </div>
            <div class="diag-doc-body">
              <span class="diag-doc-name">{{ doc.name.split('/').pop() }}</span>
              <span class="diag-doc-meta">{{ docMeta(doc) }}</span>
            </div>
          </button>
        </div>
      </aside>

      <section class="diag-doc-preview-pane">
        <div v-if="props.model.activeDocLoading" class="diag-state diag-preview-state">
          <Loader2 class="w-4 h-4 diag-spin" />
          <span>{{ t('common.loading') }}</span>
        </div>
        <div v-else-if="props.model.activeDoc" class="diag-doc-preview">
          <div class="diag-preview-title">
            <div class="diag-doc-icon-container blue">
              <FileText :size="14" :stroke-width="2.5" />
            </div>
            <span>{{ props.model.activeDoc.name.split('/').pop() }}</span>
          </div>
          <pre v-if="props.model.activeDoc.content_text" class="diag-preview-content">{{ props.model.activeDoc.content_text }}</pre>
          <div v-else class="diag-state diag-preview-state">{{ t('diagnosis.docs_preview_empty') }}</div>
        </div>
        <div v-else class="diag-state diag-preview-state">
          <FileText class="w-10 h-10 opacity-10" />
          <span>{{ t('diagnosis.docs_empty') }}</span>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped src="./diagnosis-panel.css"></style>
<style scoped>
.diag-doc-list-pane {
  width: 280px;
  min-width: 230px;
  border-right: 1px solid rgba(14, 165, 233, 0.08);
  overflow-y: auto;
  padding: 12px;
  background: rgba(255, 255, 255, 0.25);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.diag-doc-preview-pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px 18px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.25);
}

.diag-preview-state {
  flex: 1;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
}

.diag-doc-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.diag-doc-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  width: 100%;
  transition: all var(--transition-fast);
}

.diag-doc-item:hover {
  border-color: rgba(14, 165, 233, 0.45);
  background: var(--color-primary-50);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.diag-doc-item.active {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.diag-doc-icon-container {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  flex-shrink: 0;
}

.diag-doc-icon-container.blue {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}

.diag-doc-icon-container.amber {
  background: #fffbeb;
  color: #d97706;
}

.diag-doc-body {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.diag-doc-name {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-title);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diag-doc-meta {
  font-size: 0.68rem;
  color: var(--color-text-muted);
}

.diag-doc-preview {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: var(--radius-lg);
  background: #ffffff;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.diag-preview-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--color-text-title);
  background: rgba(255, 255, 255, 0.6);
}

.diag-preview-content {
  flex: 1;
  margin: 0;
  padding: 14px 16px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  line-height: 1.65;
  color: var(--color-text-body);
}
</style>
