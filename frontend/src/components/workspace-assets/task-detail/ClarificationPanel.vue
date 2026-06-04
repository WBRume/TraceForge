<script setup lang="ts">
import { reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import TaskAssetEmptyState from './TaskAssetEmptyState.vue'
import { useTaskDetailAssets } from '@/composables/useTaskDetailAssets'
import type {
  ClarificationLight,
  EvidenceLight,
  TaskRequirementLink,
} from '@/types/workspaceAssets'

const props = defineProps<{
  clarifications: ClarificationLight[]
  workspaceId: string
  taskId: string
  requirementLinks?: TaskRequirementLink[]
  evidence?: EvidenceLight[]
}>()

const emit = defineEmits<{
  mutated: []
}>()

const { t } = useI18n()
const taskAssets = useTaskDetailAssets()

const form = reactive({
  question: '',
  answer: '',
  status: 'OPEN',
  blocking_level: 'NON_BLOCKING',
  requirement_id: '',
  source_evidence_id: '',
  promote_candidate: false,
  change_reason: '',
})

async function submitClarification() {
  const result = await taskAssets.createClarification(props.workspaceId, props.taskId, {
    ...form,
    requirement_id: form.requirement_id || null,
    source_evidence_id: form.source_evidence_id || null,
  })
  if (!result) return
  emit('mutated')
  Object.assign(form, {
    question: '',
    answer: '',
    status: 'OPEN',
    blocking_level: 'NON_BLOCKING',
    requirement_id: '',
    source_evidence_id: '',
    promote_candidate: false,
    change_reason: '',
  })
  ElMessage.success(t('workspace_assets.task_detail.workbench.saved'))
}
</script>

<template>
  <section class="panel-shell">
    <header class="panel-head">
      <div>
        <span class="eyebrow">{{ t('workspace_assets.task_detail.workbench.clarifications.eyebrow') }}</span>
        <h2>{{ t('workspace_assets.task_detail.workbench.clarifications.title') }}</h2>
        <p>{{ t('workspace_assets.task_detail.workbench.clarifications.description') }}</p>
      </div>
      <el-alert
        class="boundary-alert"
        type="info"
        :closable="false"
        :title="t('workspace_assets.task_detail.workbench.clarifications.boundary')"
      />
    </header>

    <el-form label-position="top" class="write-form" @submit.prevent="submitClarification">
      <el-row :gutter="12">
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.status')">
            <el-select v-model="form.status">
              <el-option label="Open" value="OPEN" />
              <el-option label="Answered" value="ANSWERED" />
              <el-option label="Closed" value="CLOSED" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.blocking_level')">
            <el-select v-model="form.blocking_level">
              <el-option label="Blocking" value="BLOCKING" />
              <el-option label="Non-blocking" value="NON_BLOCKING" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.promote_candidate')">
            <el-switch v-model="form.promote_candidate" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.question')">
        <el-input v-model="form.question" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.answer')">
        <el-input v-model="form.answer" type="textarea" :rows="3" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.requirement')">
            <el-select v-model="form.requirement_id" clearable>
              <el-option v-for="link in (requirementLinks ?? [])" :key="link.id" :label="link.requirement?.title || link.requirement_id" :value="link.requirement_id" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.source_evidence')">
            <el-select v-model="form.source_evidence_id" clearable>
              <el-option v-for="item in (evidence ?? [])" :key="item.id" :label="item.title || item.id" :value="item.id" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.reason')">
            <el-input v-model="form.change_reason" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-button type="primary" :disabled="!form.question" :loading="taskAssets.saving.value" @click="submitClarification">
        {{ t('workspace_assets.task_detail.workbench.clarifications.submit') }}
      </el-button>
    </el-form>

    <TaskAssetEmptyState
      v-if="!clarifications.length"
      :title="t('workspace_assets.task_detail.workbench.clarifications.empty_title')"
      :message="t('workspace_assets.task_detail.workbench.clarifications.empty')"
    />

    <el-table v-else :data="clarifications" row-key="id" border>
      <el-table-column prop="question" :label="t('workspace_assets.task_detail.workbench.fields.question')" min-width="260" />
      <el-table-column prop="status" :label="t('workspace_assets.task_detail.workbench.fields.status')" width="130" />
      <el-table-column prop="blocking_level" :label="t('workspace_assets.task_detail.workbench.fields.blocking_level')" width="150" />
      <el-table-column prop="answer" :label="t('workspace_assets.task_detail.workbench.fields.answer')" min-width="240" />
    </el-table>
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
  grid-template-columns: minmax(0, 1fr) minmax(260px, 380px);
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
