<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ChevronRight, FileText, Folder, Loader2, RefreshCw, Save, Brain } from 'lucide-vue-next'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'

type SuperpowersDocSection = 'plans' | 'specs'

type SuperpowersDocEntry = {
  section: SuperpowersDocSection
  name: string
  section_path: string
  relative_path: string
  size: number
  updated_at?: string | null
}

type SuperpowersDocsIndexResponse = {
  task_id: string
  root_relative_path: string
  plans: SuperpowersDocEntry[]
  specs: SuperpowersDocEntry[]
}

type SuperpowersDocContentResponse = {
  task_id: string
  section: SuperpowersDocSection
  name: string
  section_path: string
  relative_path: string
  content: string
  updated_at?: string | null
}

type DocRow =
  | {
      kind: 'dir'
      section: SuperpowersDocSection
      key: string
      path: string
      name: string
      depth: number
      expanded: boolean
    }
  | {
      kind: 'file'
      section: SuperpowersDocSection
      key: string
      path: string
      name: string
      depth: number
      entry: SuperpowersDocEntry
    }

const props = defineProps<{
  wsId: string
  taskId: string
  readonly?: boolean
}>()

const { t } = useI18n()

const loadingIndex = ref(false)
const loadingDoc = ref(false)
const saving = ref(false)
const loadError = ref('')
const rootRelativePath = ref('')
const plans = ref<SuperpowersDocEntry[]>([])
const specs = ref<SuperpowersDocEntry[]>([])
const selectedSection = ref<SuperpowersDocSection | ''>('')
const selectedPath = ref('')
const content = ref('')
const originalContent = ref('')
const loadedDocKey = ref('')
const contentRequestId = ref(0)
const expandedDirs = ref<Record<string, boolean>>({})

const selectedDoc = computed(() => {
  const section = selectedSection.value
  const path = selectedPath.value
  if (!section || !path) return null
  const source = section === 'plans' ? plans.value : specs.value
  return source.find(item => item.section_path === path) || null
})

const hasDocs = computed(() => plans.value.length > 0 || specs.value.length > 0)
const isDirty = computed(() => content.value !== originalContent.value)
const canSave = computed(() => Boolean(selectedDoc.value) && isDirty.value && !props.readonly && !saving.value)
const selectedDocKey = computed(() => {
  if (!selectedSection.value || !selectedPath.value) return ''
  return `${selectedSection.value}/${selectedPath.value}`
})

const dirExpansionKey = (section: SuperpowersDocSection, path: string) => `${section}:${path}`

const isDirExpanded = (section: SuperpowersDocSection, path: string) => {
  const key = dirExpansionKey(section, path)
  return expandedDirs.value[key] !== false
}

const toggleDir = (section: SuperpowersDocSection, path: string) => {
  const key = dirExpansionKey(section, path)
  expandedDirs.value = {
    ...expandedDirs.value,
    [key]: !isDirExpanded(section, path),
  }
}

const syncDirectoryExpansionDefaults = (
  section: SuperpowersDocSection,
  entries: SuperpowersDocEntry[],
) => {
  const next = { ...expandedDirs.value }
  entries.forEach((entry) => {
    const segments = String(entry.section_path || '').split('/').filter(Boolean)
    if (segments.length <= 1) return
    let current = ''
    for (let idx = 0; idx < segments.length - 1; idx += 1) {
      current = current ? `${current}/${segments[idx]}` : segments[idx]
      const key = dirExpansionKey(section, current)
      if (next[key] === undefined) {
        next[key] = true
      }
    }
  })
  expandedDirs.value = next
}

