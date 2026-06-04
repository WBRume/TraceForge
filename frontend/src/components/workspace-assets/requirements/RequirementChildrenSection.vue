<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { RequirementSummary } from '@/types/workspaceAssets'

defineProps<{
  children: readonly RequirementSummary[]
}>()

const emit = defineEmits<{
  open: [requirement: RequirementSummary]
  createChild: []
}>()

const { t } = useI18n()
</script>

<template>
  <section class="requirement-section">
    <header class="section-head">
      <div>
        <h4>{{ t('workspace_assets.requirements.drawer.children_title') }}</h4>
        <p>{{ t('workspace_assets.requirements.drawer.children_body') }}</p>
      </div>
      <el-button size="small" type="primary" @click="emit('createChild')">
        {{ t('workspace_assets.requirements.table.add_child') }}
      </el-button>
    </header>

    <div v-if="children.length" class="child-list">
      <button
        v-for="child in children"
        :key="child.id"
        type="button"
        class="child-row"
        @click="emit('open', child)"
      >
        <span class="child-title-cell">
          <strong>{{ child.title }}</strong>
          <small v-if="child.body">{{ child.body }}</small>
        </span>
        <span class="child-meta">
          <span>{{ child.status }}</span>
          <span>{{ t('workspace_assets.requirements.table.task_count') }} {{ child.related_task_count }}</span>
          <span>{{ child.coverage_summary?.coverage_status || 'not_available' }}</span>
        </span>
      </button>
    </div>
    <el-empty v-else :description="t('workspace_assets.requirements.drawer.children_empty')" />
  </section>
</template>

<style scoped>
.requirement-section {
  display: grid;
  gap: 12px;
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.section-head h4 {
  margin: 0 0 4px;
  font-family: 'Poppins', sans-serif;
  font-size: 1.1rem;
  color: #1e3a8a;
}

.section-head p {
  margin: 0;
  color: #94a3b8;
  font-size: 0.875rem;
  line-height: 1.5;
}

.child-list {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.child-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  width: 100%;
  padding: 16px;
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.child-row:hover {
  border-color: #0ea5e944;
  background: #f0f9ff44;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
}

.child-title-cell {
  display: grid;
  gap: 4px;
}

.child-title-cell strong {
  color: #0f172a;
  font-size: 0.95rem;
  line-height: 1.4;
}

.child-title-cell small {
  display: -webkit-box;
  overflow: hidden;
  color: #64748b;
  font-size: 0.8125rem;
  line-height: 1.5;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.child-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #94a3b8;
  font-size: 11px;
  font-weight: 600;
}

.child-meta span {
  padding: 2px 8px;
  border-radius: 4px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  color: #64748b;
}

@media (max-width: 720px) {
  .child-row {
    grid-template-columns: 1fr;
  }

  .child-meta {
    justify-content: flex-start;
  }
}
</style>
