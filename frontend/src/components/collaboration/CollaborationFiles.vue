<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Download, GitBranch, FileText } from '@/components/icons'
import FileTypeBadge from '@/components/file-preview/FileTypeBadge.vue'
import { formatFileSize } from '@/components/file-preview/fileTypes'
import type { CollaborationReviewFile } from '@/composables/collaboration/review'

type FileItem = Pick<CollaborationReviewFile, 'key' | 'path' | 'task_repository_id' | 'kind' | 'delivered'> & { statusLabel?: string }
const props = defineProps<{
  files: FileItem[]; repositories: Array<{ task_repository_id: string; repo_slug: string; branch_name: string }>
  selected: string; checked: string[]; canRestore: boolean; localAvailable: boolean; running: boolean
  exports?: ReadonlyMap<string, { path: string; size: number }>
  exportChecked?: ReadonlySet<string>
  exporting?: boolean
}>()
const emit = defineEmits<{ select: [key: string]; check: [key: string, checked: boolean]; exportCheck: [key: string, checked: boolean]; download: [key: string] }>()
const { t } = useI18n()
const groups = computed(() => {
  const groups = new Map(props.repositories.map(repo => [repo.task_repository_id, { ...repo, files: [] as FileItem[] }]))
  for (const file of props.files) {
    if (!groups.has(file.task_repository_id)) {
      groups.set(file.task_repository_id, { task_repository_id: file.task_repository_id, repo_slug: '', branch_name: '', files: [] })
    }
    groups.get(file.task_repository_id)!.files.push(file)
  }
  return [...groups.values()].filter(repo => repo.files.length)
})
const name = (path: string) => path.split('/').at(-1)
const parent = (path: string) => path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
const displayPath = (slug: string, path: string) => slug ? `${slug}/${path}` : path

const statusLabel = (file: FileItem) => {
  if (file.statusLabel) return file.statusLabel
  if (file.kind === 'conflicts') return '待裁决'
  if (file.kind === 'local') return '本地修改'
  if (file.delivered) return '已同步'
  return 'Agent 修改'
}
</script>

<template>
  <aside class="file-navigation" :aria-label="t('collaboration.ui.changedFiles')" :class="{ 'export-enabled': exports }">
    <slot name="toolbar" />
    <div class="file-scroll custom-scrollbar">
    <section v-for="repo in groups" :key="repo.task_repository_id" class="repo-section">
      <div v-if="repo.repo_slug" class="repository-heading">
        <GitBranch :size="13" class="repo-branch-icon" />
        <strong>{{ repo.repo_slug }}</strong>
        <code :title="repo.branch_name" class="branch-pill">{{ repo.branch_name }}</code>
        <small class="repo-file-count">{{ repo.files.length }} 个文件</small>
      </div>
      <div v-for="file in repo.files" :key="file.key" class="file-row" :class="{ selected: selected === file.key, conflict: file.kind === 'conflicts' }">
        <input v-if="file.kind === 'conflicts' && canRestore" type="checkbox" :checked="checked.includes(file.key)" :aria-label="t('collaboration.ui.selectFile', { path: displayPath(repo.repo_slug, file.path) })" @change="emit('check', file.key, ($event.target as HTMLInputElement).checked)" />
        <input v-else-if="exports?.has(file.key)" type="checkbox" :checked="exportChecked?.has(file.key)" :aria-label="t('task_deliverables.select_file', { path: displayPath(repo.repo_slug, file.path) })" @change="emit('exportCheck', file.key, ($event.target as HTMLInputElement).checked)" />
        <button type="button" class="file" :aria-pressed="selected === file.key" :title="displayPath(repo.repo_slug, file.path)" @click="emit('select', file.key)">
          <FileTypeBadge v-if="exports" :path="file.path" />
          <span v-else class="file-icon-box" :class="{ conflict: file.kind === 'conflicts', local: file.kind === 'local', agent: file.kind === 'cloud' }">
            <FileText :size="13" />
          </span>
          <span class="file-name">
            <strong>{{ name(file.path) }}</strong>
            <small v-if="parent(file.path) || exports?.has(file.key)">
              {{ [parent(file.path), exports?.has(file.key) ? formatFileSize(exports.get(file.key)!.size) : ''].filter(Boolean).join(' · ') }}
            </small>
          </span>
          <span v-if="!exports || file.kind !== 'cloud' || file.delivered" class="file-status" :class="{ warning: file.kind === 'conflicts', synced: file.delivered, local: file.kind === 'local', agent: file.kind === 'cloud' }">
            {{ statusLabel(file) }}
          </span>
        </button>
        <button v-if="exports?.has(file.key)" class="file-download" type="button" :disabled="exporting" :aria-label="t('task_deliverables.download_file', { path: displayPath(repo.repo_slug, file.path) })" :title="t('task_deliverables.download_file', { path: displayPath(repo.repo_slug, file.path) })" @click="emit('download', file.key)">
          <Download :size="14" />
        </button>
      </div>
    </section>
    <slot name="empty" />
    </div>
    <slot name="footer" />
  </aside>
