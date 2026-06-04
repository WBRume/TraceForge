<script setup lang="ts">
import { reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import TaskAssetEmptyState from './TaskAssetEmptyState.vue'
import { useTaskDetailAssets } from '@/composables/useTaskDetailAssets'
import type { EvidenceLight, HumanReviewLight, TaskFinalSummary } from '@/types/workspaceAssets'

const props = defineProps<{
  finalSummary: TaskFinalSummary | null
  workspaceId: string
  taskId: string
  reviews?: HumanReviewLight[]
  evidence?: EvidenceLight[]
}>()

const emit = defineEmits<{
  mutated: []
}>()

const { t } = useI18n()
const taskAssets = useTaskDetailAssets()

const form = reactive({
  final_status: 'PENDING',
  summary: '',
  remaining_risk: '',
  next_steps: '',
  final_evidence_ids: [] as string[],
  human_confirmation_review_id: '',
  change_reason: '',
})

watch(() => props.finalSummary, (value) => {
  if (!value) return
  Object.assign(form, {
    final_status: value.final_status || 'PENDING',
    summary: value.summary || '',
    remaining_risk: value.remaining_risk || '',
    next_steps: value.next_steps || '',
    final_evidence_ids: [...(value.final_evidence_ids || [])],
    human_confirmation_review_id: value.human_confirmation_review_id || '',
  })
}, { immediate: true })

async function submitSummary() {
  const result = await taskAssets.upsertFinalSummary(props.workspaceId, props.taskId, {
    ...form,
    human_confirmation_review_id: form.human_confirmation_review_id || null,
  })
  if (!result) return
  emit('mutated')
  ElMessage.success(t('workspace_assets.task_detail.workbench.saved'))
}
</script>

<template>
  <section class="panel-shell">
    <header class="panel-head">
      <div>
        <span class="eyebrow">{{ t('workspace_assets.task_detail.workbench.final_summary.eyebrow') }}</span>
        <h2>{{ t('workspace_assets.task_detail.workbench.final_summary.title') }}</h2>
        <p>{{ t('workspace_assets.task_detail.workbench.final_summary.description') }}</p>
      </div>
      <el-alert
        class="boundary-alert"
        type="info"
        :closable="false"
        :title="t('workspace_assets.task_detail.workbench.final_summary.boundary')"
      />
    </header>

    <TaskAssetEmptyState
      v-if="!finalSummary"
      :title="t('workspace_assets.task_detail.workbench.final_summary.empty_title')"
      :message="t('workspace_assets.task_detail.workbench.final_summary.empty')"
    />

    <el-form label-position="top" class="write-form" @submit.prevent="submitSummary">
      <el-row :gutter="12">
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.final_status')">
            <el-select v-model="form.final_status">
              <el-option label="Pending" value="PENDING" />
              <el-option label="Partial" value="PARTIAL" />
              <el-option label="Rejected" value="REJECTED" />
              <el-option label="Verified" value="VERIFIED" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.final_evidence')">
            <el-select v-model="form.final_evidence_ids" multiple clearable>
              <el-option v-for="item in (evidence ?? [])" :key="item.id" :label="item.title || item.id" :value="item.id" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.human_confirmation_review')">
            <el-select v-model="form.human_confirmation_review_id" clearable>
              <el-option v-for="review in (reviews ?? [])" :key="review.id" :label="review.title || review.outcome || review.id" :value="review.id" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.summary')">
        <el-input v-model="form.summary" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.remaining_risk')">
        <el-input v-model="form.remaining_risk" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.next_steps')">
        <el-input v-model="form.next_steps" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.reason')">
        <el-input v-model="form.change_reason" />
      </el-form-item>
      <el-button type="primary" :loading="taskAssets.saving.value" @click="submitSummary">
        {{ t('workspace_assets.task_detail.workbench.final_summary.submit') }}
      </el-button>
      <el-alert
        v-if="taskAssets.error.value"
        type="error"
        :closable="false"
        :title="taskAssets.error.value"
      />
    </el-form>
  </section>
</template>

<style scoped>
.panel-shell,
.write-form {
  display: grid;
  gap: 14px;
}

.panel-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 400px);
  gap: 16px;
  align-items: start;
  padding-bottom: 14px;
  border-bottom: 1px solid #e2e8f0;
}

.eyebrow {
  color: var(--color-primary-700);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

.panel-head h2 {
  margin: 5px 0 0;
  color: #1e3a8a;
  font-family: 'Poppins', var(--font-heading);
  font-size: 1.22rem;
  letter-spacing: 0;
}

.panel-head p {
  margin: 7px 0 0;
  color: #475569;
  font-size: 0.9rem;
  line-height: 1.55;
}

.write-form {
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

@media (max-width: 920px) {
  .panel-head {
    grid-template-columns: 1fr;
  }
}
</style>
