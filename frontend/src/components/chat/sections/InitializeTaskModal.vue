<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { AlertCircle, RotateCcw } from 'lucide-vue-next'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'

/**
 * 初始化会话弹窗：录入初始化原因与初始 Prompt、装配运行时技能，
 * 并处理「已删除运行时技能」的三选确认（取消 / 丢弃 / 保留）。
 */
const props = defineProps<{
  vm: ChatViewVm
}>()

const { t } = useI18n()
</script>

<template>
  <!-- Initialize Reason Modal -->
  <div
    v-if="props.vm.showInitReasonModal"
    class="modal-overlay"
    @pointerdown.self="props.vm.showInitReasonModal = false"
  >
    <div class="modal glass-panel" style="border-top: 4px solid var(--color-primary-500);">
      <div class="modal-header">
        <RotateCcw class="w-6 h-6" style="color: var(--color-primary-600);" />
        <span>{{ t('chat.init_reason_title') }}</span>
      </div>
      <div class="modal-form">
        <div class="form-group">
          <label for="initialize-initial-prompt">{{ t('chat.initial_prompt_label') }}</label>
          <textarea
            id="initialize-initial-prompt"
            v-model="props.vm.initPrompt"
            class="input-field textarea-field"
            rows="5"
            :placeholder="t('chat.initial_prompt_placeholder')"
          ></textarea>
        </div>
        <div class="form-group">
          <label>{{ t('chat.init_reason_label') }}</label>
          <input
            type="text"
            v-model="props.vm.initReason"
            :placeholder="t('chat.init_reason_placeholder')"
            class="input-field"
            @keyup.enter="props.vm.confirmInitialize"
          />
        </div>
        <div class="form-group">
          <label>{{ t('chat.task_skills_init_label') }}</label>
          <div class="init-skill-list">
            <div v-if="props.vm.initSkillOptionsLoading" class="init-skill-state">{{ t('common.loading') }}</div>
            <div v-else-if="props.vm.initSkillOptions.length === 0" class="init-skill-state">
              {{ t('chat.task_skills_empty') }}
            </div>
            <label v-else v-for="skill in props.vm.initSkillOptions" :key="skill.id" class="init-skill-item">
              <input v-model="props.vm.initSelectedSkillIds" type="checkbox" :value="skill.id" />
              <span class="init-skill-name">{{ skill.name }}</span>
              <span class="init-skill-meta">{{ skill.dimension }}</span>
            </label>
          </div>
          <div v-if="props.vm.deletedRuntimeSkillNamesForInitialize.length > 0" class="init-skill-deleted-warning">
            {{ t('chat.task_skills_deleted_runtime_warning', {
              names: props.vm.deletedRuntimeSkillNamesForInitialize.join(', ')
            }) }}
          </div>
        </div>
      </div>
      <div class="modal-actions">
        <button class="btn-secondary" @click="props.vm.showInitReasonModal = false">{{ t('common.cancel') }}</button>
        <button
          class="btn-primary"
          :disabled="props.vm.initSkillOptionsLoading || props.vm.taskRuntimeSkillsLoading"
          @click="props.vm.confirmInitialize"
        >
          {{ t('chat.init_reason_confirm') }}
        </button>
      </div>
    </div>
  </div>

  <!-- Deleted Runtime Skill Confirmation Modal -->
  <div
    v-if="props.vm.showDeletedRuntimeSkillConfirm"
    class="modal-overlay"
    @pointerdown.self="props.vm.cancelDeletedRuntimeSkillConfirm"
  >
    <div class="modal glass-panel warning-modal">
      <div class="modal-header warning">
        <AlertCircle class="w-6 h-6" />
        <span>{{ t('chat.task_skills_deleted_runtime_confirm_title') }}</span>
      </div>
      <p class="delete-desc">
        {{ t('chat.task_skills_deleted_runtime_confirm_desc', {
          names: props.vm.deletedRuntimeSkillNamesForInitialize.join(', ')
        }) }}
      </p>
      <div class="modal-actions">
        <button class="btn-secondary" @click="props.vm.cancelDeletedRuntimeSkillConfirm">
          {{ t('common.cancel') }}
        </button>
        <button class="btn-secondary" @click="props.vm.confirmInitializeWithDeletedRuntimeSkillDecision(false)">
          {{ t('chat.task_skills_deleted_runtime_discard') }}
        </button>
        <button class="btn-primary" @click="props.vm.confirmInitializeWithDeletedRuntimeSkillDecision(true)">
          {{ t('chat.task_skills_deleted_runtime_keep') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ─── 弹窗框架（仅本组件的表单式弹窗使用；确认类弹窗走 ConfirmActionModal） ─── */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  width: 90%;
  max-width: 500px;
  padding: var(--space-8);
  background-color: white;
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-2xl);
}
.modal-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.modal-header span {
  font-size: 1.2rem;
  font-weight: 700;
}
.modal-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #475569;
}
.input-field {
  padding: 10px 14px;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  font-family: inherit;
  font-size: 1rem;
  width: 100%;
  box-sizing: border-box;
}
.input-field:focus { border-color: var(--color-primary-500); outline: none; }
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-4);
}
.warning-modal { border-top: 4px solid #f59e0b; }
.modal-header.warning { color: #d97706; }
.delete-desc {
  font-size: 0.875rem;
  color: #475569;
  margin-bottom: var(--space-4);
}

/* ─── 初始化技能装配列表 ─── */
.init-skill-list {
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 10px;
  max-height: 220px;
  overflow: auto;
  background: #fff;
}

.init-skill-state {
  font-size: 0.85rem;
  color: #64748b;
  padding: 10px 12px;
}

.init-skill-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.5rem;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.init-skill-item:hover {
  background-color: #f0f9ff;
}

.init-skill-item input[type="checkbox"] {
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
}

.init-skill-item input[type="checkbox"]:hover {
  border-color: #38bdf8;
  background-color: #f0f9ff;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}

.init-skill-item input[type="checkbox"]:checked {
  border-color: #0ea5e9;
  background-color: #0ea5e9;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M2.5 7L5.5 10L11.5 4' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  box-shadow: 0 2px 4px rgba(14, 165, 233, 0.25);
}

.init-skill-name {
  font-size: 0.85rem;
  color: #0f172a;
  font-weight: 500;
}

.init-skill-meta {
  margin-left: auto;
  font-size: 0.75rem;
  color: #94a3b8;
}

.init-skill-deleted-warning {
  margin-top: 8px;
  padding: 8px 10px;
  border: 1px solid #fde68a;
  border-radius: var(--radius-sm);
  background: #fffbeb;
  color: #92400e;
  font-size: 0.8rem;
  line-height: 1.4;
}
</style>
