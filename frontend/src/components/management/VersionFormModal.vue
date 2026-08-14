<!--
VersionFormModal: create / edit product version form.
-->
<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import BaseSelect from '@/components/BaseSelect.vue'
import { createProductVersion, updateProductVersion } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { ProductVersion, ProductVersionStatus } from '@/types/management'

const props = defineProps<{
  show: boolean
  productId: string
  version?: ProductVersion | null
}>()

const emit = defineEmits<{
  (e: 'saved', version: ProductVersion): void
  (e: 'cancel'): void
}>()

const { t } = useI18n()

const isEdit = () => Boolean(props.version)

const form = reactive({
  version_no: '',
  status: 'PLANNED' as ProductVersionStatus,
  release_date: '',
  description: '',
})

const loading = ref(false)

const statusOptions = (): { label: string; value: ProductVersionStatus }[] => [
  { label: t('management.product.version_status_planned'), value: 'PLANNED' },
  { label: t('management.product.version_status_active'), value: 'ACTIVE' },
  { label: t('management.product.version_status_eol'), value: 'EOL' },
]

watch(() => props.show, (visible) => {
  if (!visible) return
  form.version_no = props.version?.version_no ?? ''
  form.status = props.version?.status ?? 'PLANNED'
  form.release_date = props.version?.release_date?.slice(0, 10) ?? ''
  form.description = props.version?.description ?? ''
})

const submit = async () => {
  if (!form.version_no.trim()) {
    ElMessage.warning(t('management.common.required'))
    return
  }

  loading.value = true
  try {
    const payload = {
      version_no: form.version_no.trim(),
      status: form.status,
      release_date: form.release_date || null,
      description: form.description.trim() || null,
    }
    let saved: ProductVersion
    if (props.version) {
      saved = await updateProductVersion(props.productId, props.version.id, payload)
    } else {
      saved = await createProductVersion(props.productId, payload)
    }
    emit('saved', saved)
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div v-if="show" class="mgmt-modal-overlay" @pointerdown.self="emit('cancel')">
    <div class="mgmt-modal glass-panel">
      <h3>{{ isEdit() ? $t('management.product.edit_version') : $t('management.product.add_version') }}</h3>

      <div class="mgmt-form-grid">
        <div class="mgmt-field">
          <label>{{ $t('management.product.version_no') }}</label>
          <input v-model="form.version_no" class="mgmt-input" type="text" />
        </div>
        <div class="mgmt-field">
          <label>{{ $t('management.common.status') }}</label>
          <BaseSelect v-model="form.status" :options="statusOptions()" />
        </div>
        <div class="mgmt-field full">
          <label>{{ $t('management.product.release_date') }}</label>
          <input v-model="form.release_date" class="mgmt-input" type="date" />
        </div>
        <div class="mgmt-field full">
          <label>{{ $t('management.common.description') }}</label>
          <textarea v-model="form.description" class="mgmt-input" rows="3"></textarea>
        </div>
      </div>

      <div class="mgmt-modal-actions">
        <button class="btn-secondary" :disabled="loading" @click="emit('cancel')">
          {{ $t('common.cancel') }}
        </button>
        <button class="btn-primary" :disabled="loading" @click="submit">
          {{ loading ? $t('management.common.saving') : $t('management.common.save') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
