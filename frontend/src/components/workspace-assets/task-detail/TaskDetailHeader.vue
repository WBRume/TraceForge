<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Activity, Database, FileText, ShieldCheck, UserRound } from 'lucide-vue-next'
import type { TaskDetail, TaskDetailSummaryResponse } from '@/types/workspaceAssets'

const props = defineProps<{
  detail: TaskDetail | TaskDetailSummaryResponse | null
  workspaceId: string
  taskId: string
}>()

const { t } = useI18n()

const task = computed(() => props.detail?.task || null)
const requirementLinks = computed(() => props.detail?.requirement_links || [])
const summary = computed(() => props.detail?.process_summary || null)

const formatPhase = (phase: string | null | undefined): string => {
  if (!phase) return t('workspace_assets.task_detail.header.waiting_stage')
  const phaseMap: Record<string, string> = {
    'REQUIREMENT_CLARIFICATION': t('workspace_assets.task_detail.phase.requirement_clarification'),
    'AI_SOLUTION': t('workspace_assets.task_detail.phase.ai_solution'),
    'CODING': t('workspace_assets.task_detail.phase.coding'),
    'COMPILE': t('workspace_assets.task_detail.phase.compile'),
    'PACKAGE': t('workspace_assets.task_detail.phase.package'),
    'DEVICE_TEST': t('workspace_assets.task_detail.phase.device_test'),
    'INTEGRATION': t('workspace_assets.task_detail.phase.integration'),
    'OTHER': t('workspace_assets.task_detail.phase.other'),
  }
  return phaseMap[phase] || phase
}

const formatEvidenceStatus = (status: string | null | undefined): string => {
  if (!status) return t('workspace_assets.task_detail.header.waiting_evidence')
  const statusMap: Record<string, string> = {
    'available': t('workspace_assets.task_detail.evidence_status.available'),
    'empty': t('workspace_assets.task_detail.evidence_status.empty'),
    'not_connected': t('workspace_assets.task_detail.evidence_status.not_connected'),
  }
  return statusMap[status] || status
}

const formatCoverageStatus = (status: string | null | undefined): string => {
  if (!status) return t('workspace_assets.task_detail.header.not_verified')
  const statusMap: Record<string, string> = {
    'not_available': t('workspace_assets.task_detail.coverage_status.not_available'),
    'waiting_evidence': t('workspace_assets.task_detail.coverage_status.waiting_evidence'),
    'waiting_human_confirmation': t('workspace_assets.task_detail.coverage_status.waiting_human_confirmation'),
    'verified': t('workspace_assets.task_detail.coverage_status.verified'),
  }
  return statusMap[status] || status
}

const metaItems = computed(() => [
  {
    key: 'owner',
    label: t('workspace_assets.task_detail.header.owner'),
    value: task.value?.creator_display_name || task.value?.creator_id || t('workspace_assets.task_detail.header.not_assigned'),
    icon: UserRound,
    color: '#6366f1'
  },
  {
    key: 'stage',
    label: t('workspace_assets.task_detail.header.current_stage'),
    value: formatPhase(task.value?.current_phase),
    icon: Activity,
    color: '#0ea5e9'
  },
  {
    key: 'evidence',
    label: t('workspace_assets.task_detail.header.evidence'),
    value: formatEvidenceStatus(summary.value?.evidence_status),
    icon: Database,
    color: '#f59e0b'
  },
  {
    key: 'coverage',
    label: t('workspace_assets.task_detail.header.coverage'),
    value: formatCoverageStatus(summary.value?.coverage_status || task.value?.coverage_status),
    icon: ShieldCheck,
    color: '#10b981'
  },
])
</script>

