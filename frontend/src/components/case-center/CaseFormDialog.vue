<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Loader2, FilePlus2 } from 'lucide-vue-next'

const props = defineProps<{
  visible: boolean
  saving: boolean
  model: any
  isEdit: boolean
}>()

const emit = defineEmits<{
  close: []
  save: []
}>()

const { t } = useI18n()

const categoryOptions = ['PUBLIC', 'PRODUCT', 'SITE', 'TEMPORARY']
const priorityOptions = ['P0', 'P1', 'P2', 'P3']
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="isEdit ? t('case_center.edit_title') : t('case_center.create_title')"
    width="720px"
    top="6vh"
    :close-on-click-modal="false"
    @close="emit('close')"
  >
    <div class="case-form">
      <div class="form-row">
        <div class="form-field field-grow">
          <label>{{ t('case_center.field.title') }} <span class="required">*</span></label>
          <el-input v-model="model.title" maxlength="300" :placeholder="t('case_center.placeholder.title')" />
        </div>
      </div>

      <div class="form-row three-col">
        <div class="form-field">
          <label>{{ t('case_center.field.category') }}</label>
          <el-select v-model="model.category" class="field-full">
            <el-option v-for="c in categoryOptions" :key="c" :label="t(`case_center.category.${c}`)" :value="c" />
          </el-select>
        </div>
        <div class="form-field">
          <label>{{ t('case_center.field.priority') }}</label>
          <el-select v-model="model.priority" class="field-full">
            <el-option v-for="p in priorityOptions" :key="p" :label="p" :value="p" />
          </el-select>
        </div>
        <div class="form-field">
          <label>{{ t('case_center.field.site_name') }}</label>
          <el-input v-model="model.site_name" maxlength="200" :placeholder="t('case_center.placeholder.site_name')" />
        </div>
      </div>

      <div class="form-row two-col">
        <div class="form-field">
          <label>{{ t('case_center.field.product_name') }}</label>
          <el-input v-model="model.product_name" maxlength="200" :placeholder="t('case_center.placeholder.product_name')" />
        </div>
        <div class="form-field">
          <label>{{ t('case_center.field.product_version') }}</label>
          <el-input v-model="model.product_version" maxlength="100" :placeholder="t('case_center.placeholder.product_version')" />
        </div>
      </div>

      <div class="form-row">
        <div class="form-field field-grow">
          <label>{{ t('case_center.field.problem_description') }} <span class="required">*</span></label>
          <el-input v-model="model.problem_description" type="textarea" :rows="3" :placeholder="t('case_center.placeholder.problem_description')" />
        </div>
      </div>

      <div class="form-row">
        <div class="form-field field-grow">
          <label>{{ t('case_center.field.code_context') }}</label>
          <el-input v-model="model.code_context" type="textarea" :rows="2" :placeholder="t('case_center.placeholder.code_context')" />
        </div>
      </div>

      <div class="form-row">
        <div class="form-field field-grow">
          <label>{{ t('case_center.field.analysis_process') }}</label>
          <el-input v-model="model.analysis_process" type="textarea" :rows="3" :placeholder="t('case_center.placeholder.analysis_process')" />
        </div>
      </div>

      <div class="form-row two-col">
        <div class="form-field">
          <label>{{ t('case_center.field.root_cause') }}</label>
          <el-input v-model="model.root_cause" type="textarea" :rows="2" :placeholder="t('case_center.placeholder.root_cause')" />
        </div>
        <div class="form-field">
          <label>{{ t('case_center.field.solution') }}</label>
          <el-input v-model="model.solution" type="textarea" :rows="2" :placeholder="t('case_center.placeholder.solution')" />
        </div>
      </div>
    </div>

    <template #footer>
      <el-button :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" @click="emit('save')">
        <Loader2 v-if="false" class="w-4 h-4" />
        <FilePlus2 class="w-4 h-4" />
        {{ t('common.save') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.case-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-row {
  display: flex;
  gap: 14px;
}

.form-row.two-col > .form-field {
  flex: 1;
  min-width: 0;
}

.form-row.three-col > .form-field {
  flex: 1;
  min-width: 0;
}

.field-grow {
  flex: 1;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-field label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #334155;
}

.required {
  color: #ef4444;
}

.field-full {
  width: 100%;
}
</style>
