<script setup lang="ts">
import { computed, reactive, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Eye, Pencil, Plus, ShieldCheck } from 'lucide-vue-next'
import type {
  FinalWorkflowReviewPayload,
  HumanReview,
  ReviewTarget,
  ReviewTargetRef,
  ReviewTargetType,
} from '@/types/workspaceAssets'
import ReviewTargetPicker from './ReviewTargetPicker.vue'
import WorkflowStatusPill from './WorkflowStatusPill.vue'

const props = defineProps<{
  reviews: HumanReview[]
  reviewTargets: Record<ReviewTargetType, ReviewTarget[]>
  readonly: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  createReview: [payload: FinalWorkflowReviewPayload]
  updateReview: [reviewId: string, payload: FinalWorkflowReviewPayload]
}>()

const { t } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow'
const reviewDialogVisible = shallowRef(false)
const editingReviewId = shallowRef<string | null>(null)
const reviewForm = reactive({
  title: '',
  body: '',
  priority: 'NORMAL',
  targetRefs: [] as ReviewTargetRef[],
})

const reviewCountText = computed(() => t(`${baseKey}.expert_review.count`, { count: props.reviews.length }))
const targetLookup = computed(() => {
  const map = new Map<string, ReviewTarget>()
  for (const group of Object.values(props.reviewTargets ?? {})) {
    for (const item of group) {
      map.set(toKey(item), item)
    }
  }
  return map
})

function toKey(item: Pick<ReviewTargetRef, 'target_type' | 'target_id'>) {
  return `${item.target_type}:${item.target_id}`
}

function targetRefsFor(review: HumanReview): ReviewTargetRef[] {
  if (review.target_refs?.length) return review.target_refs
  const rawTargets = review.target_ref?.['targets']
  return Array.isArray(rawTargets) ? (rawTargets as ReviewTargetRef[]) : []
}

function targetLabel(ref: ReviewTargetRef) {
  return targetLookup.value.get(toKey(ref))?.label || ref.label || ref.target_id
}

function targetTypeLabel(type: ReviewTargetType | string) {
  return t(`${baseKey}.target_types.${String(type).toLowerCase()}`)
}

function priorityLabel(priority?: string | null) {
  return t(`${baseKey}.priority.${String(priority || 'NORMAL').toLowerCase()}`)
}

function openCreateReview() {
  editingReviewId.value = null
  reviewForm.title = ''
  reviewForm.body = ''
  reviewForm.priority = 'NORMAL'
  reviewForm.targetRefs = []
  reviewDialogVisible.value = true
}

function openEditReview(review: HumanReview) {
  editingReviewId.value = review.id
  reviewForm.title = review.title || ''
  reviewForm.body = review.body || ''
  reviewForm.priority = review.priority || 'NORMAL'
  reviewForm.targetRefs = targetRefsFor(review)
  reviewDialogVisible.value = true
}

function submitReview() {
  const payload: FinalWorkflowReviewPayload = {
    title: reviewForm.title,
    body: reviewForm.body || null,
    priority: reviewForm.priority,
    target_refs: reviewForm.targetRefs,
  }
  if (editingReviewId.value) {
    emit('updateReview', editingReviewId.value, payload)
  } else {
    emit('createReview', payload)
  }
  reviewDialogVisible.value = false
}
</script>

