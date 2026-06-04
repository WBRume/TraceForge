<script setup lang="ts">
import { computed, reactive, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessageCircle, Plus } from 'lucide-vue-next'
import type {
  Clarification,
  ClarificationMessagePayload,
  ClarificationThread,
  FinalWorkflowClarificationPayload,
  HumanReview,
  ReviewTarget,
  ReviewTargetRef,
  ReviewTargetType,
} from '@/types/workspaceAssets'
import ClarificationMessageComposer from './ClarificationMessageComposer.vue'
import ClarificationResolutionActions from './ClarificationResolutionActions.vue'
import ReviewTargetContextStrip from './ReviewTargetContextStrip.vue'
import WorkflowStatusPill from './WorkflowStatusPill.vue'

const props = defineProps<{
  clarifications: Clarification[]
  threads: Record<string, ClarificationThread[]>
  reviews: HumanReview[]
  reviewTargets: Record<ReviewTargetType, ReviewTarget[]>
  readonly: boolean
  canResolveClarification: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  create: [payload: FinalWorkflowClarificationPayload]
  addMessage: [clarificationId: string, payload: ClarificationMessagePayload]
  previewTarget: [target: ReviewTargetRef]
}>()

const { t } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow'
const createDialogVisible = shallowRef(false)
const selectedClarificationId = shallowRef<string | null>(null)
const createForm = reactive({
  question: '',
  blockingLevel: 'BLOCKING',
  urgency: 'NORMAL',
  clarificationType: 'REVIEW_QUESTION',
  sourceReviewId: '',
})
const reopenDialogVisible = shallowRef(false)
const reopenReason = shallowRef('')

const unresolvedBlockingCount = computed(() =>
  props.clarifications.filter((item) =>
    item.blocking_level === 'BLOCKING' && !['ACCEPTED', 'CLOSED', 'CANCELLED'].includes(item.status),
  ).length,
)
const selectedClarification = computed(() =>
  props.clarifications.find((item) => item.id === selectedClarificationId.value) ?? props.clarifications[0] ?? null,
)
const selectedThreads = computed(() =>
  selectedClarification.value ? props.threads[selectedClarification.value.id] ?? [] : [],
)
const selectedReview = computed(() =>
  selectedClarification.value?.source_review_id
    ? props.reviews.find((item) => item.id === selectedClarification.value?.source_review_id) ?? null
    : null,
)
const selectedContextTargets = computed(() => {
  if (!selectedClarification.value) return []
  const frozenTargets = targetRefsFromRecord(selectedClarification.value.target_ref)
  if (frozenTargets.length) return frozenTargets
  return selectedReview.value ? targetRefsForReview(selectedReview.value) : []
})
const canReopen = computed(() =>
  Boolean(
    selectedClarification.value
    && props.canResolveClarification
    && !props.readonly
    && selectedClarification.value.status === 'ACCEPTED',
  ),
)

watch(
  () => props.clarifications.map((item) => item.id).join(','),
  () => {
    if (!selectedClarificationId.value || !props.clarifications.some((item) => item.id === selectedClarificationId.value)) {
      selectedClarificationId.value = props.clarifications[0]?.id ?? null
    }
  },
  { immediate: true },
)

function submitCreate() {
  emit('create', {
    question: createForm.question,
    blocking_level: createForm.blockingLevel,
    urgency: createForm.urgency,
    clarification_type: createForm.clarificationType,
    source_review_id: createForm.sourceReviewId || null,
  })
  createDialogVisible.value = false
  createForm.question = ''
  createForm.sourceReviewId = ''
}

function submitConversationMessage(payload: ClarificationMessagePayload) {
  if (!selectedClarification.value) return
  emit('addMessage', selectedClarification.value.id, payload)
}

function confirmResolution() {
  if (!selectedClarification.value || props.readonly || !props.canResolveClarification) return
  emit('addMessage', selectedClarification.value.id, {
    body: t(`${baseKey}.clarification.confirm_resolution_body`),
    entry_type: 'CONFIRM_RESOLUTION',
  })
}

function openReopenDialog() {
  if (!canReopen.value) return
  reopenReason.value = ''
  reopenDialogVisible.value = true
}

function submitReopen() {
  if (!selectedClarification.value || !reopenReason.value.trim()) return
  emit('addMessage', selectedClarification.value.id, {
    body: reopenReason.value,
    entry_type: 'REOPEN',
  })
  reopenDialogVisible.value = false
  reopenReason.value = ''
}

