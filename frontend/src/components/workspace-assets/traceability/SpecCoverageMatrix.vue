<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { FileText, GitBranch } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import type {
  SpecCoverageMatrixCoverageStatus,
  SpecCoverageMatrixRow,
} from '@/types/workspaceAssets'

const props = defineProps<{
  rows: SpecCoverageMatrixRow[]
  workspaceId: string
}>()

const { t } = useI18n()

const statusOrder: SpecCoverageMatrixCoverageStatus[] = [
  'missing',
  'spec_covered',
  'in_progress',
  'human_modified',
  'evidence_missing',
  'need_clarification',
  'rejected',
  'verified',
]

const columns = computed(() => [
  t('workspace_assets.traceability.matrix.columns.requirement'),
  t('workspace_assets.traceability.matrix.columns.related_task'),
  t('workspace_assets.traceability.matrix.columns.spec_status'),
  t('workspace_assets.traceability.matrix.columns.plan_status'),
  t('workspace_assets.traceability.matrix.columns.ai_run_status'),
  t('workspace_assets.traceability.matrix.columns.human_review_status'),
  t('workspace_assets.traceability.matrix.columns.human_delta_status'),
  t('workspace_assets.traceability.matrix.columns.evidence_status'),
  t('workspace_assets.traceability.matrix.columns.coverage_status'),
  t('workspace_assets.traceability.matrix.columns.drill_down'),
])

const statusLegend = computed(() => statusOrder.map((status) => ({
  status,
  label: t(`workspace_assets.traceability.matrix.status.${status}`),
  description: t(`workspace_assets.traceability.matrix.status_detail.${status}`),
})))

function requirementTo(requirementId: string) {
  return { name: 'workspaceAssetsRequirementDetail', params: { wsId: props.workspaceId, requirementId } }
}

function taskTo(taskId: string) {
  return `/ws/${props.workspaceId}/assets/tasks/${encodeURIComponent(taskId)}`
}

function statusLabel(status: string) {
  return t(`workspace_assets.traceability.matrix.asset_status.${status}`)
}
</script>

<template>
  <section class="matrix-shell" :aria-label="t('workspace_assets.traceability.matrix.title')">
    <div class="matrix-intro">
      <div>
        <span class="matrix-eyebrow">{{ t('workspace_assets.traceability.matrix.eyebrow') }}</span>
        <h4>{{ t('workspace_assets.traceability.matrix.title') }}</h4>
        <p>{{ t('workspace_assets.traceability.matrix.body') }}</p>
      </div>
      <div class="matrix-guardrail">
        {{ t('workspace_assets.traceability.matrix.guardrail') }}
      </div>
    </div>

    <div v-if="rows.length" class="matrix-table-wrap">
      <table class="matrix-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column" scope="col">
              {{ column }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td>
              <RouterLink class="matrix-main-link" :to="requirementTo(row.requirement_id)">
                {{ row.requirement_title }}
              </RouterLink>
              <small>{{ row.requirement_id }}</small>
            </td>
            <td>
              <RouterLink v-if="row.task_id" class="matrix-main-link" :to="taskTo(row.task_id)">
                {{ row.task_name || row.task_id }}
              </RouterLink>
              <span v-else class="muted-text">{{ t('workspace_assets.traceability.matrix.no_task') }}</span>
              <small v-if="row.relation_type">{{ row.relation_type }}</small>
            </td>
            <td><span class="asset-state">{{ statusLabel(row.spec_status) }}</span></td>
            <td><span class="asset-state">{{ statusLabel(row.plan_status) }}</span></td>
            <td><span class="asset-state">{{ statusLabel(row.ai_run_status) }}</span></td>
            <td><span class="asset-state">{{ statusLabel(row.human_review_status) }}</span></td>
            <td><span class="asset-state">{{ statusLabel(row.human_delta_status) }}</span></td>
            <td><span class="asset-state">{{ statusLabel(row.evidence_status) }}</span></td>
            <td>
              <span class="coverage-badge" :class="`is-${row.coverage_status}`">
                {{ t(`workspace_assets.traceability.matrix.status.${row.coverage_status}`) }}
              </span>
              <small>{{ row.coverage_reason }}</small>
            </td>
            <td>
              <div class="drill-actions">
                <RouterLink class="drill-link" :to="requirementTo(row.requirement_id)">
                  <FileText />
                  {{ t('workspace_assets.traceability.matrix.open_requirement') }}
                </RouterLink>
                <RouterLink v-if="row.task_id" class="drill-link" :to="taskTo(row.task_id)">
                  <GitBranch />
                  {{ t('workspace_assets.traceability.matrix.open_task') }}
                </RouterLink>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else class="matrix-empty">
      <GitBranch class="empty-icon" />
      <strong>{{ t('workspace_assets.traceability.matrix.empty_title') }}</strong>
      <p>{{ t('workspace_assets.traceability.matrix.empty_body') }}</p>
    </div>

    <div class="status-explainer">
      <h4>{{ t('workspace_assets.traceability.matrix.status_title') }}</h4>
      <ul>
        <li v-for="item in statusLegend" :key="item.status">
          <span class="coverage-badge" :class="`is-${item.status}`">{{ item.label }}</span>
          <small>{{ item.description }}</small>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.matrix-shell {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-top: 20px;
}

.matrix-intro {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 20px;
  align-items: start;
}

.matrix-eyebrow {
  color: #0ea5e9;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  display: block;
  margin-bottom: 0.5rem;
}

.matrix-intro h4,
.status-explainer h4 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.125rem;
  font-weight: 700;
  margin: 0;
  color: #0f172a;
}

