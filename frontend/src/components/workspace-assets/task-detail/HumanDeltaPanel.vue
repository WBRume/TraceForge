<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import TaskAssetEmptyState from './TaskAssetEmptyState.vue'
import { useTaskDetailAssets } from '@/composables/useTaskDetailAssets'
import type { HumanDeltaLight, HumanDeltaSuggestion } from '@/types/workspaceAssets'

const props = defineProps<{
  deltas: HumanDeltaLight[]
  workspaceId: string
  taskId: string
  total?: number
  page?: number
  pageSize?: number
}>()

const emit = defineEmits<{
  mutated: []
  'page-change': [payload: { page: number; pageSize: number }]
}>()

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const taskAssets = useTaskDetailAssets()

const wsId = computed(() => String(route.params.wsId || ''))

const suggestions = ref<HumanDeltaSuggestion[]>([])
const suggestionsLoading = ref(false)

async function loadSuggestions() {
  suggestionsLoading.value = true
  try {
    const result = await taskAssets.suggestDeltas(props.workspaceId, props.taskId)
    suggestions.value = result?.items ?? []
  } finally {
    suggestionsLoading.value = false
  }
}

async function generateDelta(suggestion: HumanDeltaSuggestion) {
  const result = await taskAssets.createHumanDelta(props.workspaceId, props.taskId, {
    proposal_id: suggestion.proposal.id,
    final_evidence_id: suggestion.evidence.id,
  })
  if (!result) return

  emit('mutated')
  await loadSuggestions()

  // Auto-open detail for the newly created delta after parent refreshes the list
  await nextTick()
  const newDelta = props.deltas.find(
    d => d.proposal_id === suggestion.proposal.id && d.final_evidence_id === suggestion.evidence.id,
  )
  if (newDelta) {
    navigateToDelta(newDelta.id)
  }
}

async function retryCompare(deltaId: string) {
  const result = await taskAssets.compareDelta(props.workspaceId, props.taskId, deltaId)
  if (!result) return
  emit('mutated')
  navigateToDelta(deltaId)
}

function navigateToDelta(deltaId: string) {
  router.push(`/ws/${wsId.value}/assets/tasks/${props.taskId}/deltas/${deltaId}/workbench`)
}

function statusTagType(status: string): string {
  if (status === 'READY') return 'success'
  if (status === 'COMPARING') return 'warning'
  if (status === 'SUPERSEDED') return 'info'
  return 'info'
}

function diffStats(delta: HumanDeltaLight): string {
  const files = delta.changed_files_count ?? 0
  const ins = delta.insertions ?? 0
  const del = delta.deletions ?? 0
  return t('workspace_assets.task_detail.workbench.human_delta.diff_stats', { files, ins, del })
}

function handleCurrentChange(newPage: number) {
  emit('page-change', { page: newPage, pageSize: props.pageSize || 10 })
}

function handleSizeChange(newSize: number) {
  emit('page-change', { page: 1, pageSize: newSize })
}

onMounted(loadSuggestions)
</script>

