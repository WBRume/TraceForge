<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, CheckCircle2, CircleAlert } from 'lucide-vue-next'
import type { BaselineCheckItem } from '@/types/workspaceAssets'
import WorkflowStatusPill from './WorkflowStatusPill.vue'

const props = defineProps<{
  items: BaselineCheckItem[]
}>()

const { t, te } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow.checklist'
const orderedItems = computed(() => [...props.items].sort((a, b) => Number(b.blocking) - Number(a.blocking)))

function itemLabel(item: BaselineCheckItem) {
  const key = `${baseKey}.labels.${item.key}`
  return te(key) ? t(key) : item.label
}

function itemDetail(item: BaselineCheckItem) {
  const key = `${baseKey}.details.${item.key}`
  return te(key) ? t(key) : item.detail
}
</script>

<template>
  <div class="workflow-checklist">
    <div class="checklist-header">
      <CircleAlert class="header-icon" />
      <span>{{ t(`${baseKey}.title`) }}</span>
    </div>
    <div class="checklist-items">
      <div
        v-for="item in orderedItems"
        :key="item.key"
        class="checklist-item"
        :class="{ 'is-blocking': item.blocking }"
      >
        <CheckCircle2 v-if="item.status === 'pass'" class="item-icon is-pass" />
        <AlertTriangle v-else class="item-icon" :class="item.status === 'warning' ? 'is-warning' : 'is-block'" />
        <div class="item-copy">
          <div class="item-title-row">
            <span class="item-title">{{ itemLabel(item) }}</span>
            <WorkflowStatusPill :status="item.status" />
          </div>
          <span v-if="itemDetail(item)" class="item-detail">{{ itemDetail(item) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workflow-checklist {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.checklist-header {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #334155;
  font-size: 0.82rem;
  font-weight: 800;
}

.header-icon {
  width: 16px;
  height: 16px;
}

.checklist-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.checklist-item {
  display: grid;
  grid-template-columns: 18px 1fr;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid #edf2f7;
}

.checklist-item.is-blocking {
  background: linear-gradient(90deg, #fef2f2, transparent);
  padding-left: 8px;
  border-radius: 6px;
}

.item-icon {
  width: 17px;
  height: 17px;
  margin-top: 2px;
}

.item-icon.is-pass {
  color: #16a34a;
}

.item-icon.is-warning {
  color: #ca8a04;
}

.item-icon.is-block {
  color: #dc2626;
}

.item-copy {
  min-width: 0;
}

.item-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.item-title {
  color: #0f172a;
  font-size: 0.84rem;
  font-weight: 700;
}

.item-detail {
  display: block;
  margin-top: 4px;
  color: #64748b;
  font-size: 0.76rem;
  line-height: 1.45;
}
</style>
