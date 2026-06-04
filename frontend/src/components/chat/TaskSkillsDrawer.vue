<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { Activity, File, Folder, FolderTree, RefreshCw, Save, X } from 'lucide-vue-next'
import { VueMonacoEditor } from '@guolao/vue-monaco-editor'
import AppSideDrawer from '@/components/AppSideDrawer.vue'
import SkillRuntimeTracePanel from '@/components/chat/SkillRuntimeTracePanel.vue'
import { ensureMonacoViteSetup } from '@/utils/monaco'
import { resolveSkillFileLanguage } from '@/utils/skillLanguage'
import type { SkillRuntimeEvent } from '@/types/runtimeSkillTrace'

type RuntimeSkillUsage = {
  is_used?: boolean
  used_count?: number
  last_used_at?: string | null
}

type RuntimeSkillItem = {
  skill_id: string
  name: string
  description?: string | null
  dimension: string
  publish_state?: string
  has_pending_changes?: boolean
  changed_files_count?: number
  materialized_dir?: string | null
  is_materialized?: boolean
  usage?: RuntimeSkillUsage
}

type RuntimeFileNode = {
  path: string
  name: string
  node_type: 'file' | 'directory'
  size?: number | null
  children?: RuntimeFileNode[]
}

type RuntimeFileRow = {
  path: string
  name: string
  node_type: 'file' | 'directory'
  depth: number
}

const props = defineProps<{
  show: boolean
  loading: boolean
  skills: RuntimeSkillItem[]
  selectedSkillId: string
  canEdit: boolean
  fileTree: RuntimeFileNode[]
  fileTreeLoading: boolean
  activeFilePath: string
  activeFileContent: string
  activeFileLoading: boolean
  activeFileSaving: boolean
  activeFileBinary: boolean
  activeFileDirty: boolean
  traceEvents: SkillRuntimeEvent[]
  traceLoading: boolean
}>()

const emit = defineEmits<{
  close: []
  refreshSkills: []
  selectSkill: [skillId: string]
  refreshTree: []
  selectFile: [path: string]
  saveFile: []
  updateFileContent: [value: string]
  refreshTrace: []
}>()

const selectedSkill = computed(() => (
  props.skills.find((item) => item.skill_id === props.selectedSkillId) || null
))

const showTraceInspector = shallowRef(false)
const traceEventCount = computed(() => props.traceEvents.length)

ensureMonacoViteSetup()

const activeFileLanguage = computed(() => resolveSkillFileLanguage(props.activeFilePath))

const editorOptions = computed(() => ({
  readOnly: !props.canEdit,
  fontSize: 13,
  minimap: { enabled: false },
  wordWrap: 'on',
  scrollBeyondLastLine: false,
  automaticLayout: true,
  lineNumbers: 'on',
  renderValidationDecorations: 'on',
  tabSize: 2,
  insertSpaces: true,
}))

const flattenedFileRows = computed<RuntimeFileRow[]>(() => {
  const rows: RuntimeFileRow[] = []
  const walk = (nodes: RuntimeFileNode[], depth: number) => {
    for (const node of nodes) {
      rows.push({
        path: node.path,
        name: node.name,
        node_type: node.node_type,
        depth,
      })
      if (node.node_type === 'directory') {
        walk(Array.isArray(node.children) ? node.children : [], depth + 1)
      }
    }
  }
  walk(props.fileTree || [], 0)
  return rows
})

const onEditorInput = (value: string | undefined) => {
  emit('updateFileContent', String(value ?? ''))
}

const openTraceInspector = () => {
  showTraceInspector.value = true
}

const closeTraceInspector = () => {
  showTraceInspector.value = false
}
</script>

