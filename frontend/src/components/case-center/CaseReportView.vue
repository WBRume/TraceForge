<script setup lang="ts">
import { computed, proxyRefs, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  AlertCircle,
  GitFork,
  Target,
  Wrench,
  Loader2,
  FolderKanban,
  Pencil,
  SendHorizonal,
  RotateCcw,
  UserCheck,
  CheckCircle2,
  XCircle,
  Trash2,
  BookOpen,
  Boxes,
  History,
  MessagesSquare,
  CalendarDays,
  UserRound,
  BookMarked,
} from 'lucide-vue-next'
import { useCaseCenter } from '@/composables/useCaseCenter'
import CaseReportSection from './CaseReportSection.vue'
import CaseReviewTimeline from './CaseReviewTimeline.vue'
import CaseFormDialog from './CaseFormDialog.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const vm = proxyRefs(useCaseCenter())

const wsId = computed(() => String(route.params.wsId || ''))
const caseId = computed(() => String(route.params.caseId || ''))

watch(
  caseId,
  (id) => {
    if (id) void vm.loadCaseById(id)
  },
  { immediate: true },
)

const formatDateTime = (value?: string | null) => {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

const goBackToList = () => {
  router.push({ name: 'workspaceCases', params: { wsId: wsId.value } })
}

const openSourceSession = () => {
  const taskId = vm.currentCase?.source_task_id
  if (!taskId) return
  router.push({ name: 'taskChat', params: { wsId: wsId.value, taskId } })
}

const handleDelete = async () => {
  await vm.deleteCase()
  if (!vm.currentCase) {
    goBackToList()
  }
}

// ─── 统计条：状态 / 优先级 / 分类 / 评审轮次的语义色圆点 ───
const statusDotTone = (status: string) => ({
  DRAFT: 'dot-slate',
  PENDING_REVIEW: 'dot-sky',
  IN_REVIEW: 'dot-amber',
  APPROVED: 'dot-emerald',
  REJECTED: 'dot-rose',
}[status] || 'dot-slate')

const priorityDotTone = (priority: string) => (
  priority === 'P0' ? 'dot-rose' : priority === 'P1' ? 'dot-amber' : priority === 'P2' ? 'dot-sky' : 'dot-slate'
)

const categoryDotTone = (category: string) => (
  ({ PUBLIC: 'dot-emerald', PRODUCT: 'dot-sky', SITE: 'dot-amber' } as Record<string, string>)[category] || 'dot-slate'
)
</script>

<template>
  <div class="case-report">
    <!-- ─── Loading ─── -->
    <div v-if="vm.detailLoading" class="report-state">
      <Loader2 :size="20" class="spin" />
      <span>{{ t('common.loading') }}</span>
    </div>

    <!-- ─── Not found ─── -->
    <div v-else-if="!vm.currentCase" class="report-state">
      <BookMarked :size="32" class="report-state-icon" />
      <span>{{ t('case_center.report.not_found') }}</span>
      <button class="btn-secondary" @click="goBackToList">
        <ArrowLeft :size="16" /> {{ t('case_center.report.back') }}
      </button>
    </div>

    <template v-else>
      <!-- ─── Report Hero ─── -->
      <header class="report-hero">
        <div class="hero-top">
          <button class="back-btn" type="button" @click="goBackToList">
            <ArrowLeft :size="16" />
            <span>{{ t('case_center.report.back') }}</span>
          </button>
          <span
            v-if="vm.currentCase.source_task_name"
            class="source-task"
            :title="vm.currentCase.source_task_id || ''"
            @click="openSourceSession"
          >
            <FolderKanban :size="14" />
            {{ vm.currentCase.source_task_name }}
          </span>
        </div>

        <div class="hero-title-block">
          <p class="hero-kicker">
            <span class="kicker-dot"></span>
            {{ t('case_center.report.kicker') }}
          </p>
          <h1 class="hero-title">{{ vm.currentCase.title }}</h1>
        </div>

        <div class="hero-meta">
          <span class="hero-meta-item">
            <UserRound :size="14" />
            {{ t('case_center.creator') }}: {{ vm.currentCase.creator_name || '-' }}
          </span>
          <span class="hero-meta-item">
            <CalendarDays :size="14" />
            {{ t('case_center.created_at') }}: {{ formatDateTime(vm.currentCase.created_at) }}
          </span>
          <span v-if="vm.currentCase.updated_at" class="hero-meta-item">
            <CalendarDays :size="14" />
            {{ t('case_center.updated_at') }}: {{ formatDateTime(vm.currentCase.updated_at) }}
          </span>
        </div>

        <!-- KPI 统计条：现代仪表盘式色彩区分 -->
        <div class="stat-strip">
          <div class="stat-card">
            <span class="stat-dot" :class="statusDotTone(vm.currentCase.status)"></span>
            <div class="stat-body">
              <span class="stat-label">{{ t('case_center.report.stat_status') }}</span>
              <span class="stat-value">{{ t(`case_center.status.${vm.currentCase.status || 'DRAFT'}`) }}</span>
            </div>
          </div>
          <div class="stat-card">
            <span class="stat-dot" :class="priorityDotTone(vm.currentCase.priority)"></span>
            <div class="stat-body">
              <span class="stat-label">{{ t('case_center.report.stat_priority') }}</span>
              <span class="stat-value">{{ vm.currentCase.priority || '-' }}</span>
            </div>
          </div>
          <div class="stat-card">
            <span class="stat-dot" :class="categoryDotTone(vm.currentCase.category)"></span>
            <div class="stat-body">
              <span class="stat-label">{{ t('case_center.report.stat_category') }}</span>
              <span class="stat-value">{{ t(`case_center.category.${vm.currentCase.category || 'TEMPORARY'}`) }}</span>
            </div>
          </div>
          <div v-if="vm.currentCase.review_round > 1" class="stat-card">
            <span class="stat-dot dot-amber"></span>
            <div class="stat-body">
              <span class="stat-label">{{ t('case_center.report.stat_round') }}</span>
              <span class="stat-value">{{ t('case_center.report.round_short', { round: vm.currentCase.review_round }) }}</span>
            </div>
          </div>
        </div>

        <p v-if="vm.currentCase.status === 'REJECTED' && vm.currentCase.rejected_comment" class="rejected-banner">
          <XCircle :size="16" class="report-reject-icon" />
          <span><strong>{{ t('case_center.rejected_comment_label') }}:</strong> {{ vm.currentCase.rejected_comment }}</span>
        </p>

        <!-- State-machine action bar -->
        <div class="hero-actions">
          <template v-if="vm.currentCase.source_task_id">
            <el-button class="open-session-btn" :disabled="vm.actionLoading" @click="openSourceSession">
              <MessagesSquare :size="16" /> {{ t('case_center.report.open_session') }}
            </el-button>
            <span class="action-separator"></span>
          </template>

          <template v-if="vm.currentCase.status === 'DRAFT' && vm.myCanManage">
            <el-button :disabled="vm.actionLoading" @click="vm.openEditForm()">
              <Pencil :size="16" /> {{ t('common.edit') }}
            </el-button>
            <el-button type="danger" plain :disabled="vm.actionLoading" @click="handleDelete">
              <Trash2 :size="16" /> {{ t('common.delete') }}
            </el-button>
            <el-button type="primary" :loading="vm.actionLoading" @click="vm.submitCase()">
              <SendHorizonal :size="16" /> {{ t('case_center.action.submit') }}
            </el-button>
          </template>

          <template v-else-if="vm.currentCase.status === 'PENDING_REVIEW' && vm.myCanReview">
            <el-button type="primary" :loading="vm.actionLoading" @click="vm.startReview()">
              <UserCheck :size="16" /> {{ t('case_center.action.start_review') }}
            </el-button>
          </template>

          <template v-else-if="vm.currentCase.status === 'IN_REVIEW' && vm.myCanReview">
            <el-button type="danger" plain :disabled="vm.actionLoading" @click="vm.openReviewDialog('reject')">
              <XCircle :size="16" /> {{ t('case_center.action.reject') }}
            </el-button>
            <el-button type="success" :disabled="vm.actionLoading" @click="vm.openReviewDialog('approve')">
              <CheckCircle2 :size="16" /> {{ t('case_center.action.approve') }}
            </el-button>
          </template>

          <template v-else-if="vm.currentCase.status === 'REJECTED' && vm.myCanManage">
            <el-button :disabled="vm.actionLoading" @click="vm.openEditForm()">
              <Pencil :size="16" /> {{ t('common.edit') }}
            </el-button>
            <el-button type="danger" plain :disabled="vm.actionLoading" @click="handleDelete">
              <Trash2 :size="16" /> {{ t('common.delete') }}
            </el-button>
            <el-button type="primary" :loading="vm.actionLoading" @click="vm.resubmitCase()">
              <RotateCcw :size="16" /> {{ t('case_center.action.resubmit') }}
            </el-button>
          </template>

          <template v-else-if="vm.currentCase.status === 'APPROVED'">
            <span class="approved-note">
              <BookOpen :size="16" />
              {{ t('case_center.approved_note') }}
            </span>
          </template>
        </div>
      </header>

      <!-- ─── Report Body ─── -->
      <div class="report-grid">
        <div class="report-main">
          <CaseReportSection index="01" :title="t('case_center.field.problem_description')" :icon="AlertCircle" tone="rose">
            <p class="section-text">{{ vm.currentCase.problem_description || t('case_center.not_set') }}</p>
          </CaseReportSection>

          <CaseReportSection index="02" :title="t('case_center.report.analysis_title')" :icon="GitFork">
            <p class="section-text">{{ vm.currentCase.analysis_process || t('case_center.not_set') }}</p>
          </CaseReportSection>

          <CaseReportSection index="03" :title="t('case_center.field.root_cause')" :icon="Target" tone="amber">
            <p class="section-text strong">{{ vm.currentCase.root_cause || t('case_center.not_set') }}</p>
          </CaseReportSection>

          <CaseReportSection index="04" :title="t('case_center.field.solution')" :icon="Wrench" tone="emerald">
            <p class="section-text strong">{{ vm.currentCase.solution || t('case_center.not_set') }}</p>
          </CaseReportSection>
        </div>

        <aside class="report-aside">
          <!-- Case info -->
          <div class="aside-card accent-sky">
            <header class="aside-card-header">
              <span class="aside-icon"><Boxes :size="15" /></span>
              <span>{{ t('case_center.report.info_title') }}</span>
            </header>
            <dl class="info-list">
              <div class="info-row">
                <dt>{{ t('case_center.field.product_name') }}</dt>
                <dd>{{ vm.currentCase.product_name || t('case_center.not_set') }}</dd>
              </div>
              <div class="info-row">
                <dt>{{ t('case_center.field.product_version') }}</dt>
                <dd>{{ vm.currentCase.product_version || t('case_center.not_set') }}</dd>
              </div>
              <div class="info-row">
                <dt>{{ t('case_center.field.site_name') }}</dt>
                <dd>{{ vm.currentCase.site_name || t('case_center.not_set') }}</dd>
              </div>
              <div class="info-row">
                <dt>{{ t('case_center.field.workspace') }}</dt>
                <dd>{{ t('case_center.current_workspace') }}</dd>
              </div>
              <div class="info-row">
                <dt>{{ t('case_center.field.code_context') }}</dt>
                <dd>
                  <pre v-if="vm.currentCase.code_context" class="code-context">{{ vm.currentCase.code_context }}</pre>
                  <span v-else>{{ t('case_center.not_set') }}</span>
                </dd>
              </div>
            </dl>
          </div>

          <!-- Review records -->
          <div class="aside-card accent-amber">
            <header class="aside-card-header">
              <span class="aside-icon"><History :size="15" /></span>
              <span>{{ t('case_center.tab.review_records') }}</span>
            </header>
            <CaseReviewTimeline :records="vm.currentCase.review_records || []" />
          </div>
        </aside>
      </div>
    </template>

    <!-- ─── Edit dialog ─── -->
    <CaseFormDialog
      :visible="vm.formVisible"
      :saving="vm.formSaving"
      :model="vm.formModel"
      :is-edit="Boolean(vm.editingId)"
      @close="vm.closeForm()"
      @save="vm.saveForm()"
    />

    <!-- ─── Review decision dialog ─── -->
    <el-dialog
      v-model="vm.reviewDialogVisible"
      :title="vm.reviewConclusion === 'approve' ? t('case_center.action.approve') : t('case_center.action.reject')"
      width="480px"
      append-to-body
    >
      <el-input
        v-model="vm.reviewComment"
        type="textarea"
        :rows="4"
        :placeholder="t('case_center.review_comment_placeholder')"
      />
      <template #footer>
        <el-button @click="vm.reviewDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button :type="vm.reviewConclusion === 'approve' ? 'success' : 'danger'" @click="vm.confirmReview()">
          {{ vm.reviewConclusion === 'approve' ? t('case_center.action.approve') : t('case_center.action.reject') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.case-report {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1240px;
  width: 100%;
  margin: 0 auto;
  overflow-y: auto;
  height: 100%;
}

.report-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #94a3b8;
  padding: 80px 0;
  font-size: 0.9rem;
}

.report-state-icon {
  color: #cbd5e1;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ─── Hero (modern card masthead) ─── */
.report-hero {
  padding: 18px 22px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  border-radius: 16px;
  background: #ffffff;
  border: 1px solid #e8edf3;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04), 0 8px 24px -12px rgba(16, 24, 40, 0.08);
}

.hero-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #475569;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.back-btn:hover {
  color: var(--color-primary-600);
  border-color: #bae6fd;
  background: #f8fafc;
}

.source-task {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.74rem;
  color: #475569;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  padding: 4px 12px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.2s;
}

.source-task:hover {
  color: #0284c7;
  border-color: #bae6fd;
  background: #f0f9ff;
}

.source-task svg {
  flex-shrink: 0;
  color: #94a3b8;
}

.source-task:hover svg {
  color: #0ea5e9;
}

.hero-title-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hero-kicker {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #64748b;
}

.kicker-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.hero-title {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #0f172a;
  line-height: 1.35;
  word-break: break-word;
}

.hero-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 0.78rem;
  color: #64748b;
}

.hero-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  color: #475569;
  background: #ffffff;
  border: 1px solid #e8edf3;
  border-radius: 999px;
  padding: 3px 12px;
}

