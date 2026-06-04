<script setup lang="ts">
import { reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { FilePenLine, ShieldCheck } from 'lucide-vue-next'
import type { BaselineCheckItem, TaskFinalSummary, TaskFinalSummaryPayload } from '@/types/workspaceAssets'
import WorkflowChecklist from './WorkflowChecklist.vue'
import WorkflowStatusPill from './WorkflowStatusPill.vue'

const props = defineProps<{
  summary: TaskFinalSummary | null
  checklist: BaselineCheckItem[]
  readonly: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  generateDraft: []
  save: [payload: TaskFinalSummaryPayload]
}>()

const { t } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow'
const form = reactive({
  finalStatus: 'PARTIAL',
  summary: '',
  remainingRisk: '',
  nextSteps: '',
  reviewConclusion: '',
  clarificationSummary: '',
  deltaSummary: '',
  decisionSummary: '',
})

watch(
  () => props.summary,
  (summary) => {
    form.finalStatus = summary?.final_status ?? 'PARTIAL'
    form.summary = summary?.summary ?? ''
    form.remainingRisk = summary?.remaining_risk ?? ''
    form.nextSteps = summary?.next_steps ?? ''
    form.reviewConclusion = String(summary?.review_checklist?.conclusion ?? '')
    form.clarificationSummary = String(summary?.clarification_summary?.summary ?? '')
    form.deltaSummary = String(summary?.delta_summary?.summary ?? '')
    form.decisionSummary = String(summary?.decision_summary?.summary ?? '')
  },
  { immediate: true },
)

function save(finalStatus = form.finalStatus) {
  emit('save', {
    final_status: finalStatus,
    summary: form.summary,
    remaining_risk: form.remainingRisk,
    next_steps: form.nextSteps,
    review_checklist: {
      conclusion: form.reviewConclusion,
    },
    clarification_summary: {
      summary: form.clarificationSummary,
    },
    delta_summary: {
      summary: form.deltaSummary,
    },
    decision_summary: {
      summary: form.decisionSummary,
    },
    final_evidence_ids: props.summary?.final_evidence_ids ?? [],
    human_confirmation_review_id: props.summary?.human_confirmation_review_id ?? null,
  })
}
</script>

<template>
  <section class="final-summary-step">
    <div class="step-heading">
      <div>
        <p class="eyebrow">{{ t(`${baseKey}.steps.step_label`, { number: 3 }) }}</p>
        <h3 class="step-title">{{ t(`${baseKey}.steps.final_summary`) }}</h3>
      </div>
      <WorkflowStatusPill :status="summary?.final_status || 'PENDING'" />
    </div>

    <div class="summary-layout">
      <aside class="summary-checklist">
        <WorkflowChecklist :items="checklist" />
      </aside>

      <div class="summary-editor">
        <div class="editor-toolbar">
          <el-button :disabled="readonly || saving" :loading="saving" @click="emit('generateDraft')">
            <FilePenLine class="button-icon" />
            {{ t(`${baseKey}.summary.generate_draft`) }}
          </el-button>
          <el-button :disabled="readonly || saving" :loading="saving" @click="save('PARTIAL')">
            {{ t(`${baseKey}.summary.save_draft`) }}
          </el-button>
          <el-button :disabled="readonly || saving" :loading="saving" type="primary" @click="save('VERIFIED')">
            <ShieldCheck class="button-icon" />
            {{ t(`${baseKey}.summary.verify`) }}
          </el-button>
        </div>

        <el-form label-position="top" class="summary-form" :disabled="readonly">
          <el-form-item :label="t(`${baseKey}.fields.summary`)">
            <el-input v-model="form.summary" type="textarea" :rows="5" />
          </el-form-item>
          <div class="form-grid">
            <el-form-item :label="t(`${baseKey}.fields.remaining_risk`)">
              <el-input v-model="form.remainingRisk" type="textarea" :rows="4" />
            </el-form-item>
            <el-form-item :label="t(`${baseKey}.fields.next_steps`)">
              <el-input v-model="form.nextSteps" type="textarea" :rows="4" />
            </el-form-item>
          </div>
          <div class="form-grid">
            <el-form-item :label="t(`${baseKey}.fields.review_conclusion`)">
              <el-input v-model="form.reviewConclusion" type="textarea" :rows="3" />
            </el-form-item>
            <el-form-item :label="t(`${baseKey}.fields.clarification_summary`)">
              <el-input v-model="form.clarificationSummary" type="textarea" :rows="3" />
            </el-form-item>
            <el-form-item :label="t(`${baseKey}.fields.delta_summary`)">
              <el-input v-model="form.deltaSummary" type="textarea" :rows="3" />
            </el-form-item>
            <el-form-item :label="t(`${baseKey}.fields.decision_summary`)">
              <el-input v-model="form.decisionSummary" type="textarea" :rows="3" />
            </el-form-item>
          </div>
        </el-form>
      </div>
    </div>
  </section>
</template>

<style scoped>
.final-summary-step {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.step-heading,
.editor-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.eyebrow {
  margin: 0 0 4px;
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 800;
  text-transform: uppercase;
}

.step-title {
  margin: 0;
  color: #0f172a;
  font-size: 1.05rem;
}

.summary-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 20px;
}

.summary-checklist {
  padding-right: 18px;
  border-right: 1px solid #e2e8f0;
}

.summary-editor {
  min-width: 0;
}

.editor-toolbar {
  justify-content: flex-end;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.button-icon {
  width: 15px;
  height: 15px;
  margin-right: 6px;
}

.summary-form {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

@media (max-width: 980px) {
  .summary-layout {
    grid-template-columns: 1fr;
  }

  .summary-checklist {
    padding-right: 0;
    padding-bottom: 16px;
    border-right: 0;
    border-bottom: 1px solid #e2e8f0;
  }
}

@media (max-width: 700px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
