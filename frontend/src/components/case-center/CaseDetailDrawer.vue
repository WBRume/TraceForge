<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Loader2,
  Pencil,
  SendHorizonal,
  RotateCcw,
  UserCheck,
  CheckCircle2,
  XCircle,
  Trash2,
  FolderKanban,
  BookOpen,
} from 'lucide-vue-next'
import CaseStatusPill from './CaseStatusPill.vue'
import CaseCategoryTag from './CaseCategoryTag.vue'
import CasePriorityTag from './CasePriorityTag.vue'
import CaseConversationReplay from './CaseConversationReplay.vue'
import CaseReviewTimeline from './CaseReviewTimeline.vue'

const props = defineProps<{
  visible: boolean
  wsId: string
  caseData: any
  loading: boolean
  actionLoading: boolean
  myCanManage: boolean
  myCanReview: boolean
}>()

const emit = defineEmits<{
  close: []
  edit: []
  submit: []
  startReview: []
  resubmit: []
  delete: []
  review: [payload: { conclusion: 'approve' | 'reject'; comment: string }]
}>()

const { t } = useI18n()

const activeTab = ref('info')
const reviewDialogVisible = ref(false)
const reviewConclusion = ref<'approve' | 'reject'>('approve')
const reviewComment = ref('')

const openReviewDialog = (conclusion: 'approve' | 'reject') => {
  reviewConclusion.value = conclusion
  reviewComment.value = ''
  reviewDialogVisible.value = true
}

const confirmReview = () => {
  reviewDialogVisible.value = false
  emit('review', { conclusion: reviewConclusion.value, comment: reviewComment.value })
}

const infoRows = (c: any) => [
  { label: t('case_center.field.problem_description'), value: c.problem_description, strong: true },
  { label: t('case_center.field.product_name'), value: c.product_name },
  { label: t('case_center.field.product_version'), value: c.product_version },
  { label: t('case_center.field.site_name'), value: c.site_name },
  { label: t('case_center.field.workspace'), value: t('case_center.current_workspace') },
  { label: t('case_center.field.code_context'), value: c.code_context },
  { label: t('case_center.field.analysis_process'), value: c.analysis_process },
  { label: t('case_center.field.root_cause'), value: c.root_cause, strong: true },
  { label: t('case_center.field.solution'), value: c.solution, strong: true },
]
</script>

