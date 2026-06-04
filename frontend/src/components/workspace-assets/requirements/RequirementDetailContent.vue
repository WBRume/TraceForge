<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import RequirementAuditSection from './RequirementAuditSection.vue'
import RequirementChildrenSection from './RequirementChildrenSection.vue'
import RequirementSpecificationBlock from './RequirementSpecificationBlock.vue'
import RequirementTaskLinksSection from './RequirementTaskLinksSection.vue'
import type { RequirementDetail, RequirementLinkedTask, RequirementSummary, TaskSummary } from '@/types/workspaceAssets'

const props = defineProps<{
  workspaceId: string
  requirement: RequirementSummary | null
  detail: RequirementDetail | null
  tasks: readonly TaskSummary[]
  loading?: boolean
}>()

const emit = defineEmits<{
  edit: [requirement: RequirementSummary]
  split: [requirement: RequirementSummary]
  openChild: [requirement: RequirementSummary]
  createChild: [requirement: RequirementSummary]
  link: [payload: { taskId: string; relationType: 'RELATES_TO' | 'COVERS'; reason?: string | null }]
  unlink: [taskId: string]
}>()

const { t } = useI18n()

function uniqueById<T extends { id: string }>(items: readonly T[]): T[] {
  const seen = new Set<string>()
  return items.filter((item) => {
    if (seen.has(item.id)) return false
    seen.add(item.id)
    return true
  })
}

