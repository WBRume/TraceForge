<script setup lang="ts">
import { computed, reactive, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ConfirmationField, ConfirmationValue } from '@/composables/chat/types'

const props = defineProps<{
  fields: ConfirmationField[]
  submitLabel: string
}>()
const emit = defineEmits<{ (event: 'submit', response: string): void }>()
const { t } = useI18n()
const questionIndex = shallowRef(0)
const values = reactive<Record<string, ConfirmationValue | undefined>>({})
const customChoices = reactive<Record<string, string>>({})
const supportsCustomInput = (field: ConfirmationField) => field.custom !== false
  && (field.type === 'multiselect' || (field.type === 'string' && !!field.options?.length))

const answerValue = (field: ConfirmationField): ConfirmationValue | undefined => {
  const value = values[field.key]
  const custom = customChoices[field.key]?.trim()
  if (!supportsCustomInput(field) || !custom) return value
  if (Array.isArray(value)) return value.includes(custom) ? value : [...value, custom]
  return typeof value === 'string' && value ? `${value}\n${custom}` : custom
}

const parseOption = (label: string) => {
  const match = label.match(/^(.*?)\s*[（(](推荐|建议|低风险|核心|稳定|快照\s*v[\d.]+|离线模式|Prod|Staging|Dev|高风险)[）)]\s*$/i)
  if (match) {
    return {
      title: match[1].trim(),
      badge: match[2].trim()
    }
  }
  return { title: label, badge: null }
}

const isApplicable = (field: ConfirmationField) => (field.when || []).every(condition => {
  const source = props.fields.find(candidate => candidate.key === condition.key)
  const value = source?.type === 'string' && supportsCustomInput(source) && !values[condition.key]
    ? customChoices[condition.key]?.trim() || values[condition.key]
    : values[condition.key]
  return condition.op === 'eq' ? value === condition.value : value !== condition.value
})
const visibleFields = computed(() => props.fields.filter(field => !field.hidden && isApplicable(field)))
const currentField = computed(() => visibleFields.value[questionIndex.value])
const pageFields = computed(() => currentField.value ? [currentField.value] : [])
const isLastQuestion = computed(() => questionIndex.value >= visibleFields.value.length - 1)
watch(() => visibleFields.value.length, count => {
  questionIndex.value = Math.min(questionIndex.value, Math.max(0, count - 1))
})

watch(() => props.fields, fields => {
  const keys = new Set(fields.map(field => field.key))
  for (const key of new Set([...Object.keys(values), ...Object.keys(customChoices)])) {
    if (!keys.has(key)) {
      delete values[key]
      delete customChoices[key]
    }
  }
  for (const field of fields) {
    if (values[field.key] !== undefined) continue
    const defaultValue = field.default ?? (field.type === 'multiselect' ? [] : field.type === 'boolean' ? false : '')
    if (field.type === 'string' && supportsCustomInput(field) && typeof defaultValue === 'string'
      && !field.options?.some(option => option.value === defaultValue)) {
      customChoices[field.key] = defaultValue
      values[field.key] = ''
    } else {
      values[field.key] = defaultValue
    }
  }
}, { immediate: true })

const isValid = (field: ConfirmationField): boolean => {
  if (field.type === 'external') return true
  const value = answerValue(field)
  if (value === undefined || (typeof value === 'string' && !value.trim()) || (Array.isArray(value) && !value.length)) {
    return !field.required && !(field.type === 'multiselect' && field.minItems)
  }
  if (field.type === 'multiselect') {
    return Array.isArray(value) && value.length >= (field.minItems ?? 0)
      && value.length <= (field.maxItems ?? Infinity)
  }
  if (field.type === 'number' || field.type === 'integer') {
    return typeof value === 'number' && Number.isFinite(value)
      && (field.type !== 'integer' || Number.isInteger(value))
      && value >= (field.minimum ?? -Infinity) && value <= (field.maximum ?? Infinity)
  }
  if (field.type === 'boolean') return typeof value === 'boolean'
  return typeof value === 'string' && value.length >= (field.minLength ?? 0)
    && value.length <= (field.maxLength ?? Infinity)
}
const canContinue = computed(() => !currentField.value || isValid(currentField.value))