const buildRowsForSection = (
  section: SuperpowersDocSection,
  entries: SuperpowersDocEntry[],
): DocRow[] => {
  type MutableDir = {
    name: string
    path: string
    dirs: Map<string, MutableDir>
    files: SuperpowersDocEntry[]
  }

  const createDir = (name: string, path: string): MutableDir => ({
    name,
    path,
    dirs: new Map<string, MutableDir>(),
    files: [],
  })

  const root = createDir('', '')

  entries.forEach((entry) => {
    const segments = String(entry.section_path || '').split('/').filter(Boolean)
    if (segments.length === 0) return
    let cursor = root
    if (segments.length > 1) {
      let dirPath = ''
      for (let idx = 0; idx < segments.length - 1; idx += 1) {
        const seg = segments[idx]
        dirPath = dirPath ? `${dirPath}/${seg}` : seg
        const existing = cursor.dirs.get(seg)
        if (existing) {
          cursor = existing
          continue
        }
        const created = createDir(seg, dirPath)
        cursor.dirs.set(seg, created)
        cursor = created
      }
    }
    cursor.files.push(entry)
  })

  const rows: DocRow[] = []
  const visit = (dir: MutableDir, depth: number) => {
    const subDirs = [...dir.dirs.values()].sort((a, b) => a.name.localeCompare(b.name))
    subDirs.forEach((subDir) => {
      const expanded = isDirExpanded(section, subDir.path)
      rows.push({
        kind: 'dir',
        section,
        key: `dir:${section}:${subDir.path}`,
        path: subDir.path,
        name: subDir.name,
        depth,
        expanded,
      })
      if (expanded) {
        visit(subDir, depth + 1)
      }
    })

    const files = [...dir.files].sort((a, b) => a.name.localeCompare(b.name))
    files.forEach((entry) => {
      rows.push({
        kind: 'file',
        section,
        key: `file:${section}:${entry.section_path}`,
        path: entry.section_path,
        name: entry.name,
        depth,
        entry,
      })
    })
  }

  visit(root, 0)
  return rows
}

const plansRows = computed(() => buildRowsForSection('plans', plans.value))
const specsRows = computed(() => buildRowsForSection('specs', specs.value))

const rowIndentStyle = (depth: number) => ({ paddingLeft: `${8 + depth * 16}px` })

const normalizeEntries = (
  entries: unknown,
  section: SuperpowersDocSection,
): SuperpowersDocEntry[] => {
  if (!Array.isArray(entries)) return []
  return entries
    .filter((item) => item && typeof item === 'object')
    .map((item) => {
      const record = item as Record<string, unknown>
      return {
        section,
        name: String(record.name || ''),
        section_path: String(record.section_path || record.name || ''),
        relative_path: String(record.relative_path || ''),
        size: Number(record.size || 0),
        updated_at: record.updated_at ? String(record.updated_at) : null,
      }
    })
    .filter(item => Boolean(item.name) && Boolean(item.section_path))
}

const clearEditor = () => {
  content.value = ''
  originalContent.value = ''
  loadedDocKey.value = ''
}

const ensureSelection = () => {
  const current = selectedDoc.value
  if (current) return

  if (plans.value.length > 0) {
    selectedSection.value = 'plans'
    selectedPath.value = plans.value[0].section_path
    return
  }

  if (specs.value.length > 0) {
    selectedSection.value = 'specs'
    selectedPath.value = specs.value[0].section_path
    return
  }

  selectedSection.value = ''
  selectedPath.value = ''
  clearEditor()
}

const loadDocContent = async () => {
  const section = selectedSection.value
  const path = selectedPath.value
  if (!section || !path) {
    clearEditor()
    return
  }

  const requestId = contentRequestId.value + 1
  contentRequestId.value = requestId
  loadingDoc.value = true
  loadError.value = ''

  try {
    const res = await api.get(`/workspaces/${props.wsId}/tasks/${props.taskId}/superpowers-docs/content`, {
      params: { section, path },
    })
    if (requestId !== contentRequestId.value) return
    const payload = res.data as SuperpowersDocContentResponse
    const markdown = String(payload.content || '')
    content.value = markdown
    originalContent.value = markdown
    loadedDocKey.value = `${section}/${path}`
  } catch (error) {
    if (requestId !== contentRequestId.value) return
    loadError.value = formatApiError(
      error,
      t('chat.superpowers_docs_load_failed'),
      t,
    )
    clearEditor()
  } finally {
    if (requestId === contentRequestId.value) {
      loadingDoc.value = false
    }
  }
}

