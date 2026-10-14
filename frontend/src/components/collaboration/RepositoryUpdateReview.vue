<script setup lang="ts">
import { computed } from 'vue'
import CollaborationFiles from './CollaborationFiles.vue'
import RepositoryUpdateFile from './RepositoryUpdateFile.vue'
import type { UpdatePlan, UpdateFileDetail } from '@/services/repositoryUpdates'

const props = defineProps<{ plan: UpdatePlan; selected: string; detail: UpdateFileDetail | null; busy: boolean; loading: boolean; editable: boolean; drafts: Record<string, { text: string; version: number }> }>()
const emit = defineEmits<{ select: [key: string]; resolve: [choice: string, text?: string, version?: number]; draft: [key: string, value: { text: string; version: number } | null] }>()
const repos = computed(() => props.plan.repositories.map(repo => ({ task_repository_id:repo.id, repo_slug:repo.name, branch_name:repo.branch })))
const files = computed(() => props.plan.repositories.flatMap(repo => repo.files.map(file => ({
  ...file, key:`${repo.id}:${file.path}`, task_repository_id:repo.id, kind:file.conflict ? 'conflicts' : 'cloud', delivered:file.resolved,
  statusLabel:file.conflict ? '冲突' : file.resolved ? '已确认' : '自动整合',
}))))
const activeRepo = computed(() => props.plan.repositories.find(repo => repo.files.some(file => `${repo.id}:${file.path}` === props.selected)))
</script>

<template>
  <div class="review-body">
    <CollaborationFiles :files="files" :repositories="repos" :selected="selected" :checked="[]" :can-restore="false" :local-available="false" :running="false" @select="emit('select', $event)" />
    <RepositoryUpdateFile v-if="detail" :key="`${plan.id}:${selected}`" :saved-draft="drafts[selected]" :path="`${activeRepo?.name}/${detail.path}`" :detail="detail" :busy="busy || loading" :editable="editable" @draft="emit('draft', selected, $event)" @resolve="(choice, text, version) => emit('resolve', choice, text, version)" />
    <p v-else class="editor-empty">{{ loading ? '正在读取文件差异…' : '选择文件查看差异' }}</p>
  </div>
</template>

<style scoped>
.review-body { display:flex; flex:1; min-height:280px; min-width:0; overflow:hidden; }
.editor-empty { flex:1; margin:auto; text-align:center; color:#64748b; font-size:12px; }
@media (max-width:720px) { .review-body { flex-direction:column; } .review-body :deep(.file-navigation) { width:100%; box-sizing:border-box; max-height:180px; } }
</style>