const addCustomChoice = (field: ConfirmationField) => {
  const choice = customChoices[field.key]?.trim()
  const selected = values[field.key]
  if (!choice || !Array.isArray(selected)) return
  if (!selected.includes(choice)) values[field.key] = [...selected, choice]
  customChoices[field.key] = ''
}
const extraChoices = (field: ConfirmationField): string[] => {
  const selected = values[field.key]
  return Array.isArray(selected) ? selected.filter(value => !field.options?.some(option => option.value === value)) : []
}
const isChoiceSelected = (field: ConfirmationField, choice: string) => {
  const selected = values[field.key]
  return Array.isArray(selected) && selected.includes(choice)
}

const submit = () => {
  if (!canContinue.value) return
  if (!isLastQuestion.value) {
    questionIndex.value += 1
    return
  }
  const invalidIndex = visibleFields.value.findIndex(field => !isValid(field))
  if (invalidIndex >= 0) {
    questionIndex.value = invalidIndex
    return
  }
  const answer = Object.fromEntries(props.fields
    .filter(field => field.type !== 'external' && isApplicable(field))
    .map(field => [field.key, answerValue(field)] as const)
    .filter(([, value]) => value !== undefined && (typeof value !== 'string' || !!value.trim())))
  emit('submit', JSON.stringify(answer))
}
</script>