const loadIndex = async () => {
  loadingIndex.value = true
  loadError.value = ''
  const previousKey = selectedDocKey.value

  try {
    const res = await api.get(`/workspaces/${props.wsId}/tasks/${props.taskId}/superpowers-docs`)
    const payload = res.data as SuperpowersDocsIndexResponse
    rootRelativePath.value = payload.root_relative_path || 'docs/superpowers'
    plans.value = normalizeEntries(payload.plans, 'plans')
    specs.value = normalizeEntries(payload.specs, 'specs')
    syncDirectoryExpansionDefaults('plans', plans.value)
    syncDirectoryExpansionDefaults('specs', specs.value)
    ensureSelection()

    if (!selectedDocKey.value) {
      clearEditor()
      return
    }

    if (selectedDocKey.value !== previousKey || loadedDocKey.value !== selectedDocKey.value) {
      await loadDocContent()
    }
  } catch (error) {
    plans.value = []
    specs.value = []
    loadError.value = formatApiError(
      error,
      t('chat.superpowers_docs_fetch_failed'),
      t,
    )
    clearEditor()
  } finally {
    loadingIndex.value = false
  }
}

const selectDoc = async (entry: SuperpowersDocEntry) => {
  const nextKey = `${entry.section}/${entry.section_path}`
  if (selectedDocKey.value === nextKey) return

  if (isDirty.value) {
    const shouldDiscard = window.confirm(t('chat.superpowers_docs_discard_confirm'))
    if (!shouldDiscard) return
  }

  selectedSection.value = entry.section
  selectedPath.value = entry.section_path
  await loadDocContent()
}

const saveDoc = async () => {
  const section = selectedSection.value
  const path = selectedPath.value
  if (!section || !path || !canSave.value) return

  saving.value = true
  try {
    const res = await api.put(`/workspaces/${props.wsId}/tasks/${props.taskId}/superpowers-docs/content`, {
      section,
      path,
      content: content.value,
    })
    const payload = res.data as SuperpowersDocContentResponse
    originalContent.value = String(payload.content || '')
    content.value = originalContent.value
    loadedDocKey.value = `${section}/${path}`
    ElMessage.success(t('chat.superpowers_docs_saved'))
    await loadIndex()
  } catch (error) {
    ElMessage.error(formatApiError(error, t('chat.superpowers_docs_save_failed'), t))
  } finally {
    saving.value = false
  }
}