.matrix-intro p {
  margin: 0.5rem 0 0;
  color: #64748b;
  font-size: 0.875rem;
  line-height: 1.6;
}

.matrix-guardrail {
  padding: 1.25rem;
  background: #f0f9ff;
  border: 1px solid rgba(14, 165, 233, 0.2);
  border-radius: 1rem;
  color: #0369a1;
  font-size: 0.8125rem;
  line-height: 1.5;
}

.matrix-table-wrap {
  overflow-x: auto;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 1.5rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.matrix-table {
  width: 100%;
  min-width: 1180px;
  border-collapse: collapse;
}

.matrix-table th {
  background: #f8fafc;
  color: #475569;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 1rem;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
}

.matrix-table td {
  padding: 1.25rem 1rem;
  border-bottom: 1px solid #f1f5f9;
  font-size: 0.875rem;
  color: #1e293b;
  vertical-align: middle;
}

.matrix-table tr:hover td {
  background: #fcfdfe;
}

.matrix-table tr:last-child td {
  border-bottom: none;
}

.matrix-main-link {
  color: #0ea5e9;
  font-weight: 700;
  text-decoration: none;
  transition: color 0.3s;
}

.matrix-main-link:hover {
  color: #0284c7;
}

.matrix-table small {
  display: block;
  margin-top: 0.25rem;
  color: #94a3b8;
  font-size: 0.75rem;
  font-family: monospace;
}

.muted-text {
  color: #cbd5e1;
}

.asset-state {
  display: inline-flex;
  padding: 0.25rem 0.625rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
}

.coverage-badge {
  display: inline-flex;
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 700;
  white-space: nowrap;
}

.coverage-badge.is-spec_covered,
.coverage-badge.is-in_progress {
  background: #eff6ff;
  color: #3b82f6;
  border: 1px solid rgba(59, 130, 246, 0.2);
}

.coverage-badge.is-human_modified {
  background: #f5f3ff;
  color: #8b5cf6;
  border: 1px solid rgba(139, 92, 246, 0.2);
}

.coverage-badge.is-evidence_missing,
.coverage-badge.is-need_clarification {
  background: #fffbeb;
  color: #f59e0b;
  border: 1px solid rgba(245, 158, 11, 0.2);
}

.coverage-badge.is-rejected {
  background: #fef2f2;
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.coverage-badge.is-verified {
  background: #f0fdf4;
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.drill-actions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.drill-link {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  color: #64748b;
  font-size: 0.75rem;
  font-weight: 600;
  text-decoration: none;
  transition: color 0.3s;
}

.drill-link:hover {
  color: #0ea5e9;
}

.drill-link svg {
  width: 14px;
  height: 14px;
}

.matrix-empty {
  padding: 4rem 2rem;
  text-align: center;
  background: #f8fafc;
  border: 2px dashed #e2e8f0;
  border-radius: 1.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  color: #94a3b8;
}

.matrix-empty strong {
  font-size: 1.125rem;
  color: #0f172a;
  margin-bottom: 0.5rem;
}

.status-explainer {
  padding: 2rem;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 1.5rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.status-explainer ul {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.5rem;
  padding: 0;
  margin: 1.5rem 0 0;
  list-style: none;
}

.status-explainer li {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  align-items: flex-start;
}

.status-explainer small {
  color: #64748b;
  font-size: 0.8125rem;
  line-height: 1.5;
}

@media (max-width: 1024px) {
  .matrix-intro {
    grid-template-columns: 1fr;
  }
  .status-explainer ul {
    grid-template-columns: 1fr;
  }
}
</style>
