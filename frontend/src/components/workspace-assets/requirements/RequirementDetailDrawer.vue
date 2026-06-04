<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import RequirementAuditSection from './RequirementAuditSection.vue'
import RequirementChildrenSection from './RequirementChildrenSection.vue'
import RequirementTaskLinksSection from './RequirementTaskLinksSection.vue'
import type { RequirementDetail, RequirementSummary, TaskSummary } from '@/types/workspaceAssets'

const props = defineProps<{
  open: boolean
  workspaceId: string
  requirement: RequirementSummary | null
  detail: RequirementDetail | null
  tasks: readonly TaskSummary[]
  loading?: boolean
}>()

const emit = defineEmits<{
  close: []
  edit: [requirement: RequirementSummary]
  split: [requirement: RequirementSummary]
  openChild: [requirement: RequirementSummary]
  createChild: [requirement: RequirementSummary]
  link: [payload: { taskId: string; relationType: 'RELATES_TO' | 'COVERS'; reason?: string | null }]
  unlink: [taskId: string]
}>()

const { t } = useI18n()

const activeRequirement = computed(() => props.detail?.requirement || props.requirement)
const linkedTasks = computed(() => props.detail?.linked_tasks || activeRequirement.value?.linked_tasks || [])
const children = computed(() => props.detail?.children || activeRequirement.value?.children || [])
const auditLogs = computed(() => props.detail?.audit_logs || [])
const isParent = computed(() => Boolean(activeRequirement.value && !activeRequirement.value.parent_requirement_id))

function close() {
  emit('close')
}
</script>

<template>
  <el-drawer
    :model-value="open"
    size="min(860px, 100vw)"
    :with-header="false"
    class="requirement-detail-drawer"
    @close="close"
  >
    <section v-if="activeRequirement" class="drawer-shell">
      <header class="drawer-hero">
        <div>
          <p class="eyebrow">{{ t('workspace_assets.requirements.detail.eyebrow') }}</p>
          <h3>{{ activeRequirement.title }}</h3>
          <p>{{ activeRequirement.body || t('workspace_assets.requirements.detail.no_body') }}</p>
        </div>
        <div class="drawer-actions">
          <el-button @click="emit('edit', activeRequirement)">{{ t('workspace_assets.requirements.actions.edit') }}</el-button>
          <el-button v-if="isParent" @click="emit('createChild', activeRequirement)">
            {{ t('workspace_assets.requirements.table.add_child') }}
          </el-button>
          <el-button v-if="isParent" @click="emit('split', activeRequirement)">
            {{ t('workspace_assets.requirements.actions.split') }}
          </el-button>
          <el-button @click="close">{{ t('workspace_assets.requirements.actions.close') }}</el-button>
        </div>
      </header>

      <section class="meta-grid">
        <article>
          <span>{{ t('workspace_assets.requirements.table.level') }}</span>
          <strong>
            {{ activeRequirement.parent_requirement_id ? t('workspace_assets.requirements.table.child_requirement') : t('workspace_assets.requirements.table.parent_requirement') }}
          </strong>
          <small v-if="activeRequirement.parent_title">{{ activeRequirement.parent_title }}</small>
        </article>
        <article>
          <span>{{ t('workspace_assets.requirements.fields.status') }}</span>
          <strong>{{ activeRequirement.status }}</strong>
        </article>
        <article>
          <span>{{ t('workspace_assets.requirements.fields.priority') }}</span>
          <strong>{{ activeRequirement.priority || t('workspace_assets.requirements.detail.not_set') }}</strong>
        </article>
        <article>
          <span>{{ t('workspace_assets.requirements.fields.coverage') }}</span>
          <strong>{{ activeRequirement.coverage_summary?.coverage_status || 'not_available' }}</strong>
          <small>{{ t('workspace_assets.requirements.table.coverage_readonly') }}</small>
        </article>
      </section>

      <section class="drawer-section">
        <header class="section-head">
          <h4>{{ t('workspace_assets.requirements.fields.source_reference') }}</h4>
          <p>{{ t('workspace_assets.requirements.drawer.source_body') }}</p>
        </header>
        <dl class="source-list">
          <div>
            <dt>{{ t('workspace_assets.requirements.fields.source_kind') }}</dt>
            <dd>{{ activeRequirement.source_kind || t('workspace_assets.requirements.detail.source_pending') }}</dd>
          </div>
          <div>
            <dt>{{ t('workspace_assets.requirements.fields.source_ref') }}</dt>
            <dd>{{ activeRequirement.source_ref || t('workspace_assets.requirements.detail.not_set') }}</dd>
          </div>
          <div>
            <dt>{{ t('workspace_assets.requirements.fields.source_uri') }}</dt>
            <dd>
              <a v-if="activeRequirement.source_uri" :href="activeRequirement.source_uri" target="_blank" rel="noreferrer">
                {{ activeRequirement.source_uri }}
              </a>
              <span v-else>{{ t('workspace_assets.requirements.detail.not_set') }}</span>
            </dd>
          </div>
        </dl>
      </section>

      <section class="drawer-section">
        <header class="section-head">
          <h4>{{ t('workspace_assets.requirements.fields.acceptance_criteria') }}</h4>
          <p>{{ t('workspace_assets.requirements.detail.criteria_body') }}</p>
        </header>
        <ul v-if="activeRequirement.acceptance_criteria.length" class="criteria-list">
          <li v-for="criterion in activeRequirement.acceptance_criteria" :key="criterion">{{ criterion }}</li>
        </ul>
        <el-empty v-else :description="t('workspace_assets.requirements.detail.no_criteria')" />
      </section>

      <RequirementChildrenSection
        v-if="isParent"
        :children="children"
        @open="emit('openChild', $event)"
        @create-child="emit('createChild', activeRequirement)"
      />

      <RequirementTaskLinksSection
        v-if="!children.length"
        :workspace-id="workspaceId"
        :requirement="activeRequirement"
        :linked-tasks="linkedTasks"
        :tasks="tasks"
        :loading="loading"
        @link="emit('link', $event)"
        @unlink="emit('unlink', $event)"
      />

      <RequirementAuditSection :logs="auditLogs" />
    </section>

    <section v-else class="drawer-empty">
      <el-empty :description="loading ? t('workspace_assets.requirements.detail.loading') : t('workspace_assets.requirements.detail.empty_body')" />
    </section>
  </el-drawer>
