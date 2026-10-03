<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ArrowLeft } from '@/components/icons'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import ParentSpecification from './ParentSpecification.vue'
import SplitItemSelector from './SplitItemSelector.vue'
import SplitItemEditor from './SplitItemEditor.vue'
import { useSplitReview } from './useSplitReview'
const props = defineProps<{ wsId: string; requirementId: string; batchId: string }>()
const { t } = useI18n()
const { loading, submitting, discarding, discardConfirmOpen, parentRequirement, items, activeIndex, activeItem, changeReason, selectedCount, allSelected, draftStatus, draftStatusText, addNewItem, removeItem, setIncluded, goBack, confirmDiscard, handleConfirm } = useSplitReview(props)
</script>

<template>
<div v-loading="loading" class="split-review-view">
    <header class="top-nav-bar">
      <div class="nav-left">
        <button class="back-link" type="button" @click="goBack">
          <ArrowLeft class="back-icon" />
          <span>{{ t('workspace_assets.requirements.split_review.back_to_parent') }}</span>
        </button>
        <div class="nav-title-box">
          <span class="eyebrow-tag">AI 需求拆分工作台</span>
          <span class="nav-requirement-title" :title="parentRequirement?.title || ''">
            {{ parentRequirement?.title || t('workspace_assets.requirements.split_review.title') }}
          </span>
        </div>
      </div>

      <div class="nav-right">
        <span
          v-if="draftStatus !== 'idle'"
          class="draft-status"
          :class="`is-${draftStatus}`"
        >{{ draftStatusText }}</span>
        <input
          v-model="changeReason"
          type="text"
          class="reason-input"
          :placeholder="t('workspace_assets.requirements.placeholders.change_reason')"
        />
        <button class="btn-cancel" type="button" @click="discardConfirmOpen = true">
          {{ t('workspace_assets.requirements.split_review.discard_action') }}
        </button>
        <button
          class="btn-confirm"
          type="button"
          :disabled="submitting || selectedCount === 0"
          @click="handleConfirm"
        >
          <span v-if="submitting">{{ t('workspace_assets.requirements.split_review.submitting') }}</span>
          <span v-else>{{ t('workspace_assets.requirements.split_review.confirm_action', { count: selectedCount }) }}</span>
        </button>
      </div>
    </header>
    <main class="workbench-grid">
      <ParentSpecification :requirement="parentRequirement" />
      <section class="workbench-column editor-column content-card">
        <SplitItemSelector :items="items" :active-index="activeIndex" :selected-count="selectedCount" :all-selected="allSelected"
          @select="activeIndex = $event" @add="addNewItem" @remove="removeItem" @include="setIncluded" @select-all="allSelected = $event" />
        <SplitItemEditor v-model:item="activeItem" :active-index="activeIndex" @remove="removeItem(activeIndex)" />
      </section>
    </main>
    <ConfirmActionModal
      :show="discardConfirmOpen"
      :title="t('workspace_assets.requirements.split_review.discard_confirm_title')"
      :message="t('workspace_assets.requirements.split_review.discard_confirm_message')"
      :cancel-text="t('common.cancel')"
      :confirm-text="t('workspace_assets.requirements.split_review.discard_confirm_text')"
      :loading="discarding"
      tone="danger"
      @cancel="discardConfirmOpen = false"
      @confirm="confirmDiscard"
    />
  </div>
</template>

<style scoped>
.split-review-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  box-sizing: border-box;
  padding: 20px 28px;
  background-color: #f8fafc;
  color: #0f172a;
  font-family: 'Open Sans', var(--font-body);
  overflow: hidden;
}
.top-nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 16px;
  flex-shrink: 0;
  min-height: 42px;
}
.nav-left {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
  flex: 1;
}
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 16px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  color: #475569;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  flex-shrink: 0;
}
.back-link:hover {
  color: #0ea5e9;
  border-color: rgba(14, 165, 233, 0.4);
  background: #ffffff;
  transform: translateX(-2px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.12);
}
.back-icon {
  width: 16px;
  height: 16px;
}
.nav-title-box {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}
.eyebrow-tag {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  background: #e0f2fe;
  color: #0369a1;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  border-radius: 5px;
  letter-spacing: 0.5px;
  flex-shrink: 0;
}
.nav-requirement-title {
  font-family: 'Poppins', sans-serif;
  font-size: 1.15rem;
  font-weight: 700;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nav-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.draft-status {
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
  color: #94a3b8;
}
.draft-status.is-saving {
  color: #0284c7;
}
.draft-status.is-saved {
  color: #16a34a;
}
.draft-status.is-error {
  color: #dc2626;
}
.reason-input {
  width: 250px;
  height: 38px;
  box-sizing: border-box;
  padding: 0 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.9);
  font-size: 0.85rem;
  color: #0f172a;
  transition: all 0.2s ease;
}
.reason-input:focus {
  border-color: #0ea5e9;
  background: #ffffff;
  outline: none;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}
.btn-cancel {
  height: 38px;
  padding: 0 18px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  color: #475569;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-cancel:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
  color: #0f172a;
}
.btn-confirm {
  height: 38px;
  padding: 0 22px;
  border: 1px solid #0284c7;
  border-radius: 10px;
  background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
  color: #ffffff;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(14, 165, 233, 0.28);
  transition: all 0.2s ease;
}
.btn-confirm:hover:not(:disabled) {
  background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
  box-shadow: 0 6px 18px rgba(14, 165, 233, 0.38);
  transform: translateY(-1px);
}
.btn-confirm:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
}
.workbench-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(420px, 45%) minmax(500px, 55%);
  gap: 20px;
}
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
.editor-column {
  /* 去除顶部色条，保持统一平整边框 */
}
@media (max-width: 1000px) {
  .workbench-grid {
    grid-template-columns: 1fr;
  }
}
</style>
