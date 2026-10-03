<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertCircle } from '@/components/icons'
import { hitlOptionValue, hitlOptionLabel, confirmationPrompt } from '@/composables/chat/cards/presenters'
import type { HitlCard } from '@/composables/chat/types'
import ConfirmationForm from './ConfirmationForm.vue'

/**
 * HITL（Human-in-the-loop）交互卡（方案 1C：Claude / macOS 极简悬浮托盘质感）
 * 按钮采用 TraceForge 品牌科技蓝（#0284C7）与浅灰幽灵白底，严禁使用黑色。
 */
const props = defineProps<{
  card: HitlCard
}>()

const emit = defineEmits<{
  (event: 'submit', cardId: string, value: string): void
}>()

const { t } = useI18n()
const inputValue = ref(props.card.tempInput || '')
const prompt = computed(() => confirmationPrompt(props.card.prompt, props.card.hitl_type))

watch(() => props.card.id, () => {
  inputValue.value = props.card.tempInput || ''
})

const submit = (value: string) => {
  emit('submit', props.card.id, value)
}
</script>

<template>
  <div class="hitl-dock-container" data-testid="hitl-interaction-card">
    <!-- 1C 头部栏：琥珀指示环 + 标题与简要信息 + 紧凑操作按钮 -->
    <div class="dock-bar-row">
      <div class="dock-info-area">
        <div class="dock-indicator-ring">
          <AlertCircle class="w-4 h-4 text-amber-700" />
        </div>
        <div class="dock-text-group">
          <h4 class="dock-title">
            {{ t(props.card.hitl_type === 'form' ? 'chat.questionnaire_title' : 'chat.confirmation_title') }}
          </h4>
          <p v-if="prompt" class="dock-subtitle hitl-prompt">{{ prompt }}</p>
        </div>
      </div>

      <!-- Boolean 是非操作 -->
      <div v-if="props.card.hitl_type === 'boolean'" class="dock-buttons-group">
        <button class="btn-dock-pill-ghost" @click="submit('n')">
          {{ t('common.cancel') }} (N)
        </button>
        <button class="btn-dock-pill-primary" @click="submit('y')">
          {{ t('common.confirm') }} (Y)
        </button>
      </div>

      <!-- 纯文本快速提交 -->
      <div v-else-if="props.card.hitl_type !== 'form' && (!props.card.options || !props.card.options.length)" class="dock-buttons-group text-input-group">
        <input
          type="text"
          v-model="inputValue"
          placeholder="..."
          class="modern-text-input"
          @keyup.enter="submit(inputValue)"
        >
        <button class="btn-dock-pill-primary" @click="submit(inputValue)">
          {{ t('common.confirm') }}
        </button>
      </div>
    </div>

    <!-- 上下文附注代码块 -->
    <div v-if="props.card.context" class="dock-context-panel">
      <div class="context-box">
        <code>{{ props.card.context }}</code>
      </div>
    </div>

    <!-- 1C Select 场景：横向多策略卡组 -->
    <div v-if="props.card.hitl_type === 'select' && props.card.options?.length" class="dock-select-panel">
      <div class="dock-select-cards-grid">
        <button
          v-for="(option, index) in props.card.options"
          :key="`${props.card.id}-option-${index}`"
          type="button"
          class="dock-select-card"
          @click="submit(hitlOptionValue(option))"
        >
          <div class="dock-select-card-head">
            <span class="card-option-label">{{ hitlOptionLabel(option) }}</span>
            <span class="dock-tag-mini">#{{ index + 1 }}</span>
          </div>
        </button>
      </div>
    </div>

    <!-- 1C Form 场景：结构化问卷抽屉 -->
    <div v-if="props.card.hitl_type === 'form' && props.card.fields?.length" class="dock-form-drawer">
      <ConfirmationForm
        :fields="props.card.fields"
        :submit-label="t('chat.questionnaire_submit')"
        @submit="submit"
      />
    </div>
  </div>
</template>

<style scoped>
/* 方案 1C：Claude / macOS 极简悬浮托盘 */
.hitl-dock-container {
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: var(--radius-xl, 16px);
  box-shadow: 0 8px 30px -4px rgba(15, 23, 42, 0.08);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: all 160ms cubic-bezier(0.4, 0, 0.2, 1);
}

.dock-bar-row {
  padding: 12px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.dock-info-area {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.dock-indicator-ring {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #FEF3C7;
  color: #B45309;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.dock-text-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.dock-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--color-text-title, #0F172A);
  letter-spacing: -0.01em;
}

.dock-subtitle {
  margin: 0;
  font-size: 11.5px;
  color: var(--color-text-muted, #64748B);
  font-family: var(--font-body, sans-serif);
  line-height: 1.4;
}

.dock-buttons-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.text-input-group {
  flex: 1;
  max-width: 320px;
}

/* 核心要求：主操作按钮使用品牌科技蓝 (#0284C7)，绝不使用黑色 */
.btn-dock-pill-primary {
  background: #0284C7;
  color: #FFFFFF;
  border: none;
  padding: 6px 18px;
  border-radius: var(--radius-full, 9999px);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: all 160ms cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(2, 132, 199, 0.25);
  white-space: nowrap;
}

.btn-dock-pill-primary:hover {
  background: #0369A1;
  box-shadow: 0 4px 10px rgba(2, 132, 199, 0.35);
  transform: translateY(-0.5px);
}

.btn-dock-pill-primary:active {
  transform: translateY(0);
}

.btn-dock-pill-ghost {
  background: #F1F5F9;
  color: var(--color-text-body, #334155);
  border: 1px solid var(--border-subtle, #E2E8F0);
  padding: 6px 14px;
  border-radius: var(--radius-full, 9999px);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 160ms cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
}

.btn-dock-pill-ghost:hover {
  background: #E2E8F0;
  color: var(--color-text-title, #0F172A);
  border-color: #CBD5E1;
}

.modern-text-input {
  width: 100%;
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-full, 9999px);
  padding: 6px 12px;
  font-size: 12px;
  color: var(--color-text-title, #0F172A);
  outline: none;
  transition: all 160ms cubic-bezier(0.4, 0, 0.2, 1);
}

.modern-text-input:focus {
  background: #FFFFFF;
  border-color: #0284C7;
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.15);
}

.dock-context-panel {
  padding: 0 18px 8px;
}

.context-box {
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
  padding: 8px 12px;
  border-radius: var(--radius-md, 8px);
  font-size: 11.5px;
  font-family: var(--font-mono, monospace);
  color: #334155;
  line-height: 1.5;
  overflow-x: auto;
}

/* 1C - Select 场景：横向多选项卡托盘 */
.dock-select-panel {
  padding: 0 18px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dock-select-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
}

.dock-select-card {
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-lg, 12px);
  padding: 10px 14px;
  cursor: pointer;
  transition: all 160ms cubic-bezier(0.4, 0, 0.2, 1);
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.dock-select-card:hover {
  background: #F0F9FF;
  border-color: #BAE6FD;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(2, 132, 199, 0.1);
}

.dock-select-card:active {
  transform: translateY(0);
}

.dock-select-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-option-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--color-text-title, #0F172A);
}

.dock-tag-mini {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #E0F2FE;
  color: #0369A1;
  font-weight: 600;
  font-family: var(--font-mono, monospace);
}

/* 1C - Form 场景：结构化问卷抽屉 */
.dock-form-drawer {
  padding: 0 18px 16px;
  border-top: 1px solid #F1F5F9;
  padding-top: 12px;
}
</style>
