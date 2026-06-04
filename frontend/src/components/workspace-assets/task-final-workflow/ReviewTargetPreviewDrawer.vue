<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertCircle, FileSearch } from 'lucide-vue-next'
import DeltaFileNav from '@/components/diff/DeltaFileNav.vue'
import HumanPatchCompare from '@/components/diff/HumanPatchCompare.vue'
import type {
  ReviewTargetPreviewBlock,
  ReviewTargetPreviewResponse,
  ReviewTargetRef,
  ReviewTargetType,
} from '@/types/workspaceAssets'

const props = defineProps<{
  visible: boolean
  target: ReviewTargetRef | null
  preview: ReviewTargetPreviewResponse | null
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

const { t, te } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow'
const selectedFilePath = shallowRef<string | null>(null)

const hasPreview = computed(() => Boolean(props.preview))
const headerTitle = computed(() => props.preview?.title || props.target?.label || props.target?.target_id || '')
const fileDiffBlock = computed(() => props.preview?.blocks.find((block) => block.kind === 'file_diffs' && block.file_diffs.length) ?? null)

watch(
  () => fileDiffBlock.value?.file_diffs.map((file) => file.file_path).join('|') ?? '',
  () => {
    selectedFilePath.value = fileDiffBlock.value?.file_diffs[0]?.file_path ?? null
  },
  { immediate: true },
)

function close() {
  emit('update:visible', false)
}

function targetTypeLabel(type?: ReviewTargetType | string | null) {
  const key = `${baseKey}.target_types.${String(type || 'task_file').toLowerCase()}`
  return te(key) ? t(key) : String(type || '')
}

function statusLabel(status?: string | null) {
  const normalized = String(status || '').toLowerCase().replace(/-/g, '_')
  const key = `${baseKey}.status.${normalized}`
  return normalized && te(key) ? t(key) : status
}

function blockTitle(block: ReviewTargetPreviewBlock) {
  const key = `${baseKey}.target_preview.blocks.${block.key}`
  return te(key) ? t(key) : block.title
}

function metadataLabel(key: string, fallback?: string | null) {
  const i18nKey = `${baseKey}.target_preview.metadata.${key}`
  return te(i18nKey) ? t(i18nKey) : (fallback || key)
}

function itemLabel(item: Record<string, unknown>) {
  return metadataLabel(String(item.key || item.label || ''), String(item.label || item.key || ''))
}

function itemValue(item: Record<string, unknown>) {
  const value = item.value ?? item.body ?? item.content
  return value === null || value === undefined ? '-' : String(value)
}

function isTextBlock(block: ReviewTargetPreviewBlock) {
  return ['text', 'markdown', 'json', 'diff'].includes(block.kind)
}
</script>

<template>
  <el-drawer
    :model-value="visible"
    :title="t(`${baseKey}.target_preview.drawer_title`)"
    size="860px"
    append-to-body
    destroy-on-close
    @close="close"
  >
    <div class="preview-drawer-body">
      <div v-if="loading" class="preview-loading">
        <el-skeleton :rows="8" animated />
      </div>

      <el-alert
        v-else-if="error"
        type="error"
        :closable="false"
        class="preview-error"
        :title="t(`${baseKey}.target_preview.error_title`)"
      >
        <template #default>
          <span>{{ error }}</span>
        </template>
      </el-alert>

      <div v-else-if="hasPreview && preview" class="preview-content">
        <header class="preview-header">
          <div class="preview-icon">
            <FileSearch />
          </div>
          <div class="preview-heading">
            <div class="preview-kicker">
              <span>{{ targetTypeLabel(preview.target.target_type) }}</span>
              <span v-if="preview.status">{{ statusLabel(preview.status) }}</span>
            </div>
            <h3>{{ headerTitle }}</h3>
            <p v-if="preview.subtitle">{{ preview.subtitle }}</p>
          </div>
        </header>

        <dl v-if="preview.metadata.length" class="preview-metadata">
          <div v-for="item in preview.metadata" :key="item.key" class="metadata-item">
            <dt>{{ metadataLabel(item.key, item.label) }}</dt>
            <dd>{{ item.value }}</dd>
          </div>
        </dl>

        <div v-if="preview.blocks.length" class="preview-blocks">
          <section v-for="block in preview.blocks" :key="block.key" class="preview-block">
            <h4>{{ blockTitle(block) }}</h4>

            <dl v-if="block.kind === 'metadata' || block.kind === 'list'" class="block-list">
              <div v-for="(item, index) in block.items" :key="`${block.key}-${index}`" class="block-list-item">
                <dt>{{ itemLabel(item) }}</dt>
                <dd>{{ itemValue(item) }}</dd>
              </div>
            </dl>

            <template v-else-if="block.kind === 'file_diffs'">
              <div v-if="block.file_diffs.length" class="diff-preview-grid">
                <DeltaFileNav
                  class="diff-file-nav"
                  :file-diffs="block.file_diffs"
                  :delta-regions="block.delta_regions ?? []"
                  :selected-file-path="selectedFilePath"
                  @select-file="selectedFilePath = $event"
                />
                <HumanPatchCompare
                  class="diff-file-viewer"
                  :file-diffs="block.file_diffs"
                  :delta-regions="block.delta_regions ?? []"
                  :selected-file-path="selectedFilePath"
                />
              </div>
              <pre v-else-if="block.diff_text" class="text-block">{{ block.diff_text }}</pre>
              <p v-else class="block-empty">{{ t(`${baseKey}.target_preview.empty_block`) }}</p>
            </template>

            <pre v-else-if="isTextBlock(block)" class="text-block">{{ block.diff_text || block.content }}</pre>
            <p v-else class="block-empty">{{ t(`${baseKey}.target_preview.empty_block`) }}</p>
          </section>
        </div>

        <p v-else class="block-empty">{{ t(`${baseKey}.target_preview.empty_preview`) }}</p>
      </div>

      <div v-else class="preview-empty">
        <AlertCircle class="preview-empty-icon" />
        <span>{{ t(`${baseKey}.target_preview.empty_preview`) }}</span>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.preview-drawer-body {
  min-height: 100%;
}

.preview-loading,
.preview-empty {
  padding: 18px;
}

.preview-error {
  border-radius: 8px;
}

.preview-content {
  display: grid;
  gap: 16px;
}

.preview-header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding-bottom: 14px;
  border-bottom: 1px solid #e2e8f0;
}