function reviewLabel(reviewId?: string | null) {
  if (!reviewId) return ''
  const review = props.reviews.find((item) => item.id === reviewId)
  return review?.title || t(`${baseKey}.clarification.review_fallback`, { id: reviewId.slice(0, 8) })
}

function targetRefsFromRecord(value?: Record<string, unknown> | null): ReviewTargetRef[] {
  const rawTargets = value?.targets
  return Array.isArray(rawTargets)
    ? rawTargets.filter(isReviewTargetRef)
    : []
}

function targetRefsForReview(review: HumanReview): ReviewTargetRef[] {
  if (review.target_refs?.length) return review.target_refs
  return targetRefsFromRecord(review.target_ref)
}

function isReviewTargetRef(value: unknown): value is ReviewTargetRef {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<ReviewTargetRef>
  return Boolean(item.target_type && item.target_id)
}

function blockingLevelLabel(level?: string | null) {
  return t(`${baseKey}.blocking_level.${String(level || 'NON_BLOCKING').toLowerCase()}`)
}

function priorityLabel(priority?: string | null) {
  return t(`${baseKey}.priority.${String(priority || 'NORMAL').toLowerCase()}`)
}

function messageTypeLabel(entryType: string) {
  return t(`${baseKey}.message_types.${entryType.toLowerCase()}`)
}
</script>