</template>

<style scoped>
.drawer-shell {
  display: grid;
  gap: 20px;
  padding: 4px 4px 24px;
}

.drawer-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 18px;
  border-bottom: 1px solid #e2e8f0;
}

.drawer-hero h3 {
  margin: 4px 0 8px;
  color: #0f172a;
  font-size: 24px;
}

.drawer-hero p {
  margin: 0;
  color: #64748b;
  line-height: 1.6;
}

.eyebrow {
  margin: 0;
  color: #2563eb;
  font-size: 12px;
  font-weight: 800;
}

.drawer-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.meta-grid article {
  display: grid;
  gap: 5px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
}

.meta-grid span,
.meta-grid small,
dt {
  color: #64748b;
  font-size: 12px;
}

.meta-grid strong {
  color: #0f172a;
}

.drawer-section {
  display: grid;
  gap: 12px;
}

.section-head h4 {
  margin: 0 0 4px;
  color: #0f172a;
}

.section-head p {
  margin: 0;
  color: #64748b;
  line-height: 1.5;
}

.source-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 0;
}

.source-list div {
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

dd {
  margin: 4px 0 0;
  color: #0f172a;
  overflow-wrap: anywhere;
}

.criteria-list {
  margin: 0;
  padding-left: 18px;
  color: #334155;
  line-height: 1.6;
}

.drawer-empty {
  padding: 24px;
}

@media (max-width: 900px) {
  .drawer-hero,
  .source-list {
    grid-template-columns: 1fr;
  }

  .drawer-hero {
    flex-direction: column;
  }

  .meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