<template>
  <form class="confirmation-form" @submit.prevent="submit">
    <!-- 方案 1C 风格步进与进度条 -->
    <div v-if="visibleFields.length" class="dock-form-progress-bar" role="status">
      <span class="question-progress">
        {{ t('chat.questionnaire_progress', { current: questionIndex + 1, total: visibleFields.length }) }}
      </span>
      <div v-if="visibleFields.length > 1 && visibleFields.length <= 12" class="dock-step-dots" aria-hidden="true">
        <span
          v-for="step in visibleFields.length"
          :key="step"
          class="dock-step-dot"
          :class="{ active: step - 1 === questionIndex, completed: step - 1 < questionIndex }"
        />
      </div>
    </div>

    <fieldset v-for="field in pageFields" :key="field.key" class="confirmation-field">
      <legend class="field-title">
        {{ field.title || field.key }}<span v-if="field.required" class="required-indicator"> *</span>
      </legend>
      <p v-if="field.description" class="field-description">{{ field.description }}</p>

      <!-- Multiselect 多选场景 -->
      <template v-if="field.type === 'multiselect'">
        <div class="dock-checkbox-cards-grid">
          <label
            v-for="option in field.options"
            :key="option.value"
            class="field-choice dock-choice-card"
            :class="{ 'is-checked': isChoiceSelected(field, option.value) }"
          >
            <input v-model="values[field.key]" type="checkbox" :value="option.value" class="modern-checkbox">
            <div class="choice-text-col">
              <span class="choice-main-text">{{ option.label }}</span>
              <small v-if="option.description" class="choice-sub-text">{{ option.description }}</small>
            </div>
          </label>
          <label
            v-for="choice in extraChoices(field)"
            :key="choice"
            class="field-choice dock-choice-card is-checked"
          >
            <input v-model="values[field.key]" type="checkbox" :value="choice" class="modern-checkbox">
            <span class="choice-main-text">{{ choice }}</span>
          </label>
        </div>
        <div v-if="supportsCustomInput(field)" class="field-custom custom-input-row">
          <input
            v-model="customChoices[field.key]"
            class="field-input modern-text-input"
            type="text"
            :aria-label="`${field.title || field.key}：${t('chat.questionnaire_custom_label')}`"
            :placeholder="field.placeholder || t('chat.questionnaire_custom_placeholder')"
            @keydown.enter.prevent="addCustomChoice(field)"
          >
          <button
            type="button"
            class="field-option btn-dock-pill-ghost custom-add-btn"
            :aria-label="`${field.title || field.key}+`"
            @click="addCustomChoice(field)"
          >+</button>
        </div>
      </template>

      <!-- Boolean 是非开关场景 -->
      <label
        v-else-if="field.type === 'boolean'"
        class="field-choice dock-choice-card boolean-card"
        :class="{ 'is-checked': values[field.key] === true }"
      >
        <input
          v-model="values[field.key]"
          type="checkbox"
          :aria-label="field.title || field.key"
          class="modern-checkbox"
        >
        <span class="choice-main-text">{{ field.title || field.key }}</span>
      </label>

      <!-- External 链接 -->
      <a v-else-if="field.type === 'external'" :href="field.url" target="_blank" rel="noopener noreferrer" class="dock-link">
        {{ field.title || field.key }}
      </a>

      <!-- 单选 Options / 文本 / 数字 -->
      <template v-else>
        <!-- 方案 1C 风格卡片网格 -->
        <div v-if="field.options?.length" class="field-options dock-select-cards-grid">
          <button
            v-for="option in field.options"
            :key="option.value"
            type="button"
            class="field-option dock-select-card"
            :class="{ 'is-selected': values[field.key] === option.value }"
            :aria-pressed="values[field.key] === option.value"
            @click="values[field.key] = values[field.key] === option.value ? '' : option.value"
          >
            <div class="dock-select-card-head">
              <span class="card-option-label">{{ parseOption(option.label).title }}</span>
              <span v-if="parseOption(option.label).badge" class="dock-tag-mini">
                {{ parseOption(option.label).badge }}
              </span>
            </div>
            <div v-if="option.description" class="dock-select-card-desc">
              {{ option.description }}
            </div>
          </button>
        </div>

        <!-- 每题共用一个输入框，保留所选答案并允许补充或直接自定义。 -->
        <label v-if="field.type === 'string' && supportsCustomInput(field)" class="input-wrapper-row custom-answer-input">
          <span class="custom-answer-label">{{ t('chat.questionnaire_custom_label') }}</span>
          <input
            v-model="customChoices[field.key]"
            class="field-input modern-text-input"
            type="text"
            :aria-label="`${field.title || field.key}：${t('chat.questionnaire_custom_label')}`"
            :placeholder="field.placeholder || t('chat.questionnaire_custom_placeholder')"
            :maxlength="field.maxLength"
          >
        </label>

        <!-- 无预设选项时直接填写答案。 -->
        <div
          v-if="field.type === 'string' && !field.options?.length"
          class="input-wrapper-row"
        >
          <input
            v-model="values[field.key]"
            class="field-input modern-text-input"
            type="text"
            :aria-label="field.title || field.key"
            :placeholder="field.placeholder || '...'"
            :required="field.required"
            :minlength="field.minLength"
            :maxlength="field.maxLength"
            :pattern="field.pattern"
          >
        </div>

        <!-- 数字输入 -->
        <div v-if="field.type === 'number' || field.type === 'integer'" class="input-wrapper-row">
          <input
            v-model.number="values[field.key]"
            class="field-input modern-text-input"
            type="number"
            :aria-label="field.title || field.key"
            :required="field.required"
            :min="field.minimum"
            :max="field.maximum"
            :step="field.type === 'integer' ? 1 : 'any'"
          >
        </div>
      </template>
    </fieldset>

    <!-- 方案 1C 风格胶囊药丸导航按钮行 -->
    <div class="form-navigation">
      <button
        class="form-previous btn-dock-pill-ghost"
        type="button"
        :disabled="questionIndex === 0"
        @click="questionIndex -= 1"
      >
        {{ t('chat.questionnaire_previous') }}
      </button>
      <button
        class="form-submit btn-dock-pill-primary"
        type="submit"
        :disabled="!canContinue"
      >
        {{ isLastQuestion ? submitLabel : t('chat.questionnaire_next') }}
      </button>
    </div>
  </form>
</template>

<style scoped>
/* 方案 1C：macOS / Claude 级结构化表单与卡片视觉 */
.confirmation-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
  min-width: 0;
  color: var(--color-text-body, #334155);
}

/* 进度步进条 */
.dock-form-progress-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 2px;
}

.question-progress {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--color-text-muted, #64748B);
  font-family: var(--font-mono, monospace);
  margin: 0;
  letter-spacing: -0.01em;
}

.dock-step-dots {
  display: flex;
  align-items: center;
  gap: 5px;
}

.dock-step-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #E2E8F0;
  transition: all 160ms ease;
}

.dock-step-dot.completed {
  background: #BAE6FD;
}

.dock-step-dot.active {
  background: #0284C7;
  transform: scale(1.25);
}

