<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import RequirementSpecificationBlock from '../RequirementSpecificationBlock.vue'
import type { RequirementDetail } from '@/types/workspaceAssets'
import { getPriorityBadgeClass } from './model'
defineProps<{ requirement: RequirementDetail['requirement'] | null }>()
const { t } = useI18n()
</script>

<template>
<section class="workbench-column spec-column content-card">
        <div class="column-header">
          <span class="column-eyebrow">对照基准</span>
          <h2 class="column-title">母需求原始规格</h2>
        </div>

        <div class="spec-scroll-body">
          <div class="spec-hero-box">
            <h3 class="parent-title">{{ requirement?.title || '未命名需求' }}</h3>
            <div class="parent-meta-row">
              <span class="meta-tag status-tag">{{ requirement?.status || 'DRAFT' }}</span>
              <span class="meta-tag priority-tag" :class="getPriorityBadgeClass(requirement?.priority || '')">
                {{ requirement?.priority || '未设置' }}
              </span>
            </div>
          </div>

          <div class="spec-section">
            <h4 class="spec-section-title">规格说明内容</h4>
            <div v-if="requirement?.body" class="spec-body-wrapper">
              <RequirementSpecificationBlock
                :body="requirement.body"
                :empty-text="t('workspace_assets.requirements.split_review.no_parent_spec')"
              />
            </div>
            <div v-else class="empty-spec-text">
              {{ t('workspace_assets.requirements.split_review.no_parent_spec') }}
            </div>
          </div>

          <div class="spec-section" v-if="requirement?.acceptance_criteria?.length">
            <h4 class="spec-section-title">原始验收准则</h4>
            <ul class="criteria-list">
              <li v-for="(crit, idx) in requirement.acceptance_criteria" :key="idx">
                {{ crit }}
              </li>
            </ul>
          </div>
        </div>
      </section>
</template>

<style scoped>
.content-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.03);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-sizing: border-box;
}
.column-header {
  padding: 14px 20px;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
  flex-shrink: 0;
}
.column-eyebrow {
  display: block;
  font-size: 11px;
  font-weight: 800;
  color: #0284c7;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 2px;
}
.column-title {
  margin: 0;
  font-family: 'Poppins', sans-serif;
  font-size: 1.05rem;
  font-weight: 700;
  color: #0f172a;
}
.spec-column {
  /* 去除顶部色条，保持统一平整边框 */
}
.spec-scroll-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.spec-hero-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 18px;
}
.parent-title {
  margin: 0 0 10px;
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.35;
}
.parent-meta-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.meta-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}
.status-tag {
  background: #f1f5f9;
  color: #475569;
}
.priority-tag.priority-high { background: #fee2e2; color: #b91c1c; }
.priority-tag.priority-medium { background: #fef3c7; color: #b45309; }
.priority-tag.priority-low { background: #e0f2fe; color: #0369a1; }
.spec-section-title {
  margin: 0 0 10px;
  font-family: 'Poppins', sans-serif;
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e3a8a;
}
.spec-body-wrapper {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 20px;
  font-size: 0.9rem;
  line-height: 1.65;
}
.empty-spec-text {
  font-size: 0.85rem;
  color: #94a3b8;
  font-style: italic;
}
.criteria-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.criteria-list li {
  position: relative;
  padding-left: 28px;
  font-size: 0.875rem;
  color: #334155;
  line-height: 1.6;
}
.criteria-list li::before {
  content: '✓';
  position: absolute;
  left: 0;
  top: 2px;
  width: 18px;
  height: 18px;
  background: #e0f2fe;
  color: #0ea5e9;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 900;
}
</style>