<template>
  <el-drawer
    :model-value="visible"
    size="640px"
    :with-header="false"
    :close-on-click-modal="false"
    @close="emit('close')"
  >
    <div v-if="loading" class="drawer-state">
      <Loader2 class="w-5 h-5 spin" />
      <span>{{ t('common.loading') }}</span>
    </div>

    <template v-else-if="caseData">
      <div class="drawer-header">
        <div class="header-top">
          <h3 class="case-title">{{ caseData.title }}</h3>
          <CaseStatusPill :status="caseData.status" />
        </div>
        <div class="header-tags">
          <CaseCategoryTag :category="caseData.category" />
          <CasePriorityTag :priority="caseData.priority" />
          <span v-if="caseData.source_task_name" class="source-task" :title="caseData.source_task_id">
            <FolderKanban class="w-3 h-3" />
            {{ caseData.source_task_name }}
          </span>
          <span class="round-badge" v-if="caseData.review_round > 1">
            {{ t('case_center.review_round', { round: caseData.review_round }) }}
          </span>
        </div>
        <div class="header-meta">
          <span>{{ t('case_center.creator') }}: {{ caseData.creator_name || '-' }}</span>
          <span>{{ t('case_center.created_at') }}: {{ new Date(caseData.created_at).toLocaleString() }}</span>
          <span v-if="caseData.updated_at">{{ t('case_center.updated_at') }}: {{ new Date(caseData.updated_at).toLocaleString() }}</span>
        </div>
        <p v-if="caseData.status === 'REJECTED' && caseData.rejected_comment" class="rejected-banner">
          {{ t('case_center.rejected_comment_label') }}: {{ caseData.rejected_comment }}
        </p>
      </div>

      <el-tabs v-model="activeTab" class="drawer-tabs">
        <el-tab-pane :label="t('case_center.tab.info')" name="info">
          <div class="info-list">
            <div v-for="row in infoRows(caseData)" :key="row.label" class="info-row" :class="{ strong: row.strong }">
              <div class="info-label">{{ row.label }}</div>
              <div class="info-value">{{ row.value || t('case_center.not_set') }}</div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane :label="t('case_center.tab.replay')" name="replay">
          <CaseConversationReplay
            :ws-id="wsId"
            :source-task-id="caseData.source_task_id || ''"
            :snapshot="caseData.conversation_snapshot || null"
          />
        </el-tab-pane>

        <el-tab-pane :label="t('case_center.tab.review_records')" name="records">
          <CaseReviewTimeline :records="caseData.review_records || []" />
        </el-tab-pane>
      </el-tabs>

      <div class="drawer-footer">
        <template v-if="caseData.status === 'DRAFT' && myCanManage">
          <el-button :disabled="actionLoading" @click="emit('edit')">
            <Pencil class="w-4 h-4" /> {{ t('common.edit') }}
          </el-button>
          <el-button type="danger" plain :disabled="actionLoading" @click="emit('delete')">
            <Trash2 class="w-4 h-4" /> {{ t('common.delete') }}
          </el-button>
          <el-button type="primary" :loading="actionLoading" @click="emit('submit')">
            <SendHorizonal class="w-4 h-4" /> {{ t('case_center.action.submit') }}
          </el-button>
        </template>

        <template v-else-if="caseData.status === 'PENDING_REVIEW' && myCanReview">
          <el-button type="primary" :loading="actionLoading" @click="emit('startReview')">
            <UserCheck class="w-4 h-4" /> {{ t('case_center.action.start_review') }}
          </el-button>
        </template>

        <template v-else-if="caseData.status === 'IN_REVIEW' && myCanReview">
          <el-button type="danger" plain :disabled="actionLoading" @click="openReviewDialog('reject')">
            <XCircle class="w-4 h-4" /> {{ t('case_center.action.reject') }}
          </el-button>
          <el-button type="success" :disabled="actionLoading" @click="openReviewDialog('approve')">
            <CheckCircle2 class="w-4 h-4" /> {{ t('case_center.action.approve') }}
          </el-button>
        </template>

        <template v-else-if="caseData.status === 'REJECTED' && myCanManage">
          <el-button :disabled="actionLoading" @click="emit('edit')">
            <Pencil class="w-4 h-4" /> {{ t('common.edit') }}
          </el-button>
          <el-button type="danger" plain :disabled="actionLoading" @click="emit('delete')">
            <Trash2 class="w-4 h-4" /> {{ t('common.delete') }}
          </el-button>
          <el-button type="primary" :loading="actionLoading" @click="emit('resubmit')">
            <RotateCcw class="w-4 h-4" /> {{ t('case_center.action.resubmit') }}
          </el-button>
        </template>

        <template v-else-if="caseData.status === 'APPROVED'">
          <span class="approved-note">
            <BookOpen class="w-4 h-4" />
            {{ t('case_center.approved_note') }}
          </span>
        </template>
      </div>

      <el-dialog
        v-model="reviewDialogVisible"
        :title="reviewConclusion === 'approve' ? t('case_center.action.approve') : t('case_center.action.reject')"
        width="480px"
        append-to-body
      >
        <el-input
          v-model="reviewComment"
          type="textarea"
          :rows="4"
          :placeholder="t('case_center.review_comment_placeholder')"
        />
        <template #footer>
          <el-button @click="reviewDialogVisible = false">{{ t('common.cancel') }}</el-button>
          <el-button :type="reviewConclusion === 'approve' ? 'success' : 'danger'" @click="confirmReview">
            {{ reviewConclusion === 'approve' ? t('case_center.action.approve') : t('case_center.action.reject') }}
          </el-button>
        </template>
      </el-dialog>
    </template>
  </el-drawer>
</template>

<style scoped>
.drawer-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #94a3b8;
  padding: 60px 0;
}

.drawer-header {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-bottom: 14px;
  border-bottom: 1px solid #f1f5f9;
  margin-bottom: 4px;
}

.header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.case-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--color-primary-900);
  min-width: 0;
}

.header-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.source-task {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.72rem;
  color: #64748b;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  padding: 1px 8px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.round-badge {
  font-size: 0.72rem;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 999px;
  padding: 1px 8px;
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 0.75rem;
  color: #94a3b8;
}

.rejected-banner {
  margin: 0;
  padding: 8px 12px;
  border-radius: 8px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
  font-size: 0.82rem;
  line-height: 1.5;
}

.drawer-tabs {
  flex: 1;
  min-height: 0;
}

.info-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.info-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 0;
  border-bottom: 1px solid #f8fafc;
}

.info-row.strong {
  background: #f8fafc;
  border-radius: 8px;
  padding: 10px 12px;
  margin: 4px 0;
  border-bottom: none;
}

.info-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
}

.info-value {
  font-size: 0.85rem;
  color: #1e293b;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.drawer-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 14px;
  border-top: 1px solid #f1f5f9;
}

.approved-note {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #047857;
  font-size: 0.85rem;
  font-weight: 600;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
