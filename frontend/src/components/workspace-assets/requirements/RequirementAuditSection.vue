<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { RequirementAuditLog } from '@/types/workspaceAssets'

defineProps<{
  logs: readonly RequirementAuditLog[]
}>()

const { t } = useI18n()
</script>

<template>
  <section class="requirement-section">
    <header class="section-head">
      <h4>{{ t('workspace_assets.requirements.detail.audit_title') }}</h4>
      <p>{{ t('workspace_assets.requirements.detail.audit_body') }}</p>
    </header>

    <el-timeline v-if="logs.length">
      <el-timeline-item v-for="log in logs" :key="log.id" :timestamp="log.created_at || t('workspace_assets.requirements.detail.time_pending')">
        <strong>{{ log.action }}</strong>
        <p>{{ log.reason || t('workspace_assets.requirements.detail.no_reason') }}</p>
      </el-timeline-item>
    </el-timeline>
    <el-empty v-else :description="t('workspace_assets.requirements.detail.no_audit')" />
  </section>
</template>

<style scoped>
.requirement-section {
  display: grid;
  gap: 12px;
}

.section-head h4 {
  margin: 0 0 4px;
  font-family: 'Poppins', sans-serif;
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e3a8a;
}

.section-head p {
  margin: 0 0 16px;
  color: #94a3b8;
  font-size: 0.8125rem;
  line-height: 1.4;
}

:deep(.el-timeline-item__content) strong {
  font-size: 0.875rem;
  color: #334155;
}

:deep(.el-timeline-item__content) p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 0.8125rem;
  line-height: 1.4;
}

:deep(.el-timeline-item__timestamp) {
  font-size: 11px;
  color: #94a3b8;
}
</style>