const formatFileSize = (size: number) => {
  const bytes = Number(size || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const formatDateTime = (value?: string | null) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString()
}

watch(
  () => [props.wsId, props.taskId] as const,
  async () => {
    selectedSection.value = ''
    selectedPath.value = ''
    rootRelativePath.value = ''
    clearEditor()
    await loadIndex()
  },
  { immediate: true },
)
</script>

<template>
  <div class="superpowers-docs-panel">
    <header class="panel-header glass-panel">
      <div class="panel-title-group">
        <div class="panel-title-line">
          <div class="panel-title-icon">
            <Brain :size="18" :stroke-width="2.5" />
          </div>
          <span>{{ $t('chat.superpowers_docs_title') }}</span>
        </div>
        <p class="panel-subtitle">{{ $t('chat.superpowers_docs_source_path', { path: rootRelativePath || 'docs/superpowers' }) }}</p>
      </div>
      <div class="panel-actions">
        <button class="btn-base btn-ghost" :disabled="loadingIndex || loadingDoc" @click="loadIndex">
          <RefreshCw class="w-4 h-4" :class="{ spin: loadingIndex }" />
          <span>{{ $t('chat.superpowers_docs_refresh') }}</span>
        </button>
        <button class="btn-base btn-primary" :disabled="!canSave" @click="saveDoc">
          <Loader2 v-if="saving" class="w-4 h-4 spin" />
          <Save v-else class="w-4 h-4" />
          <span>{{ $t('chat.superpowers_docs_save') }}</span>
        </button>
      </div>
    </header>

    <div class="panel-body">
      <aside class="doc-list">
        <section class="doc-section">
          <h4>{{ $t('chat.superpowers_docs_section_plans') }}</h4>
          <template v-for="row in plansRows" :key="row.key">
            <button
              v-if="row.kind === 'dir'"
              class="doc-entry dir-entry"
              :style="rowIndentStyle(row.depth)"
              @click="toggleDir('plans', row.path)"
            >
              <ChevronRight :size="14" :stroke-width="2.5" class="dir-chevron" :class="{ expanded: row.expanded }" />
              <div class="icon-container amber">
                <Folder :size="14" :stroke-width="2.5" />
              </div>
              <span class="doc-entry-name">{{ row.name }}</span>
            </button>
            <button
              v-else
              class="doc-entry file-entry"
              :style="rowIndentStyle(row.depth)"
              :class="{ active: selectedSection === 'plans' && selectedPath === row.path }"
              @click="selectDoc(row.entry)"
            >
              <div class="doc-entry-title">
                <div class="icon-container blue">
                  <FileText :size="14" :stroke-width="2.5" />
                </div>
                <span class="doc-entry-name">{{ row.name }}</span>
              </div>
              <div class="doc-entry-meta">{{ formatFileSize(row.entry.size) }} · {{ formatDateTime(row.entry.updated_at) }}</div>
            </button>
          </template>
          <p v-if="plans.length === 0" class="doc-empty">{{ $t('chat.superpowers_docs_empty_section_plans') }}</p>
        </section>

        <section class="doc-section">
          <h4>{{ $t('chat.superpowers_docs_section_specs') }}</h4>
          <template v-for="row in specsRows" :key="row.key">
            <button
              v-if="row.kind === 'dir'"
              class="doc-entry dir-entry"
              :style="rowIndentStyle(row.depth)"
              @click="toggleDir('specs', row.path)"
            >
              <ChevronRight :size="14" :stroke-width="2.5" class="dir-chevron" :class="{ expanded: row.expanded }" />
              <div class="icon-container amber">
                <Folder :size="14" :stroke-width="2.5" />
              </div>
              <span class="doc-entry-name">{{ row.name }}</span>
            </button>
            <button
              v-else
              class="doc-entry file-entry"
              :style="rowIndentStyle(row.depth)"
              :class="{ active: selectedSection === 'specs' && selectedPath === row.path }"
              @click="selectDoc(row.entry)"
            >
              <div class="doc-entry-title">
                <div class="icon-container blue">
                  <FileText :size="14" :stroke-width="2.5" />
                </div>
                <span class="doc-entry-name">{{ row.name }}</span>
              </div>
              <div class="doc-entry-meta">{{ formatFileSize(row.entry.size) }} · {{ formatDateTime(row.entry.updated_at) }}</div>
            </button>
          </template>
          <p v-if="specs.length === 0" class="doc-empty">{{ $t('chat.superpowers_docs_empty_section_specs') }}</p>
        </section>
      </aside>

      <section class="doc-editor">
        <div v-if="loadingDoc" class="editor-state">
          <Loader2 class="w-6 h-6 spin text-primary" />
          <span>{{ $t('chat.superpowers_docs_loading') }}</span>
        </div>
        <div v-else-if="!hasDocs || !selectedDoc" class="editor-state">
          <FileText class="w-10 h-10 opacity-10 mb-2" />
          <span>{{ $t('chat.superpowers_docs_empty') }}</span>
        </div>
        <template v-else>
          <div class="editor-meta">
            <span class="path-badge">{{ selectedDoc.relative_path }}</span>
            <span v-if="isDirty" class="status-badge dirty-pill">{{ $t('chat.superpowers_docs_unsaved') }}</span>
            <span v-if="readonly" class="status-badge readonly-pill">{{ $t('chat.superpowers_docs_readonly') }}</span>
          </div>
          <textarea
            v-model="content"
            class="editor-textarea"
            :readonly="readonly"
            spellcheck="false"
            :placeholder="t('chat.superpowers_docs_placeholder')"
          />
        </template>
      </section>
    </div>

    <p v-if="loadError" class="error-text">{{ loadError }}</p>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&design=swap');

.superpowers-docs-panel {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.4);
  backdrop-filter: var(--glass-blur);
  border: 1px solid rgba(14, 165, 233, 0.1);
  border-radius: var(--radius-xl);
  overflow: hidden;
  box-shadow: var(--shadow-lg);
  font-family: var(--font-body);
}

/* ─── Header ─── */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 24px;
  border-bottom: 1px solid rgba(14, 165, 233, 0.08);
  background: rgba(255, 255, 255, 0.6);
  border-radius: 0; /* Override glass-panel radius for top header */
  z-index: 10;
}

.panel-title-group {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.panel-title-line {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--color-text-title);
  font-family: var(--font-heading);
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.panel-title-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.15), rgba(14, 165, 233, 0.05));
  color: var(--color-primary-600);
  border-radius: 8px;
  border: 1px solid rgba(14, 165, 233, 0.2);
}

