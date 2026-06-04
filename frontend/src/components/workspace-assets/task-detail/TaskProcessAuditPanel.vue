<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { TaskProcessAuditLogLight } from '@/types/workspaceAssets'

defineProps<{
  auditLogs: TaskProcessAuditLogLight[]
  workspaceId: string
  taskId: string
}>()

const { t } = useI18n()
</script>

<template>
  <aside class="audit-panel">
    <header>
      <strong>{{ t('workspace_assets.task_detail.workbench.audit.title') }}</strong>
      <span>{{ t('workspace_assets.task_detail.workbench.audit.description') }}</span>
    </header>
    <div v-if="auditLogs.length" class="audit-list">
      <article v-for="log in auditLogs.slice(0, 8)" :key="log.id" class="audit-item">
        <strong>{{ log.action }} · {{ log.record_type }}</strong>
        <span>{{ log.reason || t('workspace_assets.task_detail.workbench.audit.no_reason') }}</span>
        <small>{{ log.created_at || '-' }}</small>
      </article>
    </div>
    <p v-else>{{ t('workspace_assets.task_detail.workbench.audit.empty') }}</p>
  </aside>
</template>

<style scoped>
.audit-panel {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.audit-panel header,
.audit-item {
  display: grid;
  gap: 4px;
}

.audit-panel strong {
  color: #0f172a;
  font-size: 0.9rem;
}

.audit-panel span,
.audit-panel p,
.audit-panel small {
  margin: 0;
  color: #64748b;
  font-size: 0.8rem;
  line-height: 1.45;
}

.audit-list {
  display: grid;
  gap: 8px;
}

.audit-item {
  padding: 10px;
  border-radius: 8px;
  background: #fff;
}
</style>