<template>
  <AppSideDrawer
    :show="show"
    :title="$t('chat.task_skills_drawer_title')"
    width="min(1180px, 94vw)"
    @close="emit('close')"
  >
    <template #icon>
      <FolderTree class="w-4 h-4" />
    </template>
    <template #actions>
      <button
        type="button"
        class="trace-trigger"
        :class="{ active: showTraceInspector }"
        :title="'使用证据链 / Runtime Evidence Trace'"
        @click="openTraceInspector"
      >
        <Activity class="w-4 h-4" />
        <span>Trace</span>
        <span v-if="traceEventCount > 0" class="trace-count">{{ traceEventCount }}</span>
      </button>
      <button type="button" class="icon-btn" :disabled="loading" @click="emit('refreshSkills')">
        <RefreshCw class="w-4 h-4" />
      </button>
    </template>

    <div class="drawer-body">
      <section class="skills-panel">
        <div class="panel-title">{{ $t('chat.task_skills_selected') }}</div>
        <div v-if="loading" class="panel-state">{{ $t('common.loading') }}</div>
        <div v-else-if="skills.length === 0" class="panel-state">{{ $t('chat.task_skills_empty') }}</div>
        <div v-else class="skills-list">
          <button
            v-for="skill in skills"
            :key="skill.skill_id"
            type="button"
            class="skill-item"
            :class="{ active: skill.skill_id === selectedSkillId }"
            @click="emit('selectSkill', skill.skill_id)"
          >
            <div class="skill-main">
              <div class="skill-name">{{ skill.name }}</div>
              <div class="skill-tags">
                <span class="tag">{{ skill.dimension }}</span>
                <span class="tag" :class="{ draft: skill.publish_state === 'DRAFT' }">
                  {{ skill.publish_state === 'DRAFT' ? $t('skills.task_panel.status_draft') : $t('skills.task_panel.status_published') }}
                </span>
                <span v-if="skill.usage?.is_used" class="tag used">
                  {{ $t('chat.task_skills_used_tag', { count: skill.usage?.used_count || 0 }) }}
                </span>
              </div>
            </div>
            <div v-if="skill.materialized_dir" class="skill-path">{{ skill.materialized_dir }}</div>
          </button>
        </div>
      </section>

      <section class="file-browser-panel">
        <div class="panel-title with-action">
          <span>{{ $t('chat.task_skills_file_tree') }}</span>
          <button type="button" class="btn-micro" :disabled="fileTreeLoading || !selectedSkillId" @click="emit('refreshTree')">
            <RefreshCw class="w-3 h-3" />
            {{ $t('chat.superpowers_docs_refresh') }}
          </button>
        </div>
        <div v-if="fileTreeLoading" class="panel-state">{{ $t('common.loading') }}</div>
        <div v-else-if="flattenedFileRows.length === 0" class="panel-state">
          {{ selectedSkill ? $t('chat.task_skills_tree_empty') : $t('chat.task_skills_select_skill_hint') }}
        </div>
        <div v-else class="file-tree">
          <button
            v-for="row in flattenedFileRows"
            :key="row.path"
            type="button"
            class="tree-item"
            :class="{
              file: row.node_type === 'file',
              active: row.path === activeFilePath,
            }"
            :style="{ paddingLeft: `${12 + row.depth * 14}px` }"
            @click="row.node_type === 'file' ? emit('selectFile', row.path) : undefined"
          >
            <Folder v-if="row.node_type === 'directory'" :size="12" />
            <File v-else :size="12" />
            <span>{{ row.name }}</span>
          </button>
        </div>
      </section>

      <section class="editor-panel">
        <div class="editor-workspace">
          <div class="editor-header">
            <div class="editor-path">
              {{ activeFilePath || $t('chat.task_skills_select_file_hint') }}
            </div>
            <button
              type="button"
              class="btn-primary"
              :disabled="!canEdit || activeFileSaving || activeFileLoading || activeFileBinary || !activeFileDirty || !activeFilePath"
              @click="emit('saveFile')"
            >
              <Save class="w-4 h-4" />
              {{ activeFileSaving ? $t('common.loading') : $t('common.save') }}
            </button>
          </div>
          <div v-if="activeFileLoading" class="editor-state">{{ $t('common.loading') }}</div>
          <div v-else-if="!activeFilePath" class="editor-state">{{ $t('chat.task_skills_select_file_hint') }}</div>
          <div v-else-if="activeFileBinary" class="editor-state">{{ $t('chat.task_skills_binary_readonly') }}</div>
          <VueMonacoEditor
            v-else
            class="editor-monaco"
            :value="activeFileContent"
            :language="activeFileLanguage"
            theme="vs"
            width="100%"
            height="100%"
            :options="editorOptions"
            @update:value="onEditorInput"
          />
        </div>
      </section>

      <Transition name="trace-inspector-motion">
        <div v-if="showTraceInspector" class="trace-inspector-layer" @click.self="closeTraceInspector">
          <aside class="trace-inspector" aria-label="Runtime Evidence Trace">
            <header class="trace-inspector-header">
              <div class="trace-inspector-title">
                <Activity class="w-4 h-4" />
                <span>使用证据链 / Runtime Evidence Trace</span>
              </div>
              <button
                type="button"
                class="icon-btn"
                :title="$t('common.close')"
                @click="closeTraceInspector"
              >
                <X class="w-4 h-4" />
              </button>
            </header>
            <SkillRuntimeTracePanel
              class="trace-inspector-panel"
              :skills="skills"
              :selected-skill-id="selectedSkillId"
              :events="traceEvents"
              :loading="traceLoading"
              @refresh="emit('refreshTrace')"
            />
          </aside>
        </div>
      </Transition>
    </div>
  </AppSideDrawer>
</template>

<style scoped>
.w-3 {
  width: 12px;
  height: 12px;
}

.w-4 {
  width: 16px;
  height: 16px;
}

