<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Trash2, X } from '@/components/icons'
import BaseSelect from '@/components/BaseSelect.vue'
import { priorityOptions, type EditableSplitItem } from './model'
const activeItem = defineModel<EditableSplitItem | null>('item', { required: true })
defineProps<{ activeIndex: number }>()
const emit = defineEmits<{ remove: [] }>()
const { t } = useI18n()
const newCriterionText = ref('')
watch(() => activeItem.value?.item_id, () => { newCriterionText.value = '' })
function addCriterion(item: EditableSplitItem) {
  const text = newCriterionText.value.trim()
  if (!text) return
  activeItem.value = { ...item, acceptance_criteria: [...item.acceptance_criteria, text] }
  newCriterionText.value = ''
}
function removeCriterion(item: EditableSplitItem, index: number) {
  activeItem.value = { ...item, acceptance_criteria: item.acceptance_criteria.filter((_, i) => i !== index) }
}
</script>

<template>
<div v-if="activeItem" class="editor-scroll-body">
          <div class="editor-action-header">
            <div class="active-identity">
              <span class="active-badge">#{{ activeIndex + 1 }}</span>
              <h2 class="active-title">{{ activeItem.title || '编辑子需求规格' }}</h2>
            </div>
            <div class="active-controls">
              <label class="include-toggle-label">
                <input v-model="activeItem.include" type="checkbox" />
                <span>{{ t('workspace_assets.requirements.split_review.include_in_import') }}</span>
              </label>
              <button
                class="btn-danger-ghost"
                type="button"
                title="删除该子需求"
                @click="emit('remove')"
              >
                <Trash2 class="w-4 h-4" />
                <span>{{ t('workspace_assets.requirements.actions.delete') }}</span>
              </button>
            </div>
          </div>

          <!-- 表单核心区域 -->
          <div class="form-container">
            <div class="form-row-grid">
              <div class="form-group flex-1">
                <label class="field-label">{{ t('workspace_assets.requirements.fields.title') }}</label>
                <input
                  v-model="activeItem.title"
                  type="text"
                  class="field-input"
                  :placeholder="t('workspace_assets.requirements.placeholders.title')"
                />
              </div>

              <div class="form-group priority-field-group">
                <label class="field-label">{{ t('workspace_assets.requirements.fields.priority') }}</label>
                <BaseSelect v-model="activeItem.priority" :options="priorityOptions" class="field-select" size="sm" />
              </div>
            </div>

            <div class="form-group">
              <label class="field-label">{{ t('workspace_assets.requirements.fields.body') }}</label>
              <textarea
                v-model="activeItem.body"
                rows="6"
                class="field-textarea"
                :placeholder="t('workspace_assets.requirements.placeholders.description')"
              ></textarea>
            </div>

            <div class="form-group">
              <div class="field-label-with-tip">
                <span class="field-label">{{ t('workspace_assets.requirements.fields.acceptance_criteria') }}</span>
                <span class="field-tip">条目化判定依据，回车可快捷新增</span>
              </div>

              <div class="criteria-editor-box">
                <div
                  v-for="(_, cIdx) in activeItem.acceptance_criteria"
                  :key="cIdx"
                  class="criterion-row-item"
                >
                  <span class="criterion-dot"></span>
                  <input
                    v-model="activeItem.acceptance_criteria[cIdx]"
                    type="text"
                    class="criterion-inline-input"
                  />
                  <button
                    class="criterion-remove-btn"
                    type="button"
                    title="移除准则"
                    @click="removeCriterion(activeItem, cIdx)"
                  >
                    <X class="w-3-5 h-3-5" />
                  </button>
                </div>

                <div class="criterion-append-row">
                  <input
                    v-model="newCriterionText"
                    type="text"
                    class="criterion-append-input"
                    :placeholder="t('workspace_assets.requirements.split_review.criterion_placeholder')"
                    @keydown.enter.prevent="addCriterion(activeItem)"
                  />
                  <button
                    class="btn-append-criteria"
                    type="button"
                    :disabled="!newCriterionText.trim()"
                    @click="addCriterion(activeItem)"
                  >
                    {{ t('workspace_assets.requirements.split_review.add_criterion') }}
                  </button>
                </div>
              </div>
            </div>

            <div class="form-group">
              <label class="field-label">{{ t('workspace_assets.requirements.split_review.task_prompt_label') }}</label>
              <textarea
                v-model="activeItem.task_prompt"
                rows="4"
                class="field-textarea font-mono"
                :placeholder="t('workspace_assets.requirements.placeholders.task_prompt')"
              ></textarea>
            </div>
          </div>
        </div>

        <div v-else class="no-active-empty">
          <p>{{ t('workspace_assets.requirements.split_review.no_items') }}</p>
        </div>