function uniqueLinkedTasks(items: readonly RequirementLinkedTask[]): RequirementLinkedTask[] {
  const seen = new Set<string>()
  return items.filter((item) => {
    const key = item.link_id || item.task_id
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

const activeRequirement = computed(() => props.detail?.requirement || props.requirement)
const linkedTasks = computed(() => uniqueLinkedTasks(props.detail?.linked_tasks || activeRequirement.value?.linked_tasks || []))
const children = computed(() => uniqueById(props.detail?.children || activeRequirement.value?.children || []))
const auditLogs = computed(() => props.detail?.audit_logs || [])
const isParent = computed(() => Boolean(activeRequirement.value && !activeRequirement.value.parent_requirement_id))
const hasChildRequirements = computed(() => isParent.value && children.value.length > 0)
const shouldShowParentSpecification = computed(() => Boolean(activeRequirement.value?.body?.trim()) && !hasChildRequirements.value)
</script>

<template>
  <section v-if="activeRequirement" class="requirement-detail-content">
    <div class="detail-grid">
      <!-- Main Content Area -->
      <div class="main-column">
        <header class="content-card hero-card">
          <div class="hero-header">
            <span class="eyebrow-tag">{{ t('workspace_assets.requirements.detail.eyebrow') }}</span>
            <div class="title-row">
              <h2>{{ activeRequirement.title }}</h2>
            </div>
          </div>
          <p class="hero-description">
            {{ hasChildRequirements ? t('workspace_assets.requirements.detail.children_specification_body') : t('workspace_assets.requirements.detail.specification_body') }}
          </p>
        </header>

        <section class="content-card">
          <div class="card-header">
            <h3>{{ t('workspace_assets.requirements.detail.specification_title') }}</h3>
            <p class="card-subtitle">{{ hasChildRequirements ? t('workspace_assets.requirements.detail.children_specification_body') : t('workspace_assets.requirements.detail.specification_body') }}</p>
          </div>
          <div class="card-body">
            <RequirementSpecificationBlock
              v-if="shouldShowParentSpecification"
              :body="activeRequirement.body"
              :empty-text="t('workspace_assets.requirements.detail.no_body')"
            />
            <el-alert
              v-else-if="hasChildRequirements"
              type="info"
              :closable="false"
              :title="t('workspace_assets.requirements.detail.children_specification_body')"
              show-icon
            />
            <el-empty
              v-else
              :description="t('workspace_assets.requirements.detail.no_body')"
            />
          </div>
        </section>

        <section class="content-card">
          <div class="card-header">
            <h3>{{ t('workspace_assets.requirements.fields.acceptance_criteria') }}</h3>
            <p class="card-subtitle">{{ t('workspace_assets.requirements.detail.criteria_body') }}</p>
          </div>
          <div class="card-body">
            <ul v-if="activeRequirement.acceptance_criteria.length" class="criteria-list">
              <li v-for="criterion in activeRequirement.acceptance_criteria" :key="criterion">{{ criterion }}</li>
            </ul>
            <el-empty v-else :description="t('workspace_assets.requirements.detail.no_criteria')" />
          </div>
        </section>

        <RequirementChildrenSection
          v-if="isParent"
          :children="children"
          class="content-card"
          @open="emit('openChild', $event)"
          @create-child="emit('createChild', activeRequirement)"
        />

        <RequirementTaskLinksSection
          v-if="!hasChildRequirements"
          :workspace-id="workspaceId"
          :requirement="activeRequirement"
          :linked-tasks="linkedTasks"
          :tasks="tasks"
          :loading="loading"
          class="content-card"
          @link="emit('link', $event)"
          @unlink="emit('unlink', $event)"
        />
      </div>

      <!-- Sidebar Area -->
      <aside class="sidebar-column">
        <div class="sidebar-sticky">
          <!-- Quick Actions -->
          <div class="content-card actions-card">
            <div class="detail-actions">
              <el-button type="primary" class="action-btn main-action" @click="emit('edit', activeRequirement)">
                {{ t('workspace_assets.requirements.actions.edit') }}
              </el-button>
              <div class="secondary-actions">
                <el-button v-if="isParent" plain @click="emit('createChild', activeRequirement)">
                  {{ t('workspace_assets.requirements.table.add_child') }}
                </el-button>
                <el-button v-if="isParent" plain @click="emit('split', activeRequirement)">
                  {{ t('workspace_assets.requirements.actions.split') }}
                </el-button>
              </div>
            </div>
          </div>

          <!-- Meta Stats -->
          <div class="content-card stats-card">
            <div class="stats-grid">
              <div class="stat-item">
                <label>{{ t('workspace_assets.requirements.fields.status') }}</label>
                <span class="status-badge" :data-status="activeRequirement.status">{{ activeRequirement.status }}</span>
              </div>
              <div class="stat-item">
                <label>{{ t('workspace_assets.requirements.fields.priority') }}</label>
                <span class="priority-text">{{ activeRequirement.priority || t('workspace_assets.requirements.detail.not_set') }}</span>
              </div>
              <div class="stat-item">
                <label>{{ t('workspace_assets.requirements.table.level') }}</label>
                <span class="level-text">
                  {{ activeRequirement.parent_requirement_id ? t('workspace_assets.requirements.table.child_requirement') : t('workspace_assets.requirements.table.parent_requirement') }}
                </span>
              </div>
              <div class="stat-item">
                <label>{{ t('workspace_assets.requirements.fields.coverage') }}</label>
                <span class="coverage-text" :data-coverage="activeRequirement.coverage_summary?.coverage_status">
                  {{ activeRequirement.coverage_summary?.coverage_status || 'N/A' }}
                </span>
              </div>
            </div>
          </div>

          <!-- Source Reference -->
          <div class="content-card source-card">
            <div class="card-header mini">
              <h4>{{ t('workspace_assets.requirements.fields.source_reference') }}</h4>
            </div>
            <div class="source-info">
              <div class="source-row">
                <label>{{ t('workspace_assets.requirements.fields.source_kind') }}</label>
                <p>{{ activeRequirement.source_kind || t('workspace_assets.requirements.detail.source_pending') }}</p>
              </div>
              <div class="source-row">
                <label>{{ t('workspace_assets.requirements.fields.source_ref') }}</label>
                <p>{{ activeRequirement.source_ref || t('workspace_assets.requirements.detail.not_set') }}</p>
              </div>
              <div v-if="activeRequirement.source_uri" class="source-row">
                <label>{{ t('workspace_assets.requirements.fields.source_uri') }}</label>
                <a :href="activeRequirement.source_uri" target="_blank" class="source-link">{{ activeRequirement.source_uri }}</a>
              </div>
            </div>
          </div>

          <RequirementAuditSection :logs="auditLogs" class="content-card audit-card" />
        </div>
      </aside>
    </div>
  </section>

  <section v-else class="detail-empty">
    <el-empty :description="loading ? t('workspace_assets.requirements.detail.loading') : t('workspace_assets.requirements.detail.empty_body')" />
  </section>
</template>

<style scoped>
.requirement-detail-content {
  width: 100%;
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 24px;
  align-items: start;
}

/* Common Card Style - Glassmorphism */
.content-card {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.03);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.content-card:hover {
  background: rgba(255, 255, 255, 0.85);
  border-color: rgba(14, 165, 233, 0.2);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
}

.main-column {
  min-width: 0;
}

/* Hero Card */
.hero-card {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(240, 249, 255, 0.9) 100%);
  border-left: 4px solid #0ea5e9;
}

.eyebrow-tag {
  display: inline-block;
  padding: 4px 10px;
  background: #f0f9ff;
  color: #0369a1;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  border-radius: 6px;
  margin-bottom: 12px;
  letter-spacing: 0.5px;
}

.hero-header h2 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.85rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 12px;
  line-height: 1.2;
}

.hero-description {
  color: #64748b;
  font-size: 1rem;
  line-height: 1.6;
  margin: 0;
}

/* Section Headers */
.card-header {
  margin-bottom: 20px;
}

.card-header h3 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.2rem;
  font-weight: 600;
  color: #1e3a8a;
  margin: 0 0 4px;
}

