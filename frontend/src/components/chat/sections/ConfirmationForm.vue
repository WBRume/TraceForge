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
const isApplicable = (field: ConfirmationField) => (field.when || []).every(condition => (
  condition.op === 'eq' ? values[condition.key] === condition.value : values[condition.key] !== condition.value
))
const visibleFields = computed(() => props.fields.filter(field => !field.hidden && isApplicable(field)))
const currentField = computed(() => visibleFields.value[questionIndex.value])
const pageFields = computed(() => currentField.value ? [currentField.value] : [])
const isLastQuestion = computed(() => questionIndex.value >= visibleFields.value.length - 1)
watch(() => visibleFields.value.length, count => {
  questionIndex.value = Math.min(questionIndex.value, Math.max(0, count - 1))
})

watch(() => props.fields, fields => {
  const keys = new Set(fields.map(field => field.key))
  for (const key of Object.keys(values)) {
    if (!keys.has(key)) {
      delete values[key]
      delete customChoices[key]
    }
  }
  for (const field of fields) {
    if (values[field.key] !== undefined) continue
    values[field.key] = field.default ?? (field.type === 'multiselect' ? [] : field.type === 'boolean' ? false : '')
  }
}, { immediate: true })

const isValid = (field: ConfirmationField): boolean => {
  if (field.type === 'external') return true
  const value = values[field.key]
  if (value === undefined || value === '' || (Array.isArray(value) && !value.length)) {
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
  const answer = Object.fromEntries(props.fields.filter(field => (
    field.type !== 'external' && isApplicable(field) && values[field.key] !== undefined
    && (values[field.key] !== '' || field.required)
  )).map(field => [field.key, values[field.key]]))
  emit('submit', JSON.stringify(answer))
}
</script>

<template>
  <form class="confirmation-form" @submit.prevent="submit">
    <p v-if="visibleFields.length" class="question-progress" role="status">
      {{ t('chat.questionnaire_progress', { current: questionIndex + 1, total: visibleFields.length }) }}
    </p>
    <fieldset v-for="field in pageFields" :key="field.key" class="confirmation-field">
      <legend class="field-title">{{ field.title || field.key }}<span v-if="field.required"> *</span></legend>
      <p v-if="field.description" class="field-description">{{ field.description }}</p>
      <template v-if="field.type === 'multiselect'">
        <label v-for="option in field.options" :key="option.value" class="field-choice">
          <input v-model="values[field.key]" type="checkbox" :value="option.value">
          <span>{{ option.label }}<small v-if="option.description">{{ option.description }}</small></span>
        </label>
        <label v-for="choice in extraChoices(field)" :key="choice" class="field-choice">
          <input v-model="values[field.key]" type="checkbox" :value="choice">
          {{ choice }}
        </label>
        <div v-if="field.custom" class="field-custom">
          <input v-model="customChoices[field.key]" class="field-input" type="text"
            :aria-label="`${field.title || field.key}…`" placeholder="…"
            @keydown.enter.prevent="addCustomChoice(field)">
          <button type="button" class="field-option" :aria-label="`${field.title || field.key}+`"
            @click="addCustomChoice(field)">+</button>
        </div>
      </template>
      <label v-else-if="field.type === 'boolean'" class="field-choice">
        <input v-model="values[field.key]" type="checkbox" :aria-label="field.title || field.key">
        {{ field.title || field.key }}
      </label>
      <a v-else-if="field.type === 'external'" :href="field.url" target="_blank" rel="noopener noreferrer">{{ field.title || field.key }}</a>
      <template v-else>
        <div v-if="field.options?.length" class="field-options">
          <button v-for="option in field.options" :key="option.value" type="button" class="field-option"
            :aria-pressed="values[field.key] === option.value" @click="values[field.key] = option.value">
            {{ option.label }}<small v-if="option.description">{{ option.description }}</small>
          </button>
        </div>
        <input v-if="field.type === 'string' && (field.custom || !field.options?.length)" v-model="values[field.key]"
          class="field-input" type="text" :aria-label="field.title || field.key"
          :placeholder="field.placeholder" :required="field.required" :minlength="field.minLength"
          :maxlength="field.maxLength" :pattern="field.pattern">
        <input v-if="field.type === 'number' || field.type === 'integer'" v-model.number="values[field.key]"
          class="field-input" type="number" :aria-label="field.title || field.key"
          :required="field.required" :min="field.minimum" :max="field.maximum"
          :step="field.type === 'integer' ? 1 : 'any'">
      </template>
    </fieldset>
    <div class="form-navigation">
      <button class="form-previous" type="button" :disabled="questionIndex === 0"
        @click="questionIndex -= 1">{{ t('chat.questionnaire_previous') }}</button>
      <button class="form-submit" type="submit" :disabled="!canContinue">
        {{ isLastQuestion ? submitLabel : t('chat.questionnaire_next') }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.confirmation-form { display: grid; gap: 16px; width: 100%; min-width: 0; color: inherit; }
.question-progress { font-size: 12px; opacity: .7; margin: 0; }
.confirmation-field { border: 0; padding: 0; margin: 0; min-width: 0; }
.field-title { font-weight: 600; font-size: 13px; margin-bottom: 8px; }
.field-description, .field-choice small, .field-option small { font-size: 12px; opacity: .7; }
.field-choice { display: flex; gap: 8px; align-items: start; margin: 8px 0; font-size: 13px; }
.field-choice small, .field-option small { display: block; margin-top: 3px; }
.field-options { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.field-custom { display: flex; gap: 6px; }
.field-option, .field-input { border: 1px solid #94a3b866; border-radius: 6px; background: transparent; color: inherit; padding: 8px 10px; font-size: 13px; }
.field-option { cursor: pointer; text-align: left; }
.field-option[aria-pressed="true"] { border-color: #3b82f6; background: #3b82f61a; }
.field-input { width: 100%; box-sizing: border-box; }
.form-submit { justify-self: start; border: 0; border-radius: 6px; padding: 8px 16px; background: #2563eb; color: white; cursor: pointer; }
.form-submit:disabled { opacity: .45; cursor: default; }
.form-navigation { display: flex; justify-content: space-between; gap: 12px; }
.form-previous { border: 1px solid #94a3b866; border-radius: 6px; padding: 8px 16px; background: transparent; color: inherit; cursor: pointer; }
.form-previous:disabled { opacity: .45; cursor: default; }
</style>