.icon-btn {
  background: transparent;
  border: 1px solid rgba(148, 163, 184, 0.35);
  color: #475569;
  border-radius: 8px;
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--color-primary-500);
  color: #ffffff;
  border: none;
  border-radius: 8px;
  padding: 6px 12px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  cursor: pointer;
}

.btn-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-micro {
  background: #ffffff;
  color: #475569;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 8px;
  padding: 4px 8px;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.btn-micro:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.trace-trigger {
  position: relative;
  height: 30px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 8px;
  background: #ffffff;
  color: #475569;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.trace-trigger:hover,
.trace-trigger.active {
  border-color: rgba(14, 165, 233, 0.35);
  color: var(--color-primary-700);
  background: var(--color-primary-50);
}

.trace-count {
  min-width: 16px;
  height: 16px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--color-primary-500);
  color: #ffffff;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
}

.drawer-body {
  position: relative;
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(220px, 260px) minmax(220px, 280px) minmax(0, 1fr);
  min-width: 0;
  overflow: hidden;
}

.skills-panel {
  border-right: 1px solid rgba(15, 23, 42, 0.08);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.file-browser-panel {
  border-right: 1px solid rgba(15, 23, 42, 0.08);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.panel-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.panel-title.with-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-state {
  font-size: 12px;
  color: var(--color-text-muted);
  padding: 8px 2px;
}

.skills-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  overflow: auto;
  padding-right: 2px;
}

.skill-item {
  width: 100%;
  text-align: left;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 10px;
  padding: 10px;
  background: #fff;
  cursor: pointer;
}

.skill-item.active {
  border-color: var(--color-primary-400);
  background: var(--color-primary-50);
}

.skill-main {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.skill-name {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}

.skill-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.tag {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  color: #64748b;
  background: #f8fafc;
}

.tag.draft {
  border-color: rgba(245, 158, 11, 0.45);
  color: #b45309;
  background: #fffbeb;
}

.tag.used {
  border-color: rgba(34, 197, 94, 0.4);
  color: #166534;
  background: #f0fdf4;
}

.skill-path {
  margin-top: 8px;
  font-size: 11px;
  color: #94a3b8;
  word-break: break-all;
}

.file-tree {
  flex: 1;
  min-height: 0;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 10px;
  overflow: auto;
}

.tree-item {
  width: 100%;
  border: none;
  border-bottom: 1px solid rgba(226, 232, 240, 0.8);
  background: #fff;
  text-align: left;
  padding: 8px 12px;
  font-size: 12px;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: default;
}

.tree-item.file {
  cursor: pointer;
}

.tree-item.file:hover {
  background: #f8fafc;
}

.tree-item.active {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
}

.tree-item:last-child {
  border-bottom: none;
}

.editor-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.editor-workspace {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.editor-header {
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.editor-path {
  font-size: 12px;
  color: #475569;
  word-break: break-all;
}

.editor-state {
  margin: auto;
  font-size: 13px;
  color: #64748b;
}

.editor-monaco {
  flex: 1;
  min-height: 0;
}

.trace-inspector-layer {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: flex;
  justify-content: flex-end;
  background: rgba(15, 23, 42, 0.08);
}

.trace-inspector {
  width: min(430px, calc(100% - 28px));
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  border-left: 1px solid rgba(15, 23, 42, 0.12);
  background: #ffffff;
  box-shadow: -16px 0 40px rgba(15, 23, 42, 0.16);
}

.trace-inspector-header {
  flex: 0 0 auto;
  min-height: 48px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}

.trace-inspector-title {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
}

.trace-inspector-title span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.trace-inspector-panel) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  border: none;
  border-radius: 0;
  background: #ffffff;
}

:deep(.trace-inspector-panel .trace-timeline) {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-right: 2px;
}

.trace-inspector-motion-enter-active,
.trace-inspector-motion-leave-active {
  transition: opacity 0.16s ease;
}

.trace-inspector-motion-enter-active .trace-inspector,
.trace-inspector-motion-leave-active .trace-inspector {
  transition: transform 0.18s ease;
}

.trace-inspector-motion-enter-from,
.trace-inspector-motion-leave-to {
  opacity: 0;
}

.trace-inspector-motion-enter-from .trace-inspector,
.trace-inspector-motion-leave-to .trace-inspector {
  transform: translateX(24px);
}

@media (max-width: 1200px) {
  .drawer-body {
    grid-template-columns: minmax(200px, 240px) minmax(200px, 250px) minmax(0, 1fr);
  }
}

@media (max-width: 920px) {
  .drawer-body {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(120px, 24%) minmax(160px, 28%) minmax(0, 1fr);
  }

  .skills-panel,
  .file-browser-panel {
    border-right: none;
    border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  }
}
</style>