<template>
  <section class="clarification-step">
    <div class="step-heading">
      <div>
        <p class="eyebrow">{{ t(`${baseKey}.steps.step_label`, { number: 2 }) }}</p>
        <h3 class="step-title">{{ t(`${baseKey}.steps.clarification`) }}</h3>
      </div>
      <div class="heading-actions">
        <WorkflowStatusPill :status="unresolvedBlockingCount > 0 ? 'blocked' : 'complete'" />
        <el-button v-if="!readonly" :disabled="saving" type="primary" @click="createDialogVisible = true">
          <Plus class="button-icon" />
          {{ t(`${baseKey}.clarification.create`) }}
        </el-button>
      </div>
    </div>

    <div v-if="clarifications.length === 0" class="empty-state">
      <MessageCircle class="empty-icon" />
      <div>
        <strong>{{ t(`${baseKey}.clarification.empty_title`) }}</strong>
        <span>{{ t(`${baseKey}.clarification.empty_body`) }}</span>
      </div>
    </div>

    <div v-else class="thread-workbench">
      <aside class="thread-list-panel">
        <button
          v-for="item in clarifications"
          :key="item.id"
          class="thread-list-item"
          :class="{ 'is-active': selectedClarification?.id === item.id }"
          type="button"
          @click="selectedClarificationId = item.id"
        >
          <span class="thread-title">{{ item.question }}</span>
          <span class="thread-meta">
            {{ blockingLevelLabel(item.blocking_level) }} · {{ priorityLabel(item.urgency) }}
          </span>
          <WorkflowStatusPill :status="item.status" />
        </button>
      </aside>

      <section v-if="selectedClarification" class="conversation-panel">
        <header class="conversation-header">
          <div>
            <h4>{{ selectedClarification.question }}</h4>
            <p>
              {{ blockingLevelLabel(selectedClarification.blocking_level) }} · {{ priorityLabel(selectedClarification.urgency) }}
              <span v-if="selectedClarification.source_review_id">
                · {{ reviewLabel(selectedClarification.source_review_id) }}
              </span>
            </p>
          </div>
          <ClarificationResolutionActions
            :status="selectedClarification.status"
            :can-resolve="canResolveClarification && !readonly"
            :saving="saving"
            @confirm="confirmResolution"
            @reopen="openReopenDialog"
          />
        </header>

        <ReviewTargetContextStrip
          :targets="selectedContextTargets"
          :review-targets="reviewTargets"
          @preview="emit('previewTarget', $event)"
        />

        <div class="message-stream">
          <div
            v-for="message in selectedThreads"
            :key="message.id"
            class="message-bubble"
            :class="{
              'is-answer': message.entry_type === 'ANSWER',
              'is-system': ['SYSTEM', 'CONFIRM_RESOLUTION', 'REOPEN'].includes(message.entry_type),
            }"
          >
            <span class="message-kind">{{ messageTypeLabel(message.entry_type) }}</span>
            <p>{{ message.body }}</p>
            <time v-if="message.created_at">{{ message.created_at }}</time>
          </div>
        </div>

        <ClarificationMessageComposer
          v-if="!readonly"
          :saving="saving"
          @submit="submitConversationMessage"
        />
      </section>
    </div>

    <el-dialog v-model="createDialogVisible" :title="t(`${baseKey}.clarification.create_dialog_title`)" width="620px">
      <el-form label-position="top">
        <el-form-item :label="t(`${baseKey}.fields.linked_review`)">
          <el-select v-model="createForm.sourceReviewId" class="field-full" clearable>
            <el-option
              v-for="review in reviews"
              :key="review.id"
              :label="review.title || review.id"
              :value="review.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t(`${baseKey}.fields.question`)">
          <el-input v-model="createForm.question" type="textarea" :rows="4" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item :label="t(`${baseKey}.fields.blocking_level`)">
            <el-select v-model="createForm.blockingLevel" class="field-full">
              <el-option :label="t(`${baseKey}.blocking_level.blocking`)" value="BLOCKING" />
              <el-option :label="t(`${baseKey}.blocking_level.non_blocking`)" value="NON_BLOCKING" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t(`${baseKey}.fields.urgency`)">
            <el-select v-model="createForm.urgency" class="field-full">
              <el-option :label="t(`${baseKey}.priority.high`)" value="HIGH" />
              <el-option :label="t(`${baseKey}.priority.normal`)" value="NORMAL" />
              <el-option :label="t(`${baseKey}.priority.low`)" value="LOW" />
            </el-select>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!createForm.question" :loading="saving" @click="submitCreate">
          {{ t(`${baseKey}.clarification.create_submit`) }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reopenDialogVisible" :title="t(`${baseKey}.clarification.reopen_dialog_title`)" width="520px">
      <el-form label-position="top">
        <el-form-item :label="t(`${baseKey}.fields.reopen_reason`)">
          <el-input v-model="reopenReason" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reopenDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :disabled="!reopenReason.trim()"
          :loading="saving"
          @click="submitReopen"
        >
          {{ t(`${baseKey}.clarification.reopen`) }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.clarification-step {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.step-heading,
.heading-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.step-heading {
  justify-content: space-between;
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

.button-icon {
  width: 15px;
  height: 15px;
  margin-right: 6px;
}

.empty-state {
  display: flex;
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

.thread-workbench {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  min-height: 520px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
  background: #ffffff;
}

.thread-list-panel {
  display: flex;
  flex-direction: column;
  gap: 0;
  border-right: 1px solid #e2e8f0;
  background: #f8fafc;
}

.thread-list-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  width: 100%;
  padding: 12px;
  border: 0;
  border-bottom: 1px solid #e2e8f0;
  background: transparent;
  color: #0f172a;
  cursor: pointer;
  text-align: left;
}

.thread-list-item.is-active {
  background: #ffffff;
  box-shadow: inset 3px 0 0 #2563eb;
}

.thread-title {
  display: -webkit-box;
  overflow: hidden;
  font-size: 0.84rem;
  font-weight: 700;
  line-height: 1.4;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.thread-meta {
  color: #64748b;
  font-size: 0.74rem;
}

.conversation-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
}

.conversation-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.conversation-header h4 {
  margin: 0;
  color: #0f172a;
  font-size: 0.96rem;
  line-height: 1.45;
}

.conversation-header p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 0.78rem;
}

.message-stream {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 10px;
  min-height: 280px;
  padding: 16px;
  overflow: auto;
  background: #f8fafc;
}

.message-bubble {
  width: min(680px, 88%);
  padding: 10px 12px;
  border: 1px solid #dbe4ee;
  border-radius: 8px;
  background: #ffffff;
}

.message-bubble.is-answer {
  align-self: flex-end;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.message-bubble.is-system {
  align-self: center;
  width: min(560px, 92%);
  border-color: #cbd5e1;
  background: #f1f5f9;
}

.message-kind {
  color: #64748b;
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
}

.message-bubble p {
  margin: 4px 0 0;
  color: #1e293b;
  font-size: 0.86rem;
  line-height: 1.5;
}

.message-bubble time {
  display: block;
  margin-top: 6px;
  color: #94a3b8;
  font-size: 0.68rem;
}

.field-full {
  width: 100%;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

@media (max-width: 920px) {
  .thread-workbench {
    grid-template-columns: 1fr;
  }

  .thread-list-panel {
    max-height: 220px;
    overflow: auto;
    border-right: 0;
    border-bottom: 1px solid #e2e8f0;
  }
}

@media (max-width: 700px) {
  .step-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
