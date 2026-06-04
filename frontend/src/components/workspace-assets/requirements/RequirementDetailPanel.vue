<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { GitBranch, History, Link2Off, MessageSquare, Scissors } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import type { RequirementDetail, RequirementSummary, TaskSummary } from '@/types/workspaceAssets'

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
  link: [payload: { taskId: string; relationType: 'RELATES_TO' | 'COVERS'; reason?: string | null }]
  unlink: [taskId: string]
}>()

const linkTaskId = shallowRef('')
const linkRelationType = shallowRef<'RELATES_TO' | 'COVERS'>('RELATES_TO')
const linkReason = shallowRef('')
const { t } = useI18n()

const requirement = computed(() => props.detail?.requirement || props.requirement)
const linkedTasks = computed(() => props.detail?.linked_tasks || requirement.value?.linked_tasks || [])
const auditLogs = computed(() => props.detail?.audit_logs || [])
const availableTasks = computed(() => {
  const linked = new Set(linkedTasks.value.map((item) => item.task_id))
  return props.tasks.filter((task) => !linked.has(task.id))
})

function submitLink() {
  if (!linkTaskId.value) return
  emit('link', {
    taskId: linkTaskId.value,
    relationType: linkRelationType.value,
    reason: linkReason.value || null,
  })
  linkTaskId.value = ''
  linkReason.value = ''
}
</script>

<template>
  <section class="requirement-detail-panel">
    <template v-if="requirement">
      <header class="detail-head">
        <div>
          <span class="eyebrow">{{ t('workspace_assets.requirements.detail.eyebrow') }}</span>
          <h3>{{ requirement.title }}</h3>
          <p>{{ requirement.body || t('workspace_assets.requirements.detail.no_body') }}</p>
        </div>
        <div class="detail-actions">
          <button type="button" class="secondary-action" @click="emit('split', requirement)">
            <Scissors :size="15" />
            {{ t('workspace_assets.requirements.actions.split') }}
          </button>
          <button type="button" class="primary-action" @click="emit('edit', requirement)">
            {{ t('workspace_assets.requirements.actions.edit') }}
          </button>
        </div>
      </header>

      <dl class="meta-grid">
        <div>
          <dt>{{ t('workspace_assets.requirements.fields.status') }}</dt>
          <dd>{{ requirement.status }}</dd>
        </div>
        <div>
          <dt>{{ t('workspace_assets.requirements.fields.priority') }}</dt>
          <dd>{{ requirement.priority || t('workspace_assets.requirements.detail.not_set') }}</dd>
        </div>
        <div>
          <dt>{{ t('workspace_assets.requirements.fields.source_reference') }}</dt>
          <dd>{{ requirement.source_uri || requirement.source_ref || t('workspace_assets.requirements.detail.source_pending') }}</dd>
        </div>
        <div>
          <dt>{{ t('workspace_assets.requirements.fields.coverage') }}</dt>
          <dd>
            {{ requirement.coverage_summary?.coverage_status || 'not_available' }}
            <small>{{ requirement.coverage_summary?.coverage_reason }}</small>
          </dd>
        </div>
      </dl>

      <section class="detail-section">
        <div class="section-head">
          <div>
            <h4>{{ t('workspace_assets.requirements.fields.acceptance_criteria') }}</h4>
            <p>{{ t('workspace_assets.requirements.detail.criteria_body') }}</p>
          </div>
          <span>{{ requirement.acceptance_criteria?.length || 0 }}</span>
        </div>
        <ul v-if="requirement.acceptance_criteria?.length" class="criteria-list">
          <li v-for="criterion in requirement.acceptance_criteria" :key="criterion">{{ criterion }}</li>
        </ul>
        <div v-else class="empty-box compact">{{ t('workspace_assets.requirements.detail.no_criteria') }}</div>
      </section>

      <section class="detail-section">
        <div class="section-head">
          <div>
            <h4>{{ t('workspace_assets.requirements.related_tasks_title') }}</h4>
            <p>{{ t('workspace_assets.requirements.detail.related_tasks_body') }}</p>
          </div>
          <span>{{ linkedTasks.length }}</span>
        </div>
        <div v-if="linkedTasks.length" class="linked-task-list">
          <RouterLink
            v-for="link in linkedTasks"
            :key="link.link_id"
            class="linked-task-row"
            :to="`/ws/${props.workspaceId}/assets/tasks/${link.task_id}`"
          >
            <span>
              <strong>{{ link.task_name || link.task_id }}</strong>
              <small>{{ link.relation_type }} · {{ link.task_status }} · {{ link.current_phase || t('workspace_assets.requirements.detail.phase_pending') }}</small>
            </span>
            <button type="button" class="icon-action" @click.prevent="emit('unlink', link.task_id)" :title="t('workspace_assets.requirements.actions.unlink_task')">
              <Link2Off :size="15" />
            </button>
          </RouterLink>
        </div>
        <div v-else class="empty-box compact">
          <MessageSquare :size="17" />
          <span>{{ t('workspace_assets.requirements.related_tasks_empty') }}</span>
        </div>

        <form class="link-form" @submit.prevent="submitLink">
          <select v-model="linkTaskId" :disabled="!availableTasks.length">
            <option value="">{{ t('workspace_assets.requirements.detail.select_task') }}</option>
            <option v-for="task in availableTasks" :key="task.id" :value="task.id">
              {{ task.name }}
            </option>
          </select>
          <select v-model="linkRelationType">
            <option value="RELATES_TO">RELATES_TO</option>
            <option value="COVERS">COVERS</option>
          </select>
          <input v-model="linkReason" :placeholder="t('workspace_assets.requirements.fields.change_reason')" />
          <button type="submit" class="secondary-action" :disabled="!linkTaskId">{{ t('workspace_assets.requirements.actions.link_task') }}</button>
        </form>
      </section>

      <section class="detail-section">
        <div class="section-head">
          <div>
            <h4>{{ t('workspace_assets.requirements.detail.audit_title') }}</h4>
            <p>{{ t('workspace_assets.requirements.detail.audit_body') }}</p>
          </div>
          <History :size="18" />
        </div>
        <ol v-if="auditLogs.length" class="audit-list">
          <li v-for="log in auditLogs" :key="log.id">
            <GitBranch :size="15" />
            <span>
              <strong>{{ log.action }}</strong>
              <small>{{ log.created_at || t('workspace_assets.requirements.detail.time_pending') }} · {{ log.reason || t('workspace_assets.requirements.detail.no_reason') }}</small>
            </span>
          </li>
        </ol>
        <div v-else class="empty-box compact">{{ t('workspace_assets.requirements.detail.no_audit') }}</div>
      </section>
    </template>

    <div v-else class="empty-box">
      <strong>{{ props.loading ? t('workspace_assets.requirements.detail.loading') : t('workspace_assets.requirements.detail.select_requirement') }}</strong>
      <p>{{ t('workspace_assets.requirements.detail.empty_body') }}</p>
    </div>
  </section>
