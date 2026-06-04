<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FileText,
  GitBranch,
  Cpu,
  Shield,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
} from 'lucide-vue-next'
import TaskAssetEmptyState from './TaskAssetEmptyState.vue'
import type { TaskFileItemLight } from '@/types/workspaceAssets'

const props = defineProps<{
  files: TaskFileItemLight[]
  workspaceId: string
  taskId: string
  total?: number
  page?: number
  pageSize?: number
}>()

const { t } = useI18n()

const emit = defineEmits<{
  'page-change': [payload: { page: number; pageSize: number }]
}>()

const expandedProposals = shallowRef<Set<string>>(new Set())

const proposalItems = computed(() =>
  props.files.filter((f) => f.source_kind === 'change_proposal'),
)

const otherFiles = computed(() =>
  props.files.filter((f) => f.source_kind !== 'change_proposal'),
)

function toggleProposal(id: string) {
  const next = new Set(expandedProposals.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedProposals.value = next
}

function handleCurrentChange(newPage: number) {
  emit('page-change', { page: newPage, pageSize: props.pageSize || 10 })
}

function handleSizeChange(newSize: number) {
  emit('page-change', { page: 1, pageSize: newSize })
}

function fileIcon(kind: string) {
  if (kind === 'asset') return FileText
  if (kind === 'ai_output') return Cpu
  if (kind === 'change_proposal') return GitBranch
  if (kind === 'superpowers_doc') return FileText
  if (kind === 'verification_run') return Shield
  if (kind === 'conflict_report') return AlertTriangle
  return FileText
}
</script>

<template>
  <section class="panel-shell">
    <header class="panel-head">
      <div>
        <span class="eyebrow">{{ t('workspace_assets.task_detail.workbench.task_file.eyebrow') }}</span>
        <h2>{{ t('workspace_assets.task_detail.workbench.task_file.title') }}</h2>
      </div>
    </header>

    <div v-if="proposalItems.length || otherFiles.length" class="file-groups">
      <!-- Change Proposals -->
      <div v-for="item in proposalItems" :key="item.id" class="proposal-group">
        <button
          type="button"
          class="proposal-header"
          @click="toggleProposal(item.id)"
        >
          <component :is="expandedProposals.has(item.id) ? ChevronDown : ChevronRight" :size="16" />
          <GitBranch :size="16" class="icon-branch" />
          <span class="proposal-title">{{ item.title }}</span>
          <el-tag effect="plain" size="small">{{ item.status }}</el-tag>
        </button>

        <div v-if="expandedProposals.has(item.id)" class="proposal-files">
          <p v-if="item.summary" class="proposal-summary">{{ item.summary }}</p>
        </div>
      </div>

      <!-- Other Files -->
      <div v-for="file in otherFiles" :key="file.id" class="other-file-card">
        <div class="other-file-icon">
          <component :is="fileIcon(file.source_kind)" :size="16" />
        </div>
        <div class="other-file-info">
          <strong>{{ file.title }}</strong>
          <div class="other-file-meta">
            <el-tag effect="plain" size="small">{{ file.file_type }}</el-tag>
            <span v-if="file.source_kind" class="source-kind">{{ file.source_kind }}</span>
            <el-tag v-if="file.status" effect="plain" size="small">{{ file.status }}</el-tag>
          </div>
          <p v-if="file.summary" class="other-file-summary">{{ file.summary }}</p>
        </div>
      </div>
    </div>

    <TaskAssetEmptyState
      v-else
      :title="t('workspace_assets.task_detail.workbench.task_file.empty_title')"
      :message="t('workspace_assets.task_detail.workbench.task_file.empty')"
      :boundary="t('workspace_assets.task_detail.no_auto_commit')"
    />
    <el-pagination
      v-if="(props.total ?? 0) > 0"
      class="section-pagination"
      :current-page="props.page || 1"
      :page-size="props.pageSize || 10"
      :total="props.total || 0"
      :page-sizes="[10, 20, 50]"
      layout="total, sizes, prev, pager, next, jumper"
      :total-text="t('workspace_assets.task_detail.workbench.pagination.total', { total: props.total || 0 })"
      :page-size-text="t('workspace_assets.task_detail.workbench.pagination.page_size')"
      @current-change="handleCurrentChange"
      @size-change="handleSizeChange"
    />
  </section>
</template>

<style scoped>
.panel-shell {
  display: grid;
  gap: 14px;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding-bottom: 14px;
  border-bottom: 1px solid #e2e8f0;
}

.eyebrow {
  color: #2563eb;
  font-size: 0.75rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.panel-head h2 {
  margin: 5px 0 0;
  color: #0f172a;
  font-family: 'Poppins', sans-serif;
  font-size: 1.5rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.panel-head p {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 0.95rem;
  line-height: 1.6;
}

.file-groups {
  display: grid;
  gap: 12px;
}

.proposal-group {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}

.proposal-header {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 12px 14px;
  background: #f8fafc;
  border: none;
  cursor: pointer;
  font-size: 0.875rem;
  text-align: left;
  transition: background 0.15s;
}

.proposal-header:hover {
  background: #f1f5f9;
}

.icon-branch {
  color: #6366f1;
}

.proposal-title {
  font-weight: 600;
  color: #1e293b;
  flex: 1;
}

.proposal-files {
  padding: 8px 14px 14px;
  display: grid;
  gap: 6px;
}

.proposal-summary {
  margin: 0;
  color: #64748b;
  font-size: 0.8125rem;
  line-height: 1.5;
}

.other-file-card {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: white;
}

.other-file-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  background: #f1f5f9;
  border-radius: 8px;
  color: #64748b;
  flex-shrink: 0;
}

.other-file-info {
  flex: 1;
  min-width: 0;
}

.other-file-info strong {
  display: block;
  font-size: 0.875rem;
  color: #1e293b;
  margin-bottom: 4px;
}

.other-file-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.source-kind {
  color: #94a3b8;
  font-size: 0.75rem;
}

.other-file-summary {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 0.8125rem;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.section-pagination {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
