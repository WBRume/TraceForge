<!-- Tag/branch selector with remote validation, shared by product binding,
     project repo association and release custom repos. -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircle2, XCircle, Loader2 } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import { validateRepositoryRef } from '@/services/managementApi'
import type { RepoRefType } from '@/types/management'

const props = defineProps<{
  modelValue: { ref_type: RepoRefType; ref_name: string }
  repositoryId: string | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: { ref_type: RepoRefType; ref_name: string }): void
}>()

const { t } = useI18n()

const typeOptions = computed(() => [
  { label: t('management.product.ref_branch'), value: 'BRANCH' },
  { label: t('management.product.ref_tag'), value: 'TAG' },
])

const validating = ref(false)
const validationState = ref<'idle' | 'success' | 'error'>('idle')
const validationMessage = ref('')

const onTypeChange = (value: RepoRefType) => {
  validationState.value = 'idle'
  emit('update:modelValue', { ...props.modelValue, ref_type: value })
}

const onNameChange = (event: Event) => {
  const value = (event.target as HTMLInputElement).value
  validationState.value = 'idle'
  emit('update:modelValue', { ...props.modelValue, ref_name: value })
}

const validate = async () => {
  if (!props.repositoryId || !props.modelValue.ref_name.trim()) return
  validating.value = true
  validationState.value = 'idle'
  try {
    await validateRepositoryRef(props.repositoryId, {
      ref_type: props.modelValue.ref_type,
      ref_name: props.modelValue.ref_name.trim(),
    })
    validationState.value = 'success'
    validationMessage.value = t('management.product.validate_ref_success', { ref: props.modelValue.ref_name.trim() })
  } catch (error: unknown) {
    validationState.value = 'error'
    validationMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    validating.value = false
  }
}

watch(
  () => [props.repositoryId, props.modelValue.ref_type, props.modelValue.ref_name],
  () => {
    validationState.value = 'idle'
    validationMessage.value = ''
  },
)
</script>

<template>
  <div class="ref-input">
    <div class="ref-input-row">
      <div class="ref-type">
        <BaseSelect
          :model-value="modelValue.ref_type"
          :options="typeOptions"
          :disabled="!repositoryId"
          @update:model-value="onTypeChange"
        />
      </div>
      <input
        :value="modelValue.ref_name"
        type="text"
        class="mgmt-input ref-name"
        :disabled="!repositoryId"
        :placeholder="$t('management.product.ref_placeholder')"
        @input="onNameChange"
      />
      <button
        type="button"
        class="btn-secondary ref-validate-btn"
        :disabled="!repositoryId || !modelValue.ref_name.trim() || validating"
        :title="$t('management.product.validate_ref')"
        @click="validate"
      >
        <Loader2 v-if="validating" class="w-4 h-4 spin" />
        <CheckCircle2 v-else class="w-4 h-4" />
      </button>
    </div>
    <div v-if="validationState === 'success'" class="ref-validation success">
      <CheckCircle2 class="w-3.5 h-3.5" /> {{ validationMessage }}
    </div>
    <div v-else-if="validationState === 'error'" class="ref-validation error">
      <XCircle class="w-3.5 h-3.5" /> {{ validationMessage }}
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.ref-input {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  width: 100%;
}

.ref-input-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.ref-type {
  width: 130px;
  flex-shrink: 0;
}

.ref-name {
  flex: 1;
  min-width: 0;
}

.ref-validate-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.45rem 0.7rem;
  flex-shrink: 0;
}

.ref-validation {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.74rem;
}

.ref-validation.success {
  color: #15803d;
}

.ref-validation.error {
  color: #b91c1c;
  word-break: break-all;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