<template>
  <section class="panel-shell">
    <header class="panel-head">
      <div class="head-text">
        <span class="eyebrow">{{ t('workspace_assets.task_detail.workbench.human_delta.eyebrow') }}</span>
        <h3>{{ t('workspace_assets.task_detail.workbench.human_delta.title') }}</h3>
        <p>{{ t('workspace_assets.task_detail.workbench.human_delta.description') }}</p>
      </div>
    </header>

    <el-alert
      :title="t('workspace_assets.task_detail.workbench.human_delta.boundary')"
      type="info"
      :closable="false"
      show-icon
      class="boundary-alert"
    />

    <!-- Suggestions -->
    <div v-if="suggestionsLoading" class="suggestions-loading">
      <el-skeleton :rows="2" animated />
    </div>
    <div v-else-if="suggestions.length" class="suggestions-section">
      <h4 class="section-title">{{ t('workspace_assets.task_detail.workbench.human_delta.suggest_title') }}</h4>
      <div class="suggestion-list">
        <article
          v-for="(s, idx) in suggestions"
          :key="idx"
          class="suggestion-card"
        >
          <div class="suggestion-proposal">
            <div class="card-label">{{ t('workspace_assets.task_detail.workbench.human_delta.ai_patch') }}</div>
            <div class="card-title">Proposal #{{ s.proposal.proposal_no }} / PS{{ s.proposal.patch_set_no }}</div>
            <div class="card-meta">{{ s.proposal.base_branch }} &middot; {{ s.proposal.changed_files_count }} files, +{{ s.proposal.insertions }} / -{{ s.proposal.deletions }}</div>
          </div>
          <div class="suggestion-arrow">&rarr;</div>
          <div class="suggestion-evidence">
            <div class="card-label">{{ t('workspace_assets.task_detail.workbench.human_delta.final_patch') }}</div>
            <div class="card-title">{{ s.evidence.source_type }}: {{ s.evidence.source_ref || s.evidence.source_uri || '-' }}</div>
            <div class="card-meta">{{ s.evidence.title || '-' }}</div>
          </div>
          <div class="suggestion-action">
            <el-button
              type="primary"
              size="small"
              :loading="taskAssets.saving.value"
              @click="generateDelta(s)"
            >
              {{ t('workspace_assets.task_detail.workbench.human_delta.generate_delta') }}
            </el-button>
          </div>
        </article>
      </div>
    </div>

    <!-- Existing Deltas -->
    <div v-if="!deltas.length && !suggestions.length && !suggestionsLoading" class="empty-state">
      <TaskAssetEmptyState
        :title="t('workspace_assets.task_detail.workbench.human_delta.empty_title')"
        :message="t('workspace_assets.task_detail.workbench.human_delta.empty')"
      >
        <template #action>
          <el-button size="small" @click="loadSuggestions">
            {{ t('workspace_assets.task_detail.workbench.human_delta.suggest_title') }}
          </el-button>
        </template>
      </TaskAssetEmptyState>
    </div>
    <div v-else-if="deltas.length" class="delta-list">
      <h4 class="section-title">{{ t('workspace_assets.task_detail.workbench.human_delta.existing_title') }}</h4>
      <article
        v-for="delta in deltas"
        :key="delta.id"
        class="delta-card"
        @click="navigateToDelta(delta.id)"
      >
        <div class="delta-header">
          <el-tag :type="statusTagType(delta.status)" size="small">{{ delta.status }}</el-tag>
          <span v-if="delta.changed_files_count != null" class="delta-stats">{{ diffStats(delta) }}</span>
          <span v-if="delta.decision_count" class="delta-decisions">{{ delta.decision_count }} decisions</span>
        </div>
        <div class="delta-body">
          <div v-if="delta.proposal_summary" class="delta-source">
            <span class="source-label">{{ t('workspace_assets.task_detail.workbench.human_delta.ai_patch') }}:</span>
            Proposal #{{ delta.proposal_summary.proposal_no }} / PS{{ delta.proposal_summary.patch_set_no }}
          </div>
          <div v-if="delta.final_evidence_summary" class="delta-source">
            <span class="source-label">{{ t('workspace_assets.task_detail.workbench.human_delta.final_patch') }}:</span>
            {{ delta.final_evidence_summary.source_type }}: {{ delta.final_evidence_summary.source_ref || delta.final_evidence_summary.source_uri || '-' }}
          </div>
          <div v-if="delta.change_category" class="delta-category">{{ delta.change_category }}</div>
        </div>
        <div class="delta-actions" @click.stop>
          <el-button
            v-if="delta.status === 'PENDING'"
            size="small"
            :loading="taskAssets.saving.value"
            @click="retryCompare(delta.id)"
          >
            {{ t('workspace_assets.task_detail.workbench.human_delta.retry') }}
          </el-button>
        </div>
      </article>
    </div>
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
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.head-text .eyebrow {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-primary-700, #1e3a8a);
  font-weight: 600;
}

.head-text h3 {
  margin: 4px 0 0;
  font-family: 'Poppins', sans-serif;
  font-size: 1.125rem;
  color: #1e3a8a;
}

.head-text p {
  margin: 4px 0 0;
  font-size: 0.8125rem;
  color: #475569;
}

.boundary-alert {
  font-size: 0.8125rem;
}

.section-title {
  margin: 0 0 8px;
  font-family: 'Poppins', sans-serif;
  font-size: 0.875rem;
  font-weight: 600;
  color: #334155;
}

.suggestion-list {
  display: grid;
  gap: 10px;
}

.suggestion-card {
  display: grid;
  grid-template-columns: 1fr auto 1fr auto;
  gap: 12px;
  align-items: center;
  padding: 12px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.card-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #64748b;
  margin-bottom: 2px;
}

.card-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #1e293b;
}

.card-meta {
  font-size: 0.75rem;
  color: #64748b;
  margin-top: 2px;
}

.suggestion-arrow {
  font-size: 1.25rem;
  color: #94a3b8;
}

.suggestion-action {
  display: flex;
  align-items: center;
}

.delta-list {
  display: grid;
  gap: 10px;
}

.delta-card {
  padding: 12px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.delta-card:hover {
  border-color: var(--color-primary-700, #1e3a8a);
  box-shadow: 0 1px 4px rgba(30, 58, 138, 0.08);
}

.delta-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.delta-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.delta-stats {
  font-size: 0.75rem;
  color: #64748b;
  font-family: var(--font-mono, monospace);
}

.delta-decisions {
  font-size: 0.75rem;
  color: #64748b;
  margin-left: auto;
}

.delta-body {
  display: grid;
  gap: 4px;
}

.delta-source {
  font-size: 0.8125rem;
  color: #334155;
}

.source-label {
  color: #64748b;
  font-size: 0.75rem;
}

.delta-category {
  font-size: 0.75rem;
  color: #64748b;
  margin-top: 2px;
}

.empty-state {
  padding: 2rem 0;
}

.suggestions-loading {
  padding: 1rem 0;
}

.section-pagination {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
