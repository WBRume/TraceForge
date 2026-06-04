<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RequirementEditableStatus, RequirementMutationPayload, RequirementSummary } from '@/types/workspaceAssets'

const props = defineProps<{
  open: boolean
  requirement?: RequirementSummary | null
  loading?: boolean
}>()

const emit = defineEmits<{
  close: []
  submit: [payload: RequirementMutationPayload]
}>()

const { t } = useI18n()
const statusOptions: RequirementEditableStatus[] = [
  'DRAFT',
  'READY',
  'IN_PROGRESS',
  'VERIFIED',
  'REJECTED',
  'ARCHIVED',
]

const form = reactive({
  title: '',
  body: '',
  acceptanceCriteriaText: '',
  priority: '',
  status: 'DRAFT' as RequirementEditableStatus,
  sourceKind: '',
  sourceUri: '',
  sourceRef: '',
  changeReason: '',
})

const isEdit = computed(() => Boolean(props.requirement))

watch(
  () => [props.open, props.requirement] as const,
  () => {
    const requirement = props.requirement
    form.title = requirement?.title || ''
    form.body = requirement?.body || ''
    form.acceptanceCriteriaText = (requirement?.acceptance_criteria || []).join('\n')
    form.priority = requirement?.priority || ''
    form.status = (requirement?.status as RequirementEditableStatus) || 'DRAFT'
    form.sourceKind = requirement?.source_kind || ''
    form.sourceUri = requirement?.source_uri || ''
    form.sourceRef = requirement?.source_ref || ''
    form.changeReason = ''
  },
  { immediate: true },
)

function submit() {
  emit('submit', {
    title: form.title,
    body: form.body || null,
    acceptance_criteria: form.acceptanceCriteriaText
      .split('\n')
      .map((item) => item.trim())
      .filter(Boolean),
    priority: form.priority || null,
    status: form.status,
    source_kind: form.sourceKind || null,
    source_uri: form.sourceUri || null,
    source_ref: form.sourceRef || null,
    change_reason: form.changeReason || null,
  })
}
</script>

<template>
  <Teleport to="body">
    <div v-if="props.open" class="drawer-backdrop" @click.self="emit('close')">
      <aside class="requirement-drawer" :aria-label="t('workspace_assets.requirements.edit.aria_label')">
        <header>
          <div>
            <span class="eyebrow">{{ isEdit ? t('workspace_assets.requirements.edit.eyebrow_edit') : t('workspace_assets.requirements.edit.eyebrow_create') }}</span>
            <h3>{{ isEdit ? t('workspace_assets.requirements.edit.title_edit') : t('workspace_assets.requirements.edit.title_create') }}</h3>
          </div>
          <button type="button" class="ghost-action" @click="emit('close')">{{ t('workspace_assets.requirements.actions.close') }}</button>
        </header>

        <form class="drawer-form" @submit.prevent="submit">
          <label>
            <span>{{ t('workspace_assets.requirements.fields.title') }}</span>
            <input v-model="form.title" required maxlength="300" />
          </label>
          <label>
            <span>{{ t('workspace_assets.requirements.fields.description') }}</span>
            <textarea v-model="form.body" rows="5" />
          </label>
          <label>
            <span>{{ t('workspace_assets.requirements.fields.acceptance_criteria') }}</span>
            <textarea v-model="form.acceptanceCriteriaText" rows="4" :placeholder="t('workspace_assets.requirements.placeholders.criteria')" />
          </label>
          <div class="field-grid">
            <label>
              <span>{{ t('workspace_assets.requirements.fields.status') }}</span>
              <select v-model="form.status">
                <option v-for="option in statusOptions" :key="option" :value="option">{{ option }}</option>
              </select>
            </label>
            <label>
              <span>{{ t('workspace_assets.requirements.fields.priority') }}</span>
              <input v-model="form.priority" maxlength="40" :placeholder="t('workspace_assets.requirements.placeholders.priority')" />
            </label>
          </div>
          <div class="field-grid">
            <label>
              <span>{{ t('workspace_assets.requirements.fields.source_kind') }}</span>
              <input v-model="form.sourceKind" maxlength="80" :placeholder="t('workspace_assets.requirements.placeholders.source_kind')" />
            </label>
            <label>
              <span>{{ t('workspace_assets.requirements.fields.source_ref') }}</span>
              <input v-model="form.sourceRef" maxlength="300" />
            </label>
          </div>
          <label>
            <span>{{ t('workspace_assets.requirements.fields.source_uri') }}</span>
            <input v-model="form.sourceUri" maxlength="1000" :placeholder="t('workspace_assets.requirements.placeholders.source_uri')" />
          </label>
          <label>
            <span>{{ t('workspace_assets.requirements.fields.change_reason') }}</span>
            <textarea v-model="form.changeReason" rows="3" :placeholder="t('workspace_assets.requirements.placeholders.change_reason')" />
          </label>

          <p class="boundary-note">
            {{ t('workspace_assets.requirements.edit.boundary') }}
          </p>

          <footer>
            <button type="button" class="ghost-action" @click="emit('close')">{{ t('workspace_assets.requirements.actions.cancel') }}</button>
            <button type="submit" class="primary-action" :disabled="props.loading || !form.title.trim()">
              {{ props.loading ? t('workspace_assets.requirements.actions.saving') : t('workspace_assets.requirements.actions.save') }}
            </button>
          </footer>
        </form>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
  background: rgba(15, 23, 42, 0.22);
}

.requirement-drawer {
  width: min(560px, 100vw);
  height: 100%;
  overflow: auto;
  background: #ffffff;
  box-shadow: -20px 0 50px rgba(15, 23, 42, 0.18);
}

.requirement-drawer header,
.requirement-drawer footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 22px;
  border-bottom: 1px solid #e2e8f0;
}

.requirement-drawer footer {
  border-top: 1px solid #e2e8f0;
  border-bottom: 0;
}

.requirement-drawer h3 {
  margin: 4px 0 0;
  color: #0f172a;
}

.eyebrow {
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.drawer-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 22px;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

input,
select,
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

.boundary-note {
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: #eff6ff;
  color: #475569;
  line-height: 1.55;
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

@media (max-width: 640px) {
  .field-grid {
    grid-template-columns: 1fr;
  }
}
</style>