.panel-subtitle {
  margin: 2px 0 0 42px; /* Align with title text after icon (32px + 10px gap) */
  color: var(--color-text-muted);
  font-size: 0.75rem;
  font-weight: 500;
  opacity: 0.8;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.panel-actions {
  display: inline-flex;
  gap: 12px;
}

.btn-base {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 16px;
  border-radius: 10px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  border: 1px solid transparent;
}

.btn-ghost {
  background: rgba(255, 255, 255, 0.8);
  color: var(--color-text-body);
  border-color: rgba(148, 163, 184, 0.15);
}

.btn-ghost:hover:not(:disabled) {
  background: #ffffff;
  color: var(--color-primary-600);
  border-color: rgba(14, 165, 233, 0.2);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
}

.btn-primary {
  background: var(--color-primary-500);
  color: white;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.15);
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-primary-600);
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(14, 165, 233, 0.25);
}

.btn-base:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none !important;
  box-shadow: none !important;
}

/* ─── Body Layout ─── */
.panel-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  background: transparent;
}

/* ─── Sidebar ─── */
.doc-list {
  border-right: 1px solid rgba(14, 165, 233, 0.08);
  overflow-y: auto;
  padding: 20px 14px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  background: rgba(248, 250, 252, 0.4);
}

.doc-section h4 {
  margin: 0 0 12px 10px;
  font-size: 0.7rem;
  font-weight: 800;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  opacity: 0.7;
}

.doc-entry {
  width: 100%;
  border: 1px solid transparent;
  border-radius: 12px;
  background: transparent;
  text-align: left;
  margin-bottom: 2px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.1s var(--transition-fast);
  position: relative;
  display: flex;
  align-items: center;
}

.doc-entry:hover {
  background: rgba(255, 255, 255, 0.8);
  border-color: rgba(14, 165, 233, 0.1);
  transform: translateX(2px);
}

.doc-entry.active {
  background: rgba(255, 255, 255, 0.95);
  border-color: rgba(14, 165, 233, 0.25);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
}

.doc-entry.active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 3px;
  background: var(--color-primary-500);
  border-radius: 0 4px 4px 0;
}

.doc-entry-name {
  color: var(--color-text-body);
  font-size: 0.875rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-entry.active .doc-entry-name {
  color: var(--color-primary-700);
}

.doc-entry-title {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.dir-entry {
  gap: 10px;
}

.icon-container {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  flex-shrink: 0;
}

.icon-container.amber {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.icon-container.blue {
  background: rgba(14, 165, 233, 0.1);
  color: #0ea5e9;
}

.dir-chevron {
  color: var(--color-text-muted);
  transition: transform 0.3s var(--transition-base);
  opacity: 0.6;
}

.dir-chevron.expanded {
  transform: rotate(90deg);
  color: var(--color-primary-500);
  opacity: 1;
}

.file-entry {
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.doc-entry-meta {
  margin-left: 34px; /* Align with title text after icon (24px + 10px gap) */
  color: var(--color-text-muted);
  font-size: 0.7rem;
  font-weight: 500;
  opacity: 0.8;
}

.doc-empty {
  margin: 10px 10px;
  font-size: 0.8125rem;
  color: var(--color-text-muted);
  font-style: italic;
  opacity: 0.7;
}

/* ─── Editor ─── */
.doc-editor {
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
}

.editor-meta {
  padding: 12px 24px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  display: flex;
  gap: 12px;
  align-items: center;
  background: rgba(248, 250, 252, 0.5);
}

.path-badge {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--color-primary-700);
  background: rgba(14, 165, 233, 0.08);
  padding: 4px 12px;
  border-radius: 8px;
  border: 1px solid rgba(14, 165, 233, 0.12);
}

.status-badge {
  border-radius: 8px;
  padding: 4px 12px;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.dirty-pill {
  color: #b45309;
  background: #fef3c7;
  border: 1px solid #fde68a;
}

.readonly-pill {
  color: var(--color-text-muted);
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
}

.editor-textarea {
  flex: 1;
  min-height: 0;
  border: none;
  outline: none;
  resize: none;
  padding: 24px;
  font-family: var(--font-mono);
  font-size: 0.9375rem;
  line-height: 1.6;
  color: var(--color-text-body);
  background: transparent;
}

.editor-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--color-text-muted);
}

.error-text {
  padding: 12px 20px;
  margin: 0;
  background: rgba(244, 63, 94, 0.08);
  color: var(--color-accent-rose);
  font-size: 0.875rem;
  font-weight: 500;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