<template>
  <section class="expert-review-step">
    <div class="step-heading">
      <div>
        <p class="eyebrow">{{ t(`${baseKey}.steps.step_label`, { number: 1 }) }}</p>
        <h3 class="step-title">{{ t(`${baseKey}.steps.expert_review`) }}</h3>
        <span class="step-subtitle">{{ t(`${baseKey}.expert_review.subtitle`, { countText: reviewCountText }) }}</span>
      </div>
      <el-button v-if="!readonly" :disabled="saving" type="primary" @click="openCreateReview">
        <Plus class="button-icon" />
        {{ t(`${baseKey}.expert_review.create`) }}
      </el-button>
    </div>

    <div v-if="reviews.length === 0" class="empty-state">
      <ShieldCheck class="empty-icon" />
      <div>
        <strong>{{ t(`${baseKey}.expert_review.empty_title`) }}</strong>
        <span>{{ t(`${baseKey}.expert_review.empty_body`) }}</span>
      </div>
    </div>

    <div v-else class="review-list">
      <article v-for="review in reviews" :key="review.id" class="review-record">
        <div class="record-title-row">
          <div class="record-heading">
            <h4 class="record-title">{{ review.title || t(`${baseKey}.expert_review.default_title`) }}</h4>
            <p v-if="review.body" class="record-body">{{ review.body }}</p>
          </div>
          <WorkflowStatusPill :status="review.derived_status || review.status" />
        </div>

        <div class="target-chip-row">
          <el-tag
            v-for="target in targetRefsFor(review)"
            :key="toKey(target)"
            size="small"
            effect="plain"
          >
            {{ targetTypeLabel(target.target_type) }} · {{ targetLabel(target) }}
          </el-tag>
          <span v-if="targetRefsFor(review).length === 0" class="missing-target">
            {{ t(`${baseKey}.expert_review.missing_target`) }}
          </span>
        </div>

        <dl class="record-meta">
          <div>
            <dt>{{ t(`${baseKey}.fields.priority`) }}</dt>
            <dd>{{ priorityLabel(review.priority) }}</dd>
          </div>
          <div>
            <dt>{{ t(`${baseKey}.fields.clarifications`) }}</dt>
            <dd>{{ review.linked_clarification_ids?.length ?? 0 }}</dd>
          </div>
          <div>
            <dt>{{ t(`${baseKey}.fields.updated`) }}</dt>
            <dd>{{ review.updated_at || review.created_at || '-' }}</dd>
          </div>
        </dl>

        <div class="record-actions">
          <el-button v-if="!readonly" :disabled="saving" @click="openEditReview(review)">
            <Pencil class="button-icon" />
            {{ t(`${baseKey}.expert_review.edit`) }}
          </el-button>
          <el-button :disabled="(review.linked_clarification_ids?.length ?? 0) === 0">
            <Eye class="button-icon" />
            {{ t(`${baseKey}.expert_review.view_threads`) }}
          </el-button>
        </div>
      </article>
    </div>

    <el-dialog
      v-model="reviewDialogVisible"
      :title="editingReviewId ? t(`${baseKey}.expert_review.edit_dialog_title`) : t(`${baseKey}.expert_review.create_dialog_title`)"
      width="820px"
    >
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item :label="t(`${baseKey}.fields.title`)">
            <el-input v-model="reviewForm.title" maxlength="300" />
          </el-form-item>
          <el-form-item :label="t(`${baseKey}.fields.priority`)">
            <el-select v-model="reviewForm.priority" class="field-full">
              <el-option :label="t(`${baseKey}.priority.high`)" value="HIGH" />
              <el-option :label="t(`${baseKey}.priority.normal`)" value="NORMAL" />
              <el-option :label="t(`${baseKey}.priority.low`)" value="LOW" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item :label="t(`${baseKey}.fields.review_body`)">
          <el-input v-model="reviewForm.body" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item :label="t(`${baseKey}.fields.review_targets`)">
          <ReviewTargetPicker v-model="reviewForm.targetRefs" :targets="reviewTargets" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :disabled="!reviewForm.title || reviewForm.targetRefs.length === 0"
          :loading="saving"
          @click="submitReview"
        >
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.expert-review-step {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.step-heading,
.record-title-row,
.record-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.step-heading,
.record-title-row {
  justify-content: space-between;
}

.eyebrow {
  margin: 0 0 4px;
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 800;
  text-transform: uppercase;
}

.step-title,
.record-title {
  margin: 0;
  color: #0f172a;
}

.step-title {
  font-size: 1.05rem;
}

.step-subtitle {
  display: block;
  margin-top: 4px;
  color: #64748b;
  font-size: 0.82rem;
}

.empty-state {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  color: #64748b;
}

.empty-state span {
  display: block;
  margin-top: 4px;
  font-size: 0.84rem;
}

.empty-icon {
  width: 24px;
  height: 24px;
  color: #2563eb;
}

.review-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.review-record {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
}

.record-heading {
  min-width: 0;
}

.record-body {
  margin: 8px 0 0;
  color: #334155;
  font-size: 0.88rem;
  line-height: 1.55;
}

.target-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.missing-target {
  color: #b45309;
  font-size: 0.8rem;
}

.record-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}

.record-meta div {
  min-width: 0;
}

.record-meta dt {
  color: #94a3b8;
  font-size: 0.7rem;
  font-weight: 800;
  text-transform: uppercase;
}

.record-meta dd {
  margin: 3px 0 0;
  overflow: hidden;
  color: #0f172a;
  font-size: 0.82rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.record-actions {
  flex-wrap: wrap;
}

.button-icon {
  width: 15px;
  height: 15px;
  margin-right: 6px;
}

.form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 180px;
  gap: 12px;
}

.field-full {
  width: 100%;
}

@media (max-width: 760px) {
  .step-heading,
  .record-title-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .record-meta,
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