</template>

<style scoped>
.file-navigation {
  width: 280px;
  flex-shrink: 0;
  overflow: hidden;
  border-right: 1px solid #e2e8f0;
  padding: 12px;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.file-navigation.export-enabled { gap: 8px; }
.file-scroll { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: auto; gap: 12px; }

.repo-section {
  flex-shrink: 0;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
}

.repository-heading {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  font-size: 12px;
  color: #0f172a;
}
.repo-branch-icon {
  color: #0284c7;
  flex-shrink: 0;
}
.repository-heading strong {
  font-weight: 600;
  white-space: nowrap;
}
.branch-pill {
  font-size: 10px;
  color: #475569;
  background: #ffffff;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid #cbd5e1;
  font-family: var(--font-mono, monospace);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 125px;
}
.repo-file-count {
  margin-left: auto;
  color: #64748b;
  font-size: 11px;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-left: 3px solid transparent;
  transition: all 0.15s ease;
  position: relative;
}
.file-row:not(:last-child) {
  border-bottom: 1px solid rgba(226, 232, 240, 0.6);
}
.file-row:hover {
  background: #f8fafc;
}
.file-row.selected {
  background: #f0f9ff;
  border-left-color: #0284c7;
}
.file-row.conflict {
  background: rgba(245, 158, 11, 0.03);
}
.file-row.conflict.selected {
  background: #fffbeb;
  border-left-color: #f59e0b;
}

.file-row input {
  accent-color: #0284c7;
  flex-shrink: 0;
  cursor: pointer;
  margin-left: 2px;
}
.file-download { display: grid; place-items: center; width: 26px; height: 26px; flex: none; border: 1px solid transparent; border-radius: 5px; color: #0284c7; background: transparent; cursor: pointer; opacity: 0; transition: opacity .15s; }
.file-row:hover .file-download, .file-row:focus-within .file-download { opacity: 1; }
.file-download:hover:not(:disabled) { border-color: #bae6fd; background: #f0f9ff; }
.file-download:disabled { cursor: default; }
@media (hover: none) { .file-download { opacity: 1; } }

.file {
  display: flex;
  flex: 1;
  min-width: 0;
  gap: 8px;
  align-items: center;
  padding: 4px 0;
  border: 0;
  background: none;
  color: #334155;
  text-align: left;
  cursor: pointer;
}

.file-icon-box {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  background: #f1f5f9;
  color: #64748b;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.file-icon-box.conflict {
  background: #fef3c7;
  color: #d97706;
}
.file-icon-box.agent {
  background: #ecfdf5;
  color: #059669;
}
.file-icon-box.local {
  background: #e0f2fe;
  color: #0284c7;
}

.file-name {
  flex: 1;
  min-width: 0;
}
.file-name strong, .file-name small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-name strong {
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
}
.file-name small {
  color: #64748b;
  font-size: 10.5px;
  margin-top: 1px;
}

.file-status {
  font-size: 10.5px;
  font-weight: 500;
  white-space: nowrap;
  padding: 2px 7px;
  border-radius: 4px;
  background: #f1f5f9;
  color: #64748b;
  flex-shrink: 0;
}
.file-status.warning {
  background: #fef3c7;
  color: #b45309;
  border: 1px solid rgba(245, 158, 11, 0.3);
  font-weight: 600;
}
.file-status.synced, .file-status.agent {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #bbf7d0;
}
.file-status.local {
  background: #f0f9ff;
  color: #0284c7;
  border: 1px solid #bae6fd;
}

@media(max-width:720px) {
  .file-navigation {
    width: 100%;
    max-height: 200px;
    border-right: 0;
    border-bottom: 1px solid #e2e8f0;
  }
}
</style>
