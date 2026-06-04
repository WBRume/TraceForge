<script setup lang="ts">
import { FilePlus2 } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import type { RequirementSummary } from '@/types/workspaceAssets'

const props = defineProps<{
  items: readonly RequirementSummary[]
  selectedId: string | null
  loading?: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
  create: []
}>()

const { t } = useI18n()
</script>

<template>
  <section class="requirement-repository">
    <header class="repository-head">
      <div>
        <span class="eyebrow">{{ t('workspace_assets.requirements.repository.eyebrow') }}</span>
        <h3>{{ t('workspace_assets.requirements.repository.title') }}</h3>
        <p>{{ t('workspace_assets.requirements.repository.body') }}</p>
      </div>
      <div class="repository-actions">
        <button type="button" class="primary-action" @click="emit('create')">
          <FilePlus2 :size="16" />
          {{ t('workspace_assets.requirements.actions.new') }}
        </button>
      </div>
    </header>

    <div v-if="props.items.length" class="requirement-list" :aria-label="t('workspace_assets.requirements.repository.list_label')">
      <button
        v-for="item in props.items"
        :key="item.id"
        type="button"
        class="requirement-row"
        :class="{ 'is-active': props.selectedId === item.id }"
        @click="emit('select', item.id)"
      >
        <span>
          <strong>{{ item.title }}</strong>
          <small>{{ item.status }} · {{ t('workspace_assets.requirements.repository.related_task_count', { count: item.related_task_count }) }}</small>
        </span>
        <span class="row-meta">
          {{ item.source_uri || item.source_ref || t('workspace_assets.requirements.repository.source_pending') }}
        </span>
      </button>
    </div>

    <div v-else class="empty-box">
      <strong>{{ props.loading ? t('workspace_assets.requirements.repository.loading') : t('workspace_assets.requirements.repository.empty_title') }}</strong>
      <p>{{ t('workspace_assets.requirements.repository.empty_body') }}</p>
    </div>
  </section>
</template>

<style scoped>
.requirement-repository {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}

.repository-head {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 1.5rem;
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 1.5rem;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(12px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
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

.repository-head h3 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  margin: 0;
  color: #0f172a;
}

.repository-head p {
  margin: 0.5rem 0 0;
  color: #64748b;
  font-size: 0.875rem;
  line-height: 1.6;
}

.repository-actions {
  display: flex;
  align-items: center;
}

.primary-action {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: #0ea5e9;
  color: white;
  padding: 0.75rem 1.25rem;
  border: none;
  border-radius: 0.75rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.3s;
}

.primary-action:hover {
  background: #0284c7;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.4);
}

.requirement-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.requirement-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  width: 100%;
  padding: 1.25rem;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  background: white;
  text-align: left;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.requirement-row:hover {
  transform: translateY(-4px);
  border-color: #0ea5e9;
  box-shadow: 0 10px 15px -3px rgba(14, 165, 233, 0.1);
}

.requirement-row.is-active {
  border-color: #0ea5e9;
  background: #f0f9ff;
  box-shadow: 0 4px 6px -1px rgba(14, 165, 233, 0.1);
}

.requirement-row strong {
  display: block;
  font-size: 1rem;
  color: #0f172a;
  margin-bottom: 0.25rem;
}

.requirement-row small {
  color: #64748b;
  font-size: 0.8125rem;
}

.row-meta {
  color: #94a3b8;
  font-size: 0.75rem;
  font-family: monospace;
  align-self: flex-start;
  margin-top: 4px;
}

.empty-box {
  padding: 3rem 2rem;
  border: 2px dashed #e2e8f0;
  border-radius: 1.5rem;
  background: #f8fafc;
  color: #94a3b8;
  text-align: center;
}

.empty-box strong {
  display: block;
  font-size: 1rem;
  color: #0f172a;
  margin-bottom: 0.5rem;
}

.empty-box p {
  margin: 0;
  font-size: 0.875rem;
}

@media (max-width: 768px) {
  .repository-head {
    flex-direction: column;
    align-items: flex-start;
  }
  .repository-actions {
    width: 100%;
  }
  .primary-action {
    width: 100%;
    justify-content: center;
  }
  .requirement-row {
    grid-template-columns: 1fr;
  }
}
</style>