.card-subtitle {
  color: #94a3b8;
  font-size: 0.875rem;
  margin: 0;
}

/* Criteria List */
.criteria-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 12px;
}

.criteria-list li {
  position: relative;
  padding-left: 28px;
  color: #334155;
  line-height: 1.6;
}

.criteria-list li::before {
  content: '✓';
  position: absolute;
  left: 0;
  top: 2px;
  width: 20px;
  height: 20px;
  background: #e0f2fe;
  color: #0ea5e9;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 900;
}

/* Sidebar */
.sidebar-sticky {
  position: sticky;
  top: 30px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.actions-card {
  padding: 16px;
}

.detail-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.main-action {
  width: 100%;
  height: 42px;
  font-weight: 600;
  font-size: 0.95rem;
  border-radius: 10px;
}

.secondary-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.secondary-actions :deep(.el-button) {
  margin: 0;
  border-radius: 8px;
  font-weight: 500;
}

/* Stats Card */
.stats-grid {
  display: grid;
  gap: 16px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-item label {
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-item span {
  font-weight: 600;
  color: #1e293b;
  font-size: 0.9375rem;
}

.status-badge {
  display: inline-block;
  padding: 4px 10px;
  background: #f1f5f9;
  border-radius: 6px;
  font-size: 0.8125rem !important;
  width: fit-content;
}

/* Source Card */
.card-header.mini h4 {
  font-size: 0.9rem;
  font-weight: 700;
  color: #475569;
  margin: 0;
}

.source-info {
  display: grid;
  gap: 12px;
}

.source-row label {
  font-size: 11px;
  color: #94a3b8;
  display: block;
  margin-bottom: 2px;
}

.source-row p {
  margin: 0;
  font-size: 0.875rem;
  color: #334155;
  word-break: break-all;
}

.source-link {
  font-size: 0.875rem;
  color: #0ea5e9;
  text-decoration: none;
  word-break: break-all;
}

.source-link:hover {
  text-decoration: underline;
}

/* Empty State */
.detail-empty {
  padding: 60px;
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(8px);
  border: 2px dashed #e2e8f0;
  border-radius: 16px;
}

@media (max-width: 1100px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
  
  .sidebar-column {
    order: -1;
  }
  
  .sidebar-sticky {
    position: static;
  }
}
</style>