</template>

<style scoped>
.editor-scroll-body {
  flex: 1;
  overflow-y: auto;
  padding: 22px 26px;
}
.editor-action-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid #e2e8f0;
  margin-bottom: 18px;
}
.active-identity {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.active-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  border-radius: 6px;
  background: #e0f2fe;
  color: #0369a1;
  font-weight: 800;
  font-size: 0.85rem;
  font-family: var(--font-mono);
}
.active-title {
  margin: 0;
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.active-controls {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}
.include-toggle-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
  user-select: none;
}
.btn-danger-ghost {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
  background: rgba(254, 242, 242, 0.6);
  color: #ef4444;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-danger-ghost:hover {
  background: #fee2e2;
  border-color: #fca5a5;
}
.form-container {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.form-row-grid {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.flex-1 {
  flex: 1;
}
.priority-field-group {
  width: 160px;
  flex-shrink: 0;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  font-size: 0.8125rem;
  font-weight: 700;
  color: #475569;
  letter-spacing: 0.01em;
}
.field-label-with-tip {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.field-tip {
  font-size: 0.75rem;
  color: #94a3b8;
}
.field-input,
.field-select,
.field-textarea {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  color: #0f172a;
  font-family: inherit;
  font-size: 0.875rem;
  padding: 10px 14px;
  transition: all 0.2s ease;
}
.field-input:focus,
.field-select:focus,
.field-textarea:focus {
  border-color: #0ea5e9;
  outline: none;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}
.field-select {
  height: 40px;
  cursor: pointer;
}
.field-textarea {
  resize: vertical;
  line-height: 1.6;
}
.font-mono {
  font-family: var(--font-mono);
  font-size: 0.8125rem;
}
.criteria-editor-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.criterion-row-item {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 12px;
  transition: all 0.2s ease;
}
.criterion-row-item:hover {
  border-color: #cbd5e1;
}
.criterion-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #0ea5e9;
  flex-shrink: 0;
}
.criterion-inline-input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 0.875rem;
  color: #0f172a;
  padding: 2px 4px;
  outline: none;
}
.criterion-remove-btn {
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}
.criterion-remove-btn:hover {
  color: #ef4444;
  background: #fee2e2;
}
.criterion-append-row {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}
.criterion-append-input {
  flex: 1;
  height: 38px;
  box-sizing: border-box;
  padding: 0 14px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: #ffffff;
  font-size: 0.875rem;
  color: #0f172a;
  outline: none;
  transition: all 0.2s ease;
}
.criterion-append-input:focus {
  border-style: solid;
  border-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}
.btn-append-criteria {
  height: 38px;
  padding: 0 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  color: #0284c7;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-append-criteria:hover:not(:disabled) {
  background: #f0f9ff;
  border-color: #bae6fd;
}
.btn-append-criteria:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.no-active-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #94a3b8;
  font-size: 0.95rem;
}
.include-toggle-label input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  margin: 0;
  border-radius: 4px;
  border: 1.5px solid #cbd5e1;
  background-color: #ffffff;
  background-repeat: no-repeat;
  background-position: center;
  background-size: 11px 11px;
  cursor: pointer;
  transition: all 0.16s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
  outline: none;
  display: inline-block;
  vertical-align: middle;
}
.include-toggle-label input[type="checkbox"]:hover:not(:disabled) {
  border-color: #38bdf8;
  background-color: #f0f9ff;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}
.include-toggle-label input[type="checkbox"]:checked {
  border-color: #0ea5e9;
  background-color: #0ea5e9;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M2.5 7L5.5 10L11.5 4' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  box-shadow: 0 2px 4px rgba(14, 165, 233, 0.25);
}
.include-toggle-label input[type="checkbox"]:checked:hover:not(:disabled) {
  border-color: #0284c7;
  background-color: #0284c7;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.35);
}
.include-toggle-label input[type="checkbox"]:focus-visible {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.22);
}
.w-3-5 { width: 14px; }
.h-3-5 { height: 14px; }
.w-4 { width: 16px; }
.h-4 { height: 16px; }
</style>