.hero-meta-item svg {
  color: #94a3b8;
  flex-shrink: 0;
}

/* KPI 统计条 */
.stat-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fafbfc;
  border: 1px solid #eef2f6;
  border-radius: 12px;
  padding: 10px 14px;
  transition: border-color 0.2s, background 0.2s;
}

.stat-card:hover {
  background: #ffffff;
  border-color: #e2e8f0;
}

.stat-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot-sky { background: #0ea5e9; }
.dot-emerald { background: #10b981; }
.dot-amber { background: #f59e0b; }
.dot-rose { background: #f43f5e; }
.dot-slate { background: #94a3b8; }

.stat-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.stat-label {
  font-size: 0.66rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #94a3b8;
}

.stat-value {
  font-size: 0.9rem;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rejected-banner {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0;
  padding: 10px 14px;
  border-radius: 10px;
  background: #fff1f2;
  border: 1px solid #fecdd3;
  color: #be123c;
  font-size: 0.82rem;
  line-height: 1.55;
}

.report-reject-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: #fb7185;
}

.hero-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 14px;
  border-top: 1px solid #eef2f6;
  flex-wrap: wrap;
}

.action-separator {
  width: 1px;
  height: 22px;
  background: #e2e8f0;
}

.open-session-btn {
  margin-right: auto;
}

.approved-note {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #047857;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 0.82rem;
  font-weight: 600;
}

/* ─── Grid ─── */
.report-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 16px;
  align-items: start;
}

.report-main {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.section-text {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.75;
  color: var(--color-text-body);
  white-space: pre-wrap;
  word-break: break-word;
}

/* 根因 / 方案：柔和浅色强调块（无边框条） */
.report-section.tone-amber .section-text.strong {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 12px;
  padding: 12px 14px;
  color: #78350f;
  font-weight: 500;
}

.report-section.tone-emerald .section-text.strong {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  border-radius: 12px;
  padding: 12px 14px;
  color: #064e3b;
  font-weight: 500;
}

/* ─── Aside ─── */
.report-aside {
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: sticky;
  top: 0;
}

.aside-card {
  background: #ffffff;
  border: 1px solid #e8edf3;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
}

.aside-card-header {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 13px 16px;
  border-bottom: 1px solid #f1f5f9;
  font-size: 0.85rem;
  font-weight: 600;
  color: #0f172a;
  background: #fcfdfe;
}

.aside-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  flex-shrink: 0;
}

.accent-sky .aside-icon {
  background: #e0f2fe;
  color: #0284c7;
}

.accent-amber .aside-icon {
  background: #fef3c7;
  color: #b45309;
}

.info-list {
  margin: 0;
  padding: 8px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.info-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.info-row dt {
  font-size: 0.7rem;
  font-weight: 600;
  color: #94a3b8;
  letter-spacing: 0.02em;
}

.info-row dd {
  margin: 0;
  font-size: 0.82rem;
  color: var(--color-text-body);
  line-height: 1.5;
  word-break: break-word;
  white-space: pre-wrap;
}

.code-context {
  margin: 0;
  padding: 8px 10px;
  border: 1px solid #e8edf3;
  border-radius: 8px;
  background: #f8fafc;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  line-height: 1.55;
  color: #334155;
  overflow: auto;
  max-height: 220px;
  white-space: pre-wrap;
  word-break: break-all;
}

@media (max-width: 1100px) {
  .report-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .report-aside {
    position: static;
  }
}
</style>
