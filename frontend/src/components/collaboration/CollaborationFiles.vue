<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CollaborationReviewFile } from '@/composables/collaboration/review'
const props = defineProps<{
  files: CollaborationReviewFile[]; repositories: Array<{ task_repository_id: string; repo_slug: string; branch_name: string }>
  selected: string; checked: string[]; canRestore: boolean; localAvailable: boolean; running: boolean
}>()
const emit = defineEmits<{ select: [key: string]; check: [key: string, checked: boolean] }>()
const { t } = useI18n()
const groups = computed(() => props.repositories.map(repo => ({ ...repo, files: props.files.filter(file => file.task_repository_id === repo.task_repository_id) })).filter(repo => repo.files.length))
const name = (path: string) => path.split('/').at(-1)
const parent = (path: string) => path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
const status = (file: CollaborationReviewFile) => file.kind === 'conflicts' ? props.running ? 'previewConflict' : 'pending'
  : file.kind === 'local' ? 'pendingSend' : !props.localAvailable ? 'agent' : file.delivered ? 'received' : 'pendingReceive'
</script>

<template>
  <aside class="file-navigation" :aria-label="t('collaboration.ui.changedFiles')">
    <section v-for="repo in groups" :key="repo.task_repository_id">
      <div class="repository-heading"><strong>{{ repo.repo_slug }}</strong><code :title="repo.branch_name">{{ repo.branch_name }}</code><small>{{ repo.files.length }}</small></div>
      <div v-for="file in repo.files" :key="file.key" class="file-row" :class="{ selected: selected === file.key }">
        <input v-if="file.kind === 'conflicts' && canRestore" type="checkbox" :checked="checked.includes(file.key)" :aria-label="t('collaboration.ui.selectFile', { path: `${repo.repo_slug}/${file.path}` })" @change="emit('check', file.key, ($event.target as HTMLInputElement).checked)" />
        <button type="button" class="file" :aria-pressed="selected === file.key" :title="`${repo.repo_slug}/${file.path}`" @click="emit('select', file.key)">
          <span class="change" :class="{ warning: file.kind === 'conflicts' }">{{ file.kind === 'conflicts' ? '!' : file.change }}</span>
          <span class="file-name"><strong>{{ name(file.path) }}</strong><small v-if="parent(file.path)">{{ parent(file.path) }}</small></span>
          <span class="file-status" :class="{ warning: file.kind === 'conflicts' }">{{ t(`collaboration.ui.${status(file)}`) }}</span>
        </button>
      </div>
    </section>
  </aside>
</template>

<style scoped>
.file-navigation { width: 240px; flex-shrink: 0; overflow: auto; border-right: 1px solid #e5eaf0; padding: 8px 0; }.repository-heading { display: flex; align-items: center; gap: 8px; padding: 12px 14px 7px; font-size: 12px; }.repository-heading code { font-size: 10px; color: var(--color-text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.repository-heading strong { flex-shrink: 0; }.repository-heading small { margin-left: auto; color: var(--color-text-muted); }
.file-row { display: flex; align-items: center; gap: 6px; padding: 0 10px; border-left: 2px solid transparent; }.file-row.selected { background: var(--color-primary-50); border-left-color: var(--color-primary-600); }.file-row input { accent-color: var(--color-primary-600); flex-shrink: 0; }.file { display: flex; flex: 1; min-width: 0; gap: 8px; align-items: center; padding: 10px 0; border: 0; background: none; color: var(--color-text-body); text-align: left; cursor: pointer; }.change { color: var(--color-text-muted); font: 11px monospace; }.file-name { flex: 1; min-width: 0; }.file-name strong, .file-name small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.file-name strong { font-size: 12px; font-weight: 500; }.file-name small { color: var(--color-text-muted); font-size: 10px; }.file-status { font-size: 10px; white-space: nowrap; color: var(--color-text-muted); }.warning { color: #a66a12; }
@media(max-width:720px) { .file-navigation { width: 100%; max-height: 180px; border-right: 0; border-bottom: 1px solid #e5eaf0; }.repository-heading { padding-top: 6px; }.file { padding: 7px 0; } }
</style>
