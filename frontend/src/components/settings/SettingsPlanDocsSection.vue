<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  Folder,
  Plus,
  Trash2,
  Copy,
  RotateCcw,
  Info,
  TriangleAlert,
  RefreshCw,
  Loader2,
} from '@/components/icons'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'

type PlanDocSettings = { workspace_id: string; roots: string[]; can_edit: boolean }

const props = defineProps<{ workspaceId: string }>()
const { t } = useI18n()

const rootsList = ref<string[]>([])
const rawText = ref('')
const newPathInput = ref('')
const mode = ref<'list' | 'raw'>('list')
const canEdit = ref(false)
const loaded = ref(false)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
let loadId = 0

const DEFAULT_PRESETS = ['docs/plans', 'docs/specs', 'archive']

const isConfigured = computed(() => rootsList.value.length > 0)

const normalizePath = (raw: string): string => {
  const trimmed = raw.trim().replace(/\\/g, '/')
  if (trimmed === '.') return '.'
  return trimmed.replace(/^\/+|\/+$/g, '')
}

const syncRawToList = () => {
  const lines = rawText.value
    .split('\n')
    .map(normalizePath)
    .filter(Boolean)
  rootsList.value = Array.from(new Set(lines))
}

const syncListToRaw = () => {
  rawText.value = rootsList.value.join('\n')
}

const switchMode = (target: 'list' | 'raw') => {
  if (target === mode.value) return
  if (target === 'raw') {
    syncListToRaw()
  } else {
    syncRawToList()
  }
  mode.value = target
}

const addPath = (rawVal?: string) => {
  if (!canEdit.value || loading.value || saving.value) return
  const target = normalizePath(rawVal !== undefined ? rawVal : newPathInput.value)
  if (!target) return

  if (rootsList.value.includes(target)) {
    ElMessage.warning(t('settings.plan_docs.already_exists'))
    return
  }

  rootsList.value.push(target)
  if (rawVal === undefined) {
    newPathInput.value = ''
  }
  syncListToRaw()
}

const removePath = (index: number) => {
  if (!canEdit.value || loading.value || saving.value) return
  rootsList.value.splice(index, 1)
  syncListToRaw()
}

const copyPath = async (path: string) => {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(path)
      ElMessage.success(t('settings.plan_docs.copied'))
    }
  } catch {
    // 降级静默或已有系统提示
  }
}

const resetToDefaults = () => {
  if (!canEdit.value || loading.value || saving.value) return
  rootsList.value = [...DEFAULT_PRESETS]
  syncListToRaw()
}

const load = async () => {
  const requestId = ++loadId
  const workspaceId = props.workspaceId
  rootsList.value = []
  rawText.value = ''
  newPathInput.value = ''
  canEdit.value = false
  loaded.value = false
  saving.value = false
  error.value = ''
  loading.value = Boolean(workspaceId)
  if (!workspaceId) return

  try {
    const response = await api.get<PlanDocSettings>(`/workspaces/${workspaceId}/plan-docs-settings`)
    if (requestId !== loadId) return
    rootsList.value = Array.isArray(response.data?.roots) ? response.data.roots : []
    syncListToRaw()
    canEdit.value = Boolean(response.data?.can_edit)
    loaded.value = true
  } catch (err) {
    if (requestId === loadId) {
      error.value = formatApiError(err, t('management.common.operation_failed'), t)
    }
  } finally {
    if (requestId === loadId) {
      loading.value = false
    }
  }
}

const save = async () => {
  if (!loaded.value || !canEdit.value || saving.value || loading.value) return
  const requestId = loadId
  const workspaceId = props.workspaceId

  if (mode.value === 'raw') {
    syncRawToList()
  }

  const roots = rootsList.value.map(normalizePath).filter(Boolean)
  saving.value = true
  error.value = ''

  try {
    const response = await api.put<PlanDocSettings>(`/workspaces/${workspaceId}/plan-docs-settings`, { roots })
    if (requestId !== loadId || workspaceId !== props.workspaceId) return
    rootsList.value = Array.isArray(response.data?.roots) ? response.data.roots : []
    syncListToRaw()
    ElMessage.success(t('system_config.saved'))
  } catch (err) {
    if (requestId === loadId) {
      error.value = formatApiError(err, t('management.common.operation_failed'), t)
    }
  } finally {
    if (requestId === loadId) {
      saving.value = false
    }
  }
}