</template>

<style scoped>
.requirement-detail-panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}

.detail-head,
.detail-section,
.meta-grid {
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 1.5rem;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(12px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.detail-head {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 2rem;
}

.eyebrow {
  color: #0ea5e9;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  display: block;
  margin-bottom: 0.5rem;
}

.detail-head h3 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.5rem;
  font-weight: 700;
  margin: 0;
  color: #0f172a;
}

.detail-head p,
.section-head p {
  margin: 0.75rem 0 0;
  color: #64748b;
  font-size: 0.9375rem;
  line-height: 1.6;
}

.detail-actions,
.link-form {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.primary-action,
.secondary-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  border-radius: 0.75rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.3s;
}

.primary-action {
  background: #0ea5e9;
  color: white;
  border: none;
}

.primary-action:hover {
  background: #0284c7;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.4);
}

.secondary-action {
  background: white;
  border: 1px solid #e2e8f0;
  color: #475569;
}

.secondary-action:hover:not(:disabled) {
  border-color: #0ea5e9;
  color: #0ea5e9;
  background: #f0f9ff;
}

.secondary-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  background: white;
}

.meta-grid div {
  padding: 1.5rem;
  border-bottom: 1px solid #f1f5f9;
}

.meta-grid div:nth-child(odd) {
  border-right: 1px solid #f1f5f9;
}

.meta-grid dt {
  color: #94a3b8;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  margin-bottom: 0.5rem;
}

.meta-grid dd {
  margin: 0;
  color: #1e293b;
  font-size: 0.9375rem;
  font-weight: 600;
}

.meta-grid small {
  display: block;
  margin-top: 0.25rem;
  color: #64748b;
  font-weight: 400;
  font-size: 0.8125rem;
}

.detail-section {
  padding: 2rem;
}

.section-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.section-head h4 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.125rem;
  font-weight: 700;
  margin: 0;
  color: #0f172a;
}

.section-head span {
  background: #f0f9ff;
  color: #0ea5e9;
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  font-size: 0.8125rem;
  font-weight: 700;
  align-self: flex-start;
}

.criteria-list,
.audit-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0;
  margin: 0;
  list-style: none;
}

.criteria-list li,
.audit-list li {
  padding: 1rem;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 0.75rem;
  font-size: 0.875rem;
  color: #475569;
  line-height: 1.6;
}

.linked-task-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.linked-task-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 1rem;
  text-decoration: none;
  transition: all 0.3s;
}

.linked-task-row:hover {
  background: white;
  border-color: #0ea5e9;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.linked-task-row strong {
  display: block;
  font-size: 0.9375rem;
  color: #0f172a;
  margin-bottom: 0.25rem;
}

.linked-task-row small {
  color: #64748b;
  font-size: 0.8125rem;
}

.link-form {
  margin-top: 1.5rem;
  padding: 1.5rem;
  background: #f8fafc;
  border-radius: 1rem;
  border: 1px solid #f1f5f9;
}

.link-form select,
.link-form input {
  padding: 0.75rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: white;
  font-size: 0.875rem;
  outline: none;
  transition: border-color 0.3s;
}

.link-form select:focus,
.link-form input:focus {
  border-color: #0ea5e9;
}

.empty-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 1.5rem;
  background: #f8fafc;
  border: 2px dashed #e2e8f0;
  border-radius: 1.5rem;
  color: #94a3b8;
  text-align: center;
}

.empty-box.compact {
  padding: 1.5rem;
  flex-direction: row;
  gap: 1rem;
}

.empty-box strong {
  color: #0f172a;
  margin-bottom: 0.5rem;
}

@media (max-width: 1024px) {
  .meta-grid {
    grid-template-columns: 1fr;
  }
  .meta-grid div:nth-child(odd) {
    border-right: none;
  }
}

@media (max-width: 768px) {
  .detail-head {
    flex-direction: column;
    padding: 1.5rem;
  }
  .detail-actions {
    width: 100%;
  }
  .primary-action, .secondary-action {
    flex: 1;
  }
}
</style>