/* 字段区域 */
.confirmation-field {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-title {
  font-weight: 600;
  font-size: 13.5px;
  color: var(--color-text-title, #0F172A);
  margin-bottom: 2px;
  padding: 0;
}

.required-indicator {
  color: #EF4444;
  margin-left: 2px;
}

.field-description {
  font-size: 12px;
  color: var(--color-text-muted, #64748B);
  margin: 0;
  line-height: 1.5;
}

/* 1C - 选项卡片网格 */
.dock-select-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 8px;
  margin-top: 2px;
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
  gap: 4px;
  box-sizing: border-box;
}

.dock-select-card:hover {
  background: #F0F9FF;
  border-color: #BAE6FD;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(2, 132, 199, 0.08);
}

.dock-select-card:active {
  transform: translateY(0);
}

.dock-select-card.is-selected,
.dock-select-card[aria-pressed="true"] {
  background: #F0F9FF;
  border-color: #0284C7;
  box-shadow: 0 0 0 1.5px #0284C7;
}

.dock-select-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-option-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--color-text-title, #0F172A);
  line-height: 1.3;
}

.dock-select-card.is-selected .card-option-label,
.dock-select-card[aria-pressed="true"] .card-option-label {
  color: #0369A1;
}

.dock-tag-mini {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #E0F2FE;
  color: #0369A1;
  font-weight: 600;
  white-space: nowrap;
}

.dock-select-card-desc {
  font-size: 11px;
  color: var(--color-text-muted, #64748B);
  line-height: 1.4;
}

/* 多选卡片组 */
.dock-checkbox-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 8px;
}

.dock-choice-card {
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-lg, 12px);
  padding: 10px 14px;
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  transition: all 160ms cubic-bezier(0.4, 0, 0.2, 1);
  margin: 0;
}

.dock-choice-card:hover {
  background: #F0F9FF;
  border-color: #BAE6FD;
}

.dock-choice-card.is-checked {
  background: #F0F9FF;
  border-color: #0284C7;
  box-shadow: 0 0 0 1px #0284C7;
}

.boolean-card {
  padding: 10px 14px;
  display: inline-flex;
  width: auto;
  align-self: flex-start;
}

.modern-checkbox {
  accent-color: #0284C7;
  width: 15px;
  height: 15px;
  margin-top: 2px;
  cursor: pointer;
}

.choice-text-col {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.choice-main-text {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--color-text-title, #0F172A);
}

.choice-sub-text {
  font-size: 11px;
  color: var(--color-text-muted, #64748B);
}

/* 输入框 */
.input-wrapper-row {
  margin-top: 4px;
}

.custom-answer-input {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.custom-answer-label {
  font-size: 12px;
  color: var(--color-text-muted, #64748B);
}

.modern-text-input {
  width: 100%;
  box-sizing: border-box;
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md, 8px);
  padding: 8px 14px;
  font-size: 12.5px;
  color: var(--color-text-title, #0F172A);
  outline: none;
  transition: all 160ms cubic-bezier(0.4, 0, 0.2, 1);
  font-family: inherit;
}

.modern-text-input:focus {
  background: #FFFFFF;
  border-color: #0284C7;
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.15);
}

.custom-input-row {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}

.custom-add-btn {
  width: 34px;
  height: 34px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}

.dock-link {
  color: #0284C7;
  font-size: 12.5px;
  text-decoration: underline;
}

/* 底部胶囊药丸导航操作行 */
.form-navigation {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding-top: 10px;
  border-top: 1px solid #F1F5F9;
  margin-top: 4px;
}

/* 核心：品牌科技蓝主按钮，圆角胶囊药丸 */
.btn-dock-pill-primary {
  background: #0284C7;
  color: #FFFFFF;
  border: none;
  padding: 7px 20px;
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

.btn-dock-pill-primary:hover:not(:disabled) {
  background: #0369A1;
  box-shadow: 0 4px 10px rgba(2, 132, 199, 0.35);
  transform: translateY(-0.5px);
}

.btn-dock-pill-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
}

/* 浅灰幽灵次按钮，圆角胶囊药丸 */
.btn-dock-pill-ghost {
  background: #F1F5F9;
  color: var(--color-text-body, #334155);
  border: 1px solid var(--border-subtle, #E2E8F0);
  padding: 7px 16px;
  border-radius: var(--radius-full, 9999px);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 160ms cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
}

.btn-dock-pill-ghost:hover:not(:disabled) {
  background: #E2E8F0;
  color: var(--color-text-title, #0F172A);
  border-color: #CBD5E1;
}

.btn-dock-pill-ghost:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