watch(() => props.workspaceId, load, { immediate: true })
</script>

<template>
  <form class="plan-doc-settings animate-fade-in" @submit.prevent="save">
    <!-- 模块头部 -->
    <header class="section-header">
      <div class="icon-circle">
        <Folder class="w-6 h-6" />
      </div>
      <div class="section-title-group">
        <div class="title-row">
          <h2>{{ t('settings.plan_docs.title') }}</h2>
          <span
            v-if="loaded"
            class="status-badge"
            :class="isConfigured ? 'status-ready' : 'status-disabled'"
          >
            <span class="status-dot"></span>
            {{ t(isConfigured ? 'settings.plan_docs.status_ready' : 'settings.plan_docs.status_disabled') }}
          </span>
        </div>
        <p>{{ t('settings.plan_docs.desc') }}</p>
      </div>
    </header>

    <!-- 错误状态提示卡片 (替代生硬的裸露 Not Found) -->
    <div v-if="error" class="alert-banner alert-danger" role="alert">
      <TriangleAlert class="w-5 h-5 alert-icon" />
      <div class="alert-content">
        <div class="alert-title">{{ t('settings.plan_docs.load_failed_title') }}</div>
        <p class="alert-message">{{ error }}</p>
      </div>
      <button
        v-if="!loaded"
        type="button"
        class="btn-retry"
        :disabled="loading"
        @click="load"
      >
        <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
        <span>{{ t('settings.plan_docs.retry') }}</span>
      </button>
    </div>

    <!-- 主配置区域 -->
    <div class="config-panel">
      <!-- 栏目标题与模式切换 -->
      <div class="panel-header">
        <div class="header-left">
          <label class="panel-label">{{ t('settings.plan_docs.roots') }}</label>
          <span v-if="loaded" class="count-pill">
            {{ t('settings.plan_docs.count_badge', { count: rootsList.length }) }}
          </span>
        </div>

        <div v-if="loaded && canEdit" class="mode-switch">
          <button
            type="button"
            class="mode-btn"
            :class="{ active: mode === 'list' }"
            @click="switchMode('list')"
          >
            {{ t('settings.plan_docs.mode_list') }}
          </button>
          <button
            type="button"
            class="mode-btn"
            :class="{ active: mode === 'raw' }"
            @click="switchMode('raw')"
          >
            {{ t('settings.plan_docs.mode_raw') }}
          </button>
        </div>
      </div>

      <!-- 加载中占位 -->
      <div v-if="loading && !loaded" class="loading-state">
        <Loader2 class="w-6 h-6 animate-spin text-sky-500" />
        <span>{{ t('common.loading') }}</span>
      </div>

      <template v-else-if="loaded">
        <!-- 模式一：条目模式 (默认推荐) -->
        <div v-if="mode === 'list'" class="mode-list-view">
          <!-- 路径条目列表 -->
          <div v-if="rootsList.length > 0" class="path-items-container">
            <div
              v-for="(path, index) in rootsList"
              :key="`${path}-${index}`"
              class="path-item-card"
            >
              <div class="path-item-left">
                <div class="item-icon-box">
                  <Folder class="w-4 h-4 text-sky-600" />
                </div>
                <span class="path-text">{{ path }}</span>
                <span v-if="path === '.'" class="root-tag">
                  {{ t('settings.plan_docs.root_dir_tag') }}
                </span>
              </div>

              <div class="path-item-actions">
                <button
                  type="button"
                  class="action-icon-btn"
                  :title="t('settings.plan_docs.copy_path')"
                  @click="copyPath(path)"
                >
                  <Copy class="w-3.5 h-3.5" />
                </button>
                <button
                  v-if="canEdit"
                  type="button"
                  class="action-icon-btn remove-btn"
                  :title="t('settings.plan_docs.remove_path')"
                  :disabled="saving"
                  @click="removePath(index)"
                >
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </div>

          <!-- 空列表提示 -->
          <div v-else class="empty-path-box">
            <p>{{ t('settings.plan_docs.empty_tip') }}</p>
          </div>

          <!-- 新增路径输入行 -->
          <div v-if="canEdit" class="add-path-bar">
            <div class="input-wrapper">
              <Folder class="w-4 h-4 input-prefix-icon" />
              <input
                v-model="newPathInput"
                type="text"
                class="path-input"
                :placeholder="t('settings.plan_docs.input_placeholder')"
                :disabled="saving"
                @keydown.enter.prevent="addPath()"
              />
            </div>
            <button
              type="button"
              class="btn-add-path"
              :disabled="saving || !newPathInput.trim()"
              @click="addPath()"
            >
              <Plus class="w-4 h-4" />
              <span>{{ t('settings.plan_docs.add_path') }}</span>
            </button>
          </div>

          <!-- 推荐预设快速填充 -->
          <div v-if="canEdit" class="presets-row">
            <span class="presets-label">{{ t('settings.plan_docs.presets_label') }}:</span>
            <button
              v-for="preset in DEFAULT_PRESETS"
              :key="preset"
              type="button"
              class="preset-pill"
              :disabled="rootsList.includes(preset) || saving"
              @click="addPath(preset)"
            >
              <span class="preset-plus">+</span>
              <span>{{ preset }}</span>
            </button>
            <button
              type="button"
              class="preset-pill"
              :disabled="rootsList.includes('.') || saving"
              @click="addPath('.')"
            >
              <span class="preset-plus">+</span>
              <span>. ({{ t('settings.plan_docs.root_dir_tag') }})</span>
            </button>
          </div>
        </div>

        <!-- 模式二：批量文本 (RAW) 模式 -->
        <div v-else class="mode-raw-view">
          <div class="raw-textarea-wrapper">
            <textarea
              id="plan-doc-roots-raw"
              v-model="rawText"
              rows="6"
              spellcheck="false"
              class="raw-textarea"
              :disabled="loading || saving || !loaded"
              :readonly="!canEdit"
              :placeholder="t('settings.plan_docs.placeholder')"
            ></textarea>
            <span class="raw-badge">{{ t('settings.plan_docs.raw_tip') }}</span>
          </div>
          <div class="raw-actions-bar">
            <button
              type="button"
              class="btn-secondary btn-sm"
              @click="switchMode('list')"
            >
              {{ t('settings.plan_docs.complete_raw') }}
            </button>
          </div>
        </div>
      </template>

      <!-- 结构化说明规则卡片 -->
      <div class="rules-grid">
        <div class="rule-card">
          <div class="rule-icon-circle blue">
            <Info class="w-4 h-4" />
          </div>
          <div class="rule-text">
            <div class="rule-title">{{ t('settings.plan_docs.rule_scan_title') }}</div>
            <p>{{ t('settings.plan_docs.rule_scan_desc') }}</p>
          </div>
        </div>

        <div class="rule-card">
          <div class="rule-icon-circle green">
            <Folder class="w-4 h-4" />
          </div>
          <div class="rule-text">
            <div class="rule-title">{{ t('settings.plan_docs.rule_incremental_title') }}</div>
            <p>{{ t('settings.plan_docs.rule_incremental_desc') }}</p>
          </div>
        </div>
      </div>

      <!-- 只读提示 -->
      <p v-if="loaded && !canEdit" class="field-hint text-amber-600" role="status">
        {{ t('settings.plan_docs.readonly') }}
      </p>
    </div>

    <!-- 底部操作区域 -->
    <footer class="section-footer">
      <div class="footer-left">
        <button
          v-if="canEdit && loaded"
          type="button"
          class="btn-reset-default"
          :disabled="saving || loading"
          @click="resetToDefaults"
        >
          <RotateCcw class="w-3.5 h-3.5" />
          <span>{{ t('settings.plan_docs.reset_default') }}</span>
        </button>
      </div>

      <div class="footer-right">
        <button
          v-if="error && !loaded"
          type="button"
          class="btn-secondary"
          :disabled="loading"
          @click="load"
        >
          {{ t('settings.plan_docs.retry') }}
        </button>
        <button
          v-if="canEdit"
          type="submit"
          class="btn-primary"
          :disabled="loading || saving || !loaded"
        >
          <Loader2 v-if="saving" class="w-4 h-4 animate-spin mr-1.5" />
          <span>{{ t(saving ? 'system_config.saving' : 'system_config.save') }}</span>
        </button>
      </div>
    </footer>
  </form>
