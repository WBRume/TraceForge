<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { createProject, updateProject } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { Project } from '@/types/management'

const props = withDefaults(defineProps<{
  show: boolean;
  project?: Project | null;
}>(), {
  project: null,
})

const emit = defineEmits<{
  (e: 'saved', project: Project): void;
  (e: 'cancel'): void;
}>()

const { t } = useI18n()

const isEditing = computed(() => Boolean(props.project?.id))

const form = reactive<{
  name: string;
  code: string;
  customer: string;
  description: string;
}>({
  name: '',
  code: '',
  customer: '',
  description: '',
})

const saving = ref(false)

const resetForm = () => {
  form.name = props.project?.name ?? ''
  form.code = props.project?.code ?? ''
  form.customer = props.project?.customer ?? ''
  form.description = props.project?.description ?? ''
}

watch(() => props.show, (visible) => {
  if (visible) {
    resetForm()
  }
})

const canSubmit = computed(
  () => form.name.trim().length > 0 && form.code.trim().length > 0 && !saving.value
)

const toNullable = (value: string): string | null => (value.trim().length > 0 ? value.trim() : null)

const handleSave = async () => {
  if (!canSubmit.value) {
    ElMessage.error(t('management.common.required'))
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      code: form.code.trim(),
      customer: toNullable(form.customer),
      description: toNullable(form.description),
    }
    if (isEditing.value) {
      const updated = await updateProject(props.project!.id, payload)
      emit('saved', updated)
    } else {
      const created = await createProject(payload)
      emit('saved', created)
    }
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    saving.value = false
  }
}

const handleCancel = () => {
  if (saving.value) return
  emit('cancel')
}
</script>

<template>
  <div v-if="show" class="mgmt-modal-overlay" @click.self="handleCancel">
    <div class="mgmt-modal glass-panel">
      <h3>{{ isEditing ? $t('management.project.edit') : $t('management.project.create') }}</h3>

      <div class="mgmt-form-grid">
        <div class="mgmt-field">
          <label>{{ $t('management.project.name') }}</label>
          <input v-model="form.name" class="mgmt-input" type="text" />
        </div>

        <div class="mgmt-field">
          <label>{{ $t('management.project.code') }}</label>
          <input v-model="form.code" class="mgmt-input" type="text" />
        </div>

        <div class="mgmt-field">
          <label>{{ $t('management.project.customer') }}</label>
          <input v-model="form.customer" class="mgmt-input" type="text" />
        </div>

        <div class="mgmt-field full">
          <label>{{ $t('management.project.description') }}</label>
          <textarea v-model="form.description" class="mgmt-input" rows="3"></textarea>
        </div>
      </div>

      <div class="mgmt-modal-actions">
        <button class="btn-secondary" :disabled="saving" @click="handleCancel">
          {{ $t('common.cancel') }}
        </button>
        <button class="btn-primary" :disabled="!canSubmit" @click="handleSave">
          {{ saving ? $t('common.saving') : $t('common.save') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
