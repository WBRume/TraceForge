<script setup lang="ts">
import { computed, onScopeDispose, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import IdeOpenButton from './IdeOpenButton.vue'
import MonacoDiffViewer from '@/components/diff/MonacoDiffViewer.vue'
import { Laptop, UploadCloud } from '@/components/icons'

const props = defineProps<{
  leftHash?: string; rightHash?: string; leftLabel: string; rightLabel: string
  readText: (hash: string) => Promise<string>; path: string
  wordWrap?: boolean; openInIde?: boolean; ideTitle?: string
}>()
const emit = defineEmits<{ 'open-in-ide': [position: { line: number; column: number }]; 'ide-error': [message: string] }>()
const { t } = useI18n()
const media = window.matchMedia('(max-width: 720px)')
const compact = shallowRef(media.matches), preferredLayout = shallowRef<'split' | 'unified' | null>(null)
const onResize = () => { compact.value = media.matches }
media.addEventListener('change', onResize)
onScopeDispose(() => media.removeEventListener('change', onResize))
const layout = computed({ get: () => preferredLayout.value || (compact.value ? 'unified' : 'split'), set: value => { preferredLayout.value = value } })
const original = shallowRef(''), modified = shallowRef('')
const loading = shallowRef(false), error = shallowRef('')
watch(() => [props.leftHash, props.rightHash, props.path], async (_, __, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  loading.value = true; error.value = ''; original.value = ''; modified.value = ''
  try {
    const pair = await Promise.all([props.leftHash ? props.readText(props.leftHash) : '', props.rightHash ? props.readText(props.rightHash) : ''])
    if (current) [original.value, modified.value] = pair
  } catch (reason) { if (current) error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { if (current) loading.value = false }
}, { immediate: true })

const pathParts = computed(() => {
  const parts = props.path.split('/')
  const fileName = parts.pop() || ''
  return { dir: parts.join(' / '), file: fileName }
})
</script>

<template>
  <section class="code-comparison">
    <!-- 顶部工具条 -->
    <div class="comparison-toolbar">
      <div class="breadcrumb-box" :title="path">
        <span v-if="pathParts.dir" class="dir-path">{{ pathParts.dir }} /</span>
        <strong class="file-path">{{ pathParts.file }}</strong>
      </div>
      <div class="comparison-tools">
        <IdeOpenButton v-if="openInIde" :title="ideTitle" @open="emit('open-in-ide', { line: 1, column: 1 })" @error="emit('ide-error', $event)" />
        <slot name="tools" />
        <div class="view-mode-toggle" role="group" :aria-label="t('collaboration.ui.diffLayout')">
          <button type="button" class="mode-btn" :class="{ active: layout === 'split' }" @click="layout = 'split'">
            {{ t('collaboration.split') }}
          </button>
          <button type="button" class="mode-btn" :class="{ active: layout === 'unified' }" @click="layout = 'unified'">
            {{ t('collaboration.unified') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 对比源列头 -->
    <div class="diff-version-headers">
      <div class="version-header-pane left">
        <span class="version-badge">
          <Laptop :size="13" class="version-icon" />
          <span>{{ leftLabel }}{{ !leftHash ? ` · ${t('collaboration.absent')}` : '' }}</span>
        </span>
        <code v-if="leftHash" class="sha-pill">{{ leftHash.slice(0, 7) }}</code>
      </div>
      <div class="version-header-pane right">
        <span class="version-badge right-badge">
          <UploadCloud :size="13" class="version-icon" />
          <span>{{ rightLabel }}{{ !rightHash ? ` · ${t('collaboration.absent')}` : '' }}</span>
        </span>
        <code v-if="rightHash" class="sha-pill">{{ rightHash.slice(0, 7) }}</code>
      </div>
    </div>

    <p v-if="error" role="alert" class="state-message error">{{ error }}</p>
    <p v-else-if="loading" role="status" class="state-message loading">{{ t('common.loading') }}</p>
    <div v-else class="monaco-wrapper">
      <MonacoDiffViewer :file-path="path" :original-label="leftLabel" :modified-label="rightLabel" :original-revision="leftHash" :modified-revision="rightHash" :open-in-ide="openInIde" :ide-title="ideTitle" @open-in-ide="emit('open-in-ide', $event)" :original="original" :modified="modified" :render-side-by-side="layout === 'split'" :word-wrap="wordWrap ? 'on' : 'off'" theme="vs" height="100%" />
    </div>
  </section>
</template>

<style scoped>
.code-comparison {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 180px;
  min-width: 0;
  overflow: hidden;
  background: #ffffff;
}

.comparison-toolbar {
  --comparison-control-height: 30px;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  padding: 8px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.breadcrumb-box {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
}
.dir-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  color: #64748b;
  font-family: var(--font-mono, monospace);
}
.file-path {
  flex-shrink: 0;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono, monospace);
  font-size: 12.5px;
  font-weight: 600;
  color: #0f172a;
}

.comparison-tools {
  display: flex;
  width: 100%;
  min-width: 0;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.comparison-toolbar :deep(.base-select) {
  flex: none;
  width: 140px;
  min-width: 140px;
}
.comparison-toolbar :deep(.select-trigger) { height: var(--comparison-control-height); border-radius: 6px; padding: 0 10px; }
.comparison-toolbar :deep(.selected-text) { font-size: 12px; }
.comparison-toolbar :deep(.select-arrow) { width: 14px; height: 14px; }

/* 视图模式切换胶囊 */
.view-mode-toggle {
  display: inline-flex;
  flex: none;
  margin-left: auto;
  height: var(--comparison-control-height);
  box-sizing: border-box;
  align-items: center;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 2px;
  gap: 2px;
}
.mode-btn {
  height: 100%;
  padding: 0 8px;
  line-height: 20px;
  font-size: 11px;
  font-weight: 500;
  border: 0;
  background: transparent;
  color: #64748b;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.mode-btn:hover {
  color: #0f172a;
}
.mode-btn.active {
  background: #ffffff;
  color: #0284c7;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

/* 对比源版本列头 */
.diff-version-headers {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
  font-size: 11.5px;
}
.version-header-pane {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 16px;
  color: #334155;
  font-weight: 500;
}
.version-header-pane.left {
  border-right: 1px solid #e2e8f0;
}
.version-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.version-badge.right-badge {
  color: #0284c7;
}
.version-icon {
  flex-shrink: 0;
  opacity: 0.85;
}
.sha-pill {
  font-family: var(--font-mono, monospace);
  font-size: 10.5px;
  color: #64748b;
  background: #ffffff;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid #cbd5e1;
}

.monaco-wrapper {
  flex: 1;
  min-height: 0;
  width: 100%;
  position: relative;
}

.state-message {
  padding: 24px;
  font-size: 12px;
  color: #64748b;
  text-align: center;
}
.state-message.error {
  color: #dc2626;
  background: #fef2f2;
}

@media (max-width: 600px) {
  .diff-version-headers { grid-template-columns: 1fr; }
  .version-header-pane.left { border-right: 0; border-bottom: 1px solid #e2e8f0; }
}
</style>