</template>

<style scoped src="@/styles/settings/general.css"></style>
<style scoped>
.plan-doc-settings {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.section-header {
  margin-bottom: 0;
  align-items: flex-start;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.section-title-group h2 {
  margin: 0;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.125rem 0.625rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 500;
  transition: all 0.2s ease;
}

.status-ready {
  background-color: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.status-disabled {
  background-color: #f1f5f9;
  color: #64748b;
  border: 1px solid #cbd5e1;
}

.status-dot {
  width: 0.375rem;
  height: 0.375rem;
  border-radius: 9999px;
  background-color: currentColor;
}

/* 优雅的错误卡片 */
.alert-banner {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  border-radius: 0.75rem;
  font-size: 0.875rem;
}

.alert-danger {
  background-color: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}

.alert-icon {
  flex-shrink: 0;
  color: #ef4444;
  margin-top: 0.125rem;
}

.alert-content {
  flex: 1;
  min-width: 0;
}

.alert-title {
  font-weight: 600;
  margin-bottom: 0.125rem;
}

.alert-message {
  font-size: 0.8125rem;
  color: #b91c1c;
  margin: 0;
  line-height: 1.5;
  word-break: break-all;
}

.btn-retry {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  background-color: #ffffff;
  border: 1px solid #fca5a5;
  border-radius: 0.5rem;
  color: #b91c1c;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-retry:hover {
  background-color: #fee2e2;
}

/* 主面板 */
.config-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.panel-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #334155;
}

.count-pill {
  padding: 0.125rem 0.5rem;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 500;
  color: #64748b;
}

.mode-switch {
  display: flex;
  background-color: #f1f5f9;
  padding: 0.25rem;
  border-radius: 0.625rem;
  gap: 0.25rem;
}

.mode-btn {
  border: none;
  background: transparent;
  padding: 0.25rem 0.625rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: #64748b;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.mode-btn.active {
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 2.5rem;
  color: #64748b;
  font-size: 0.875rem;
}

/* 列表视图 */
.mode-list-view {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.path-items-container {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.path-item-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.625rem 0.875rem;
  background-color: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  transition: all 0.2s ease;
}

.path-item-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 2px 6px -1px rgba(14, 165, 233, 0.08);
}

.path-item-left {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  min-width: 0;
  flex: 1;
}

.item-icon-box {
  width: 1.75rem;
  height: 1.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #f0f9ff;
  border-radius: 0.5rem;
  flex-shrink: 0;
}

.path-text {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.875rem;
  font-weight: 500;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.root-tag {
  font-size: 0.6875rem;
  padding: 0.125rem 0.375rem;
  background-color: #fef3c7;
  color: #b45309;
  border-radius: 0.25rem;
  font-weight: 600;
}

.path-item-actions {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.action-icon-btn {
  border: none;
  background: transparent;
  color: #94a3b8;
  padding: 0.375rem;
  border-radius: 0.375rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.action-icon-btn:hover {
  background-color: #f1f5f9;
  color: #334155;
}

.action-icon-btn.remove-btn:hover {
  background-color: #fef2f2;
  color: #ef4444;
}

.empty-path-box {
  padding: 1.5rem;
  text-align: center;
  border: 1px dashed #cbd5e1;
  border-radius: 0.75rem;
  background-color: #f8fafc;
  color: #94a3b8;
  font-size: 0.8125rem;
}

/* 输入栏 */
.add-path-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.input-wrapper {
  position: relative;
  flex: 1;
}

.input-prefix-icon {
  position: absolute;
  left: 0.75rem;
  top: 50%;
  transform: translateY(-50%);
  color: #94a3b8;
  pointer-events: none;
}

.path-input {
  width: 100%;
  box-sizing: border-box;
  padding: 0.5625rem 0.75rem 0.5625rem 2.25rem;
  background-color: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 0.625rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.8125rem;
  color: #1e293b;
  transition: all 0.2s ease;
}

.path-input:focus {
  outline: none;
  border-color: #0284c7;
  box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.15);
}

.btn-add-path {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5625rem 1rem;
  background: #0284c7;
  color: #ffffff;
  border: none;
  border-radius: 0.625rem;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.btn-add-path:hover:not(:disabled) {
  background: #0369a1;
}

.btn-add-path:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 预设 */
.presets-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.375rem;
  padding-top: 0.125rem;
}

.presets-label {
  font-size: 0.75rem;
  color: #94a3b8;
  font-weight: 500;
}

.preset-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  font-size: 0.75rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s ease;
}

.preset-pill:hover:not(:disabled) {
  background: #f0f9ff;
  border-color: #bae6fd;
  color: #0284c7;
}

.preset-pill:disabled {
  opacity: 0.45;
  cursor: default;
}

.preset-plus {
  font-weight: 700;
  color: #0284c7;
}

/* RAW 视图 */
.mode-raw-view {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.raw-textarea-wrapper {
  position: relative;
}

.raw-textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  padding: 0.875rem;
  background: #0f172a;
  color: #38bdf8;
  border: 1px solid #334155;
  border-radius: 0.75rem;
  font: 0.875rem/1.7 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.raw-textarea:focus {
  outline: none;
  border-color: #38bdf8;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.2);
}

.raw-badge {
  position: absolute;
  right: 0.75rem;
  top: 0.75rem;
  font-size: 0.6875rem;
  background: rgba(30, 41, 59, 0.85);
  color: #94a3b8;
  padding: 0.125rem 0.5rem;
  border-radius: 0.25rem;
  border: 1px solid #334155;
  pointer-events: none;
}

.raw-actions-bar {
  display: flex;
  justify-content: flex-end;
}

/* 结构化说明规则卡片 */
.rules-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 0.75rem;
  margin-top: 0.25rem;
}

.rule-card {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.75rem 0.875rem;
  background-color: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
}

.rule-icon-circle {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 0.125rem;
}

.rule-icon-circle.blue {
  background-color: #e0f2fe;
  color: #0284c7;
}

.rule-icon-circle.green {
  background-color: #dcfce7;
  color: #16a34a;
}

.rule-text {
  font-size: 0.75rem;
  line-height: 1.5;
  color: #64748b;
}

.rule-title {
  font-weight: 600;
  color: #334155;
  margin-bottom: 0.125rem;
}

.rule-text p {
  margin: 0;
}

/* 底部操作区 */
.section-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 1rem;
  border-top: 1px solid #f1f5f9;
}

.btn-reset-default {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  background: transparent;
  border: none;
  color: #64748b;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  padding: 0.375rem 0.625rem;
  border-radius: 0.5rem;
  transition: all 0.2s ease;
}

.btn-reset-default:hover:not(:disabled) {
  background: #f1f5f9;
  color: #1e293b;
}

.footer-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.75rem;
}
</style>

