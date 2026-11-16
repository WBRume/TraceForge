<script setup lang="ts">
import { reactive, shallowRef, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import type { RequirementTaskLinkPayload, RequirementTaskRelation } from '@/types/workspaceAssets'

const props = defineProps<{
  options: { label: string; value: string }[]
  pendingAcceptance: boolean
  send: (payload: RequirementTaskLinkPayload) => Promise<boolean>
}>()

const open = defineModel<boolean>({ required: true })
const { t } = useI18n()
const formId = useId()
const submitting = shallowRef(false)
const failed = shallowRef(false)
const relations = [
  { value: 'COVERS', labelKey: 'covers_short', descriptionKey: 'covers_desc' },
  { value: 'RELATES_TO', labelKey: 'relates_to_short', descriptionKey: 'relates_to_desc' },
] as const

const form = reactive({
  taskId: '',
  relation: 'COVERS' as RequirementTaskRelation,
  reason: '',
})

watch(open, (visible) => {
  if (!visible) return
  form.taskId = ''
  form.relation = 'COVERS'
  form.reason = ''
  failed.value = false
})

async function submit() {
  if (submitting.value || !props.options.some(task => task.value === form.taskId)) return
  submitting.value = true
  failed.value = false
  try {
    const saved = await props.send({
      task_id: form.taskId,
      relation_type: form.relation,
      change_reason: form.reason.trim() || null,
    })
    if (saved) open.value = false
    else failed.value = true
  } catch {
    failed.value = true
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="open"
    :title="t('workspace_assets.requirements.link_task_modal.title')"
    width="min(480px, calc(100vw - 32px))"
    append-to-body
    destroy-on-close
    :show-close="!submitting"
    :close-on-click-modal="!submitting"
    :close-on-press-escape="!submitting"
  >
    <form :id="formId" class="task-link-form" @submit.prevent="submit">
      <template v-if="options.length">
        <div class="link-field">
          <span class="field-label">{{ t('workspace_assets.requirements.link_task_modal.select_task_label') }}</span>
          <BaseSelect
            v-model="form.taskId"
            :options="options"
            :aria-label="t('workspace_assets.requirements.link_task_modal.select_task_label')"
            :placeholder="t('workspace_assets.requirements.link_task_modal.select_task_placeholder')"
            :search-placeholder="t('workspace_assets.requirements.link_task_modal.search_task_placeholder')"
            :disabled="submitting"
            searchable
          />
        </div>

        <fieldset class="relation-field" :disabled="submitting">
          <legend class="field-label">{{ t('workspace_assets.requirements.link_task_modal.relation_type_label') }}</legend>
          <label v-for="relation in relations" :key="relation.value" class="relation-option" :class="{ selected: form.relation === relation.value }">
            <input v-model="form.relation" :name="formId" type="radio" :value="relation.value">
            <span>
              <strong>{{ t(`workspace_assets.requirements.relation_types.${relation.labelKey}`) }}</strong>
              <span class="option-description">{{ t(`workspace_assets.requirements.relation_types.${relation.descriptionKey}`) }}</span>
            </span>
          </label>
        </fieldset>

        <el-alert
          v-if="pendingAcceptance && form.relation === 'COVERS'"
          :title="t('workspace_assets.requirements.task_links.review_scope_changed')"
          type="warning"
          :closable="false"
          show-icon
        />

        <label class="link-field">
          <span class="field-label">{{ t('workspace_assets.requirements.link_task_modal.reason_label') }}</span>
          <el-input v-model="form.reason" type="textarea" :rows="2" :disabled="submitting" />
        </label>
      </template>
      <p v-else class="task-option-empty">{{ t('workspace_assets.requirements.task_links.no_candidates') }}</p>
      <el-alert v-if="failed" :title="t('workspace_assets.requirements.task_links.save_failed')" type="error" :closable="false" show-icon />
    </form>

    <template #footer>
      <el-button :disabled="submitting" @click="open = false">{{ t('common.cancel') }}</el-button>
      <el-button
        type="primary"
        native-type="submit"
        :form="formId"
        :loading="submitting"
        :disabled="!form.taskId || !options.length"
      >
        {{ t('workspace_assets.requirements.link_task_modal.submit') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.task-link-form { display: grid; gap: 16px; }
.link-field { display: grid; gap: 7px; min-width: 0; }
.field-label { color: var(--el-text-color-primary); font-size: 13px; font-weight: 600; }
.relation-field { display: grid; gap: 6px; min-width: 0; margin: 0; padding: 0; border: 0; }
.relation-field legend { margin-bottom: 7px; padding: 0; }
.relation-option {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  padding: 9px 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  cursor: pointer;
}
.relation-option.selected { border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }
.relation-option input { margin: 3px 0 0; accent-color: var(--el-color-primary); }
.relation-option strong { color: var(--el-text-color-primary); font-size: 13px; }
.option-description { display: block; margin-top: 2px; color: var(--el-text-color-regular); font-size: 12px; line-height: 1.5; }
.task-option-empty { margin: 0; color: var(--el-text-color-regular); font-size: 13px; }
</style>