<template>
  <header class="task-detail-header">
    <div class="header-main">
      <div class="title-section">
        <div class="eyebrow-row">
          <span class="eyebrow-tag">{{ t('workspace_assets.task_detail.eyebrow') }}</span>
          <div class="id-badges">
            <span class="badge">WS: {{ workspaceId }}</span>
            <span class="badge">TASK: {{ taskId }}</span>
          </div>
        </div>
        <h1 class="task-title">{{ task?.name || t('workspace_assets.task_detail.title') }}</h1>
        <p class="task-desc">{{ task?.description || t('workspace_assets.task_detail.subtitle') }}</p>
      </div>

      <div class="meta-grid">
        <div v-for="item in metaItems" :key="item.key" class="meta-card">
          <div class="meta-icon-wrapper" :style="{ backgroundColor: item.color + '15', color: item.color }">
            <component :is="item.icon" class="meta-icon" />
          </div>
          <div class="meta-info">
            <span class="meta-label">{{ item.label }}</span>
            <span class="meta-value">{{ item.value }}</span>
          </div>
        </div>
      </div>
    </div>

    <aside class="header-aside">
      <div class="requirements-panel">
        <div class="panel-head">
          <FileText class="panel-icon" />
          <h3>{{ t('workspace_assets.task_detail.header.related_requirements') }}</h3>
        </div>
        <div v-if="requirementLinks.length" class="requirement-scroll">
          <RouterLink
            v-for="link in requirementLinks"
            :key="link.id"
            class="requirement-pill"
            :to="{ name: 'workspaceAssetsRequirementDetail', params: { wsId: workspaceId, requirementId: link.requirement_id }, query: { from: 'task' } }"
          >
            <span class="req-title">{{ link.requirement?.title || link.requirement_id }}</span>
            <span class="req-type">{{ link.relation_type }}</span>
          </RouterLink>
        </div>
        <div v-else class="empty-requirements">
          <p>{{ t('workspace_assets.task_detail.header.no_requirements') }}</p>
        </div>
      </div>
    </aside>
  </header>
</template>

<style scoped>
.task-detail-header {
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: 16px;
  align-items: stretch;
}

.header-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(226, 232, 240, 0.6);
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.02);
}

.eyebrow-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.eyebrow-tag {
  color: #2563eb;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.id-badges {
  display: flex;
  gap: 6px;
}

.badge {
  padding: 2px 6px;
  background: #f1f5f9;
  border-radius: 4px;
  color: #64748b;
  font-size: 0.65rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
}

.task-title {
  margin: 0;
  color: #0f172a;
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 600;
  line-height: 1.3;
}

.task-desc {
  margin: 6px 0 0;
  color: #475569;
  font-size: 0.8rem;
  line-height: 1.5;
  max-width: 600px;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}

.meta-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: white;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  transition: transform 0.2s, box-shadow 0.2s;
}

.meta-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(15, 23, 42, 0.04);
}

.meta-icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  flex-shrink: 0;
}

.meta-icon {
  width: 14px;
  height: 14px;
}

.meta-info {
  display: flex;
  flex-direction: column;
}

.meta-label {
  color: #64748b;
  font-size: 0.65rem;
  font-weight: 600;
}

.meta-value {
  color: #1e293b;
  font-size: 0.75rem;
  font-weight: 600;
}

/* Aside / Requirements */
.header-aside {
  display: flex;
}

.requirements-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 14px;
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(226, 232, 240, 0.6);
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.02);
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.panel-icon {
  width: 14px;
  height: 14px;
  color: #2563eb;
}

.panel-head h3 {
  margin: 0;
  font-size: 0.75rem;
  font-weight: 600;
  color: #0f172a;
}

.requirement-scroll {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 120px;
  overflow-y: auto;
  padding-right: 4px;
}

.requirement-pill {
  display: flex;
  flex-direction: column;
  padding: 6px 8px;
  background: white;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  text-decoration: none;
  transition: all 0.2s;
}

.requirement-pill:hover {
  border-color: #0ea5e966;
  background: #f0f9ff;
  transform: translateX(2px);
}

.req-title {
  color: #1e293b;
  font-size: 0.7rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.req-type {
  color: #94a3b8;
  font-size: 0.6rem;
  font-weight: 600;
  text-transform: uppercase;
}

.empty-requirements {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 0.7rem;
  font-style: italic;
}

@media (max-width: 1200px) {
  .task-detail-header {
    grid-template-columns: 1fr;
  }
}
</style>
