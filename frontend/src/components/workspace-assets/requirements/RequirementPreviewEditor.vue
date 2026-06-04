<script setup lang="ts">
import { reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RequirementImportBatch } from '@/types/workspaceAssets'
import type {
  EditableRequirementPreviewItem,
  RequirementPreviewConfirmPayload,
} from './requirementCreateTypes'

const props = defineProps<{
  batch: RequirementImportBatch | null
  loading?: boolean
  split?: boolean
}>()

const emit = defineEmits<{
  confirm: [payload: RequirementPreviewConfirmPayload]
  discard: []
  back: []
  cancel: []
}>()

const { t } = useI18n()
const changeReason = defineModel<string>('changeReason', { default: '' })
const previewItems = reactive<EditableRequirementPreviewItem[]>([])

watch(
  () => props.batch,
  (batch) => {
    previewItems.splice(0, previewItems.length)
    for (const item of batch?.items || []) {
      previewItems.push({
        item_id: item.id,
        include: item.status !== 'SKIPPED',
        title: item.title,
        body: item.body || '',
        acceptance_criteria: item.acceptance_criteria || [],
        priority: item.priority || '',
        task_prompt: item.task_prompt || '',
        status: 'DRAFT',
        originalTitle: item.title,
      })
    }
  },
  { immediate: true },
)

function updateCriteriaFromEvent(item: EditableRequirementPreviewItem, event: Event) {
  const value = (event.target as HTMLTextAreaElement | null)?.value || ''
  item.acceptance_criteria = value
    .split('\n')
    .map((current) => current.trim())
    .filter(Boolean)
}

function confirm() {
  emit('confirm', {
    items: previewItems.map((item) => ({
      item_id: item.item_id,
      include: item.include,
      title: item.title || item.originalTitle,
      body: item.body || null,
      acceptance_criteria: item.acceptance_criteria || [],
      priority: item.priority || null,
      task_prompt: item.task_prompt || null,
      status: item.status || 'DRAFT',
    })),
    change_reason: changeReason.value || null,
  })
}
</script>

<template>
  <section class="preview-step">
    <div class="preview-head">
      <div>
        <h4>{{ t('workspace_assets.requirements.preview.title') }}</h4>
        <p>{{ t('workspace_assets.requirements.preview.body') }}</p>
      </div>
      <span>{{ props.batch?.status || t('workspace_assets.requirements.preview.no_preview') }}</span>
    </div>

    <div v-if="previewItems.length" class="preview-list">
      <article v-for="item in previewItems" :key="item.item_id" class="preview-item">
        <label class="include-row">
          <input v-model="item.include" type="checkbox" />
          <span>{{ t('workspace_assets.requirements.preview.create_requirement') }}</span>
        </label>
        <input v-model="item.title" :placeholder="t('workspace_assets.requirements.placeholders.title')" />
        <textarea v-model="item.body" rows="4" :placeholder="t('workspace_assets.requirements.placeholders.description')" />
        <textarea
          :value="(item.acceptance_criteria || []).join('\n')"
          rows="3"
          :placeholder="t('workspace_assets.requirements.placeholders.criteria')"
          @input="updateCriteriaFromEvent(item, $event)"
        />
        <textarea
          v-model="item.task_prompt"
          rows="4"
          :placeholder="t('workspace_assets.requirements.placeholders.task_prompt')"
        />
      </article>
    </div>
    <div v-else class="empty-box">
      {{ props.split ? t('workspace_assets.requirements.preview.split_empty') : t('workspace_assets.requirements.preview.empty') }}
    </div>

    <label class="reason-field">
      <span>{{ t('workspace_assets.requirements.fields.confirm_reason') }}</span>
      <textarea v-model="changeReason" rows="3" />
    </label>

    <footer class="dialog-footer">
      <button type="button" class="ghost-action" @click="emit('cancel')">
        {{ t('workspace_assets.requirements.actions.cancel') }}
      </button>
      <div class="button-row">
        <button
          v-if="previewItems.length && !props.split"
          type="button"
          class="ghost-action"
          @click="emit('discard')"
        >
          {{ t('workspace_assets.requirements.actions.discard_preview') }}
        </button>
        <button
          v-else-if="!props.split"
          type="button"
          class="ghost-action"
          @click="emit('back')"
        >
          {{ t('workspace_assets.requirements.actions.back') }}
        </button>
        <button type="button" class="primary-action" :disabled="props.loading || !previewItems.length" @click="confirm">
          {{ props.loading ? t('workspace_assets.requirements.actions.confirming') : t('workspace_assets.requirements.actions.apply_preview') }}
        </button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.preview-step {
  display: grid;
  gap: 12px;
  padding: 18px 22px;
}

.preview-head,
.dialog-footer,
.button-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.preview-head {
  align-items: flex-start;
  padding-bottom: 10px;
  border-bottom: 1px solid #e2e8f0;
}

.preview-head h4 {
  margin: 0;
  color: #0f172a;
}

.preview-head p {
  margin: 4px 0 0;
  color: #64748b;
  line-height: 1.55;
}

.preview-head span {
  color: #2563eb;
  font-weight: 800;
}

.preview-list {
  display: grid;
  gap: 10px;
}

.preview-item {
  display: grid;
  gap: 9px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

.include-row {
  flex-direction: row;
  align-items: center;
}

.include-row input {
  width: auto;
}

input,
textarea {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 10px 11px;
  color: #0f172a;
  font: inherit;
}

textarea {
  resize: vertical;
}

.empty-box {
  padding: 16px;
  border: 1px dashed rgba(148, 163, 184, 0.38);
  border-radius: 8px;
  background: #f8fafc;
  color: #64748b;
}

.primary-action,
.ghost-action {
  min-height: 34px;
  padding: 0 13px;
  border-radius: 8px;
  font-weight: 700;
  cursor: pointer;
}

.primary-action {
  border: 1px solid #2563eb;
  background: #2563eb;
  color: #ffffff;
}

.primary-action:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.ghost-action {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
}

@media (max-width: 720px) {
  .dialog-footer {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