.preview-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 8px;
  background: #eff6ff;
  color: #2563eb;
}

.preview-icon svg,
.preview-empty-icon {
  width: 18px;
  height: 18px;
}

.preview-heading {
  min-width: 0;
}

.preview-kicker {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
}

.preview-heading h3 {
  margin: 5px 0 0;
  color: #0f172a;
  font-size: 1.04rem;
  line-height: 1.35;
}

.preview-heading p {
  margin: 5px 0 0;
  color: #64748b;
  font-size: 0.82rem;
}

.preview-metadata,
.block-list {
  display: grid;
  gap: 8px;
  margin: 0;
}

.preview-metadata {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.metadata-item,
.block-list-item {
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.metadata-item dt,
.block-list-item dt {
  color: #64748b;
  font-size: 0.68rem;
  font-weight: 800;
}

.metadata-item dd,
.block-list-item dd {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
  color: #0f172a;
  font-size: 0.8rem;
  line-height: 1.45;
}

.preview-blocks {
  display: grid;
  gap: 14px;
}

.preview-block {
  display: grid;
  gap: 10px;
}

.preview-block h4 {
  margin: 0;
  color: #0f172a;
  font-size: 0.92rem;
}

.text-block {
  max-height: 360px;
  margin: 0;
  overflow: auto;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #0f172a;
  color: #e2e8f0;
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
  font-size: 0.78rem;
  line-height: 1.55;
  white-space: pre-wrap;
}

.diff-preview-grid {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  min-height: 440px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}

.diff-file-nav {
  min-height: 0;
  border-right: 1px solid #e2e8f0;
}

.diff-file-viewer {
  min-width: 0;
  min-height: 0;
}

.block-empty,
.preview-empty {
  color: #64748b;
  font-size: 0.84rem;
}

.preview-empty {
  display: flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 900px) {
  .preview-metadata,
  .diff-preview-grid {
    grid-template-columns: 1fr;
  }

  .diff-file-nav {
    border-right: 0;
    border-bottom: 1px solid #e2e8f0;
  }
}
</style>
