<script setup lang="ts">
import { computed, proxyRefs, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Download,
  AlertCircle,
  GitBranch,
  Target,
  Wrench,
  Loader2,
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
  BookMarked,
  Check,
  Copy,
  ClipboardList,
  FileCode2,
} from '@/components/icons'
import { useCaseCenter } from '@/composables/useCaseCenter'
import CaseReportSection from './CaseReportSection.vue'
import CaseReviewTimeline from './CaseReviewTimeline.vue'
import { useMarkdownExport } from '@/composables/useMarkdownExport'
import CaseFormDialog from './CaseFormDialog.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import { renderInlineMarkdown } from '@/utils/inlineMarkdown'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const vm = proxyRefs(useCaseCenter())
const { exportCaseMarkdown } = useMarkdownExport()

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
  if (route.name === 'knowledgeCaseDetail') {
    router.push(wsId.value ? `/knowledge/cases/${wsId.value}` : '/knowledge/cases')
    return
  }
  router.push({ name: 'workspaceCases', params: { wsId: wsId.value } })
}
const handleExportRagMarkdown = () => {
  const caseDetail = vm.currentCase
  if (!caseDetail) return
  exportCaseMarkdown(caseDetail)
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

// ─── 顶部标题徽标：状态 / 优先级 / 分类 / 评审轮次的语义色 ───
const statusPillTone = (status: string) => ({
  DRAFT: 'gray',
  PENDING_REVIEW: 'blue',
  IN_REVIEW: 'amber',
  APPROVED: 'green',
  REJECTED: 'red',
}[status] || 'gray')

const priorityPillTone = (priority: string) => (
  priority === 'P0' ? 'red' : priority === 'P1' ? 'amber' : priority === 'P2' ? 'blue' : 'gray'
)

const categoryPillTone = (category: string) => (
  ({ PUBLIC: 'green', PRODUCT: 'blue', SITE: 'amber' } as Record<string, string>)[category] || 'gray'
)
const detail = computed<Record<string, any>>(() => {
  const value = vm.currentCase?.diagnosis_detail
  return value && typeof value === 'object' ? (value as Record<string, any>) : {}
})

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter(Boolean)
}

function objectList(value: unknown): Record<string, any>[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is Record<string, any> => Boolean(item) && typeof item === 'object',
  )
}

function formatIndex(index: number): string {
  return String(index + 1).padStart(2, '0')
}

function contextLocation(item: Record<string, any>): string {
  const start = Number(item.start_line)
  const end = Number(item.end_line)
  const file = String(item.file_path || '')
  if (!Number.isFinite(start)) return file
  if (Number.isFinite(end) && end !== start) return `${file}:${start}-${end}`
  return `${file}:${start}`
}

const evidenceItems = computed(() => stringList(detail.value.evidence))
const fixSteps = computed(() => stringList(detail.value.fix_steps))
const fixCode = computed(() => String(detail.value.fix_code || '').trim())
const confidence = computed(() => {
  if (detail.value.confidence === undefined || detail.value.confidence === null) return null
  const value = Number(detail.value.confidence)
  return Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : null
})
const callChainNodes = computed(() =>
  objectList(detail.value.call_chain).map((node, index) => ({
    seq: Number(node.seq ?? index + 1),
    label: [node.module, node.function].filter(Boolean).join('.') || String(node.file_path || '未命名节点'),
    filePath: String(node.file_path || ''),
    description: String(node.description || ''),
  })),
)
const codeContextItems = computed(() =>
  objectList(detail.value.code_context).map((item) => ({
    location: contextLocation(item),
    note: String(item.note || ''),
    snippet: String(item.snippet || ''),
  })),
)
const similarCases = computed(() =>
  objectList(detail.value.similar_cases).map((item) => ({
    title: String(item.title || ''),
    similarity: String(item.similarity || ''),
    summary: String(item.summary || ''),
    reference: String(item.reference || ''),
  })),
)
const hasStats = computed(
  () =>
    evidenceItems.value.length > 0 ||
    fixSteps.value.length > 0 ||
    callChainNodes.value.length > 0 ||
    confidence.value !== null,
)

const copied = ref(false)
let copyResetTimer: number | undefined
async function copyFixCode() {
  if (!fixCode.value) return
  try {
    await navigator.clipboard.writeText(fixCode.value)
    copied.value = true
    window.clearTimeout(copyResetTimer)
    copyResetTimer = window.setTimeout(() => {
      copied.value = false
    }, 1600)
  } catch {
    copied.value = false
  }
}
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
      <!-- ─── Report Header（对齐产品 / 项目详情风格） ─── -->
      <div class="mgmt-page-header">
        <div>
          <div class="mgmt-back-row">
            <button class="mgmt-back-btn" type="button" @click="goBackToList">
              <ArrowLeft :size="16" /> {{ t('case_center.report.back') }}
            </button>
          </div>
          <h2 class="mgmt-detail-title">
            {{ vm.currentCase.title }}
            <span
              class="mgmt-status-pill"
              :class="statusPillTone(vm.currentCase.status)"
            >{{ vm.currentCase.status === 'TECHNICALLY_VERIFIED' ? '物理验证归档' : t(`case_center.status.${vm.currentCase.status || 'DRAFT'}`) }}</span>
            <span class="mgmt-status-pill" :class="priorityPillTone(vm.currentCase.priority)">
              {{ vm.currentCase.priority || '-' }}
            </span>
            <span v-if="vm.currentCase.status !== 'APPROVED' || vm.currentCase.category !== 'TEMPORARY'" class="mgmt-status-pill" :class="categoryPillTone(vm.currentCase.category)">
              {{ t(`case_center.category.${vm.currentCase.category || 'PUBLIC'}`) }}
            </span>
            <span v-if="vm.currentCase.has_playbook" class="mgmt-status-pill">已晋升规程</span>
          </h2>
          <p class="mgmt-subtitle">
            <span class="mgmt-case-meta">{{ t('case_center.creator') }}: {{ vm.currentCase.creator_name || '-' }}</span>
            <span class="mgmt-case-meta">{{ t('case_center.created_at') }}: {{ formatDateTime(vm.currentCase.created_at) }}</span>
            <span v-if="vm.currentCase.updated_at" class="mgmt-case-meta">{{ t('case_center.updated_at') }}: {{ formatDateTime(vm.currentCase.updated_at) }}</span>
            <span v-if="vm.currentCase.review_round > 1" class="mgmt-case-meta">{{ t('case_center.report.round_short', { round: vm.currentCase.review_round }) }}</span>
          </p>
          <p v-if="vm.currentCase.status === 'REJECTED' && vm.currentCase.rejected_comment" class="case-reject-note">
            <XCircle :size="15" />
            <span><strong>{{ t('case_center.rejected_comment_label') }}:</strong> {{ vm.currentCase.rejected_comment }}</span>
          </p>
        </div>

        <div class="case-report-actions">
            <button class="btn-secondary" type="button" @click="handleExportRagMarkdown">
              <Download :size="16" /> {{ t('case_center.export_markdown') }}
            </button>
          <template v-if="vm.currentCase.source_task_id">
            <button class="btn-secondary" type="button" :disabled="vm.actionLoading" @click="openSourceSession">
              <MessagesSquare :size="16" /> {{ t('case_center.report.open_session') }}
            </button>
            <span class="action-separator"></span>
          </template>

          <template v-if="vm.currentCase.status === 'DRAFT' && vm.myCanManage">
            <button class="btn-secondary" type="button" :disabled="vm.actionLoading" @click="vm.openEditForm()">
              <Pencil :size="16" /> {{ t('common.edit') }}
            </button>
            <button class="btn-secondary case-btn-danger" type="button" :disabled="vm.actionLoading" @click="handleDelete">
              <Trash2 :size="16" /> {{ t('common.delete') }}
            </button>
            <button class="btn-primary" type="button" :disabled="vm.actionLoading" @click="vm.submitCase()">
              <SendHorizonal :size="16" /> {{ t('case_center.action.submit') }}
            </button>
          </template>

          <template v-else-if="vm.currentCase.status === 'PENDING_REVIEW' && vm.myCanReview">
            <button class="btn-primary" type="button" :disabled="vm.actionLoading" @click="vm.startReview()">
              <UserCheck :size="16" /> {{ t('case_center.action.start_review') }}
            </button>
          </template>

          <template v-else-if="vm.currentCase.status === 'IN_REVIEW' && vm.myCanReview">
            <button class="btn-secondary case-btn-danger" type="button" :disabled="vm.actionLoading" @click="vm.openReviewDialog('reject')">
              <XCircle :size="16" /> {{ t('case_center.action.reject') }}
            </button>
            <button class="btn-primary" type="button" :disabled="vm.actionLoading" @click="vm.openReviewDialog('approve')">
              <CheckCircle2 :size="16" /> {{ t('case_center.action.approve') }}
            </button>
          </template>

          <template v-else-if="vm.currentCase.status === 'REJECTED' && vm.myCanManage">
            <button class="btn-secondary" type="button" :disabled="vm.actionLoading" @click="vm.openEditForm()">
              <Pencil :size="16" /> {{ t('common.edit') }}
            </button>
            <button class="btn-secondary case-btn-danger" type="button" :disabled="vm.actionLoading" @click="handleDelete">
              <Trash2 :size="16" /> {{ t('common.delete') }}
            </button>
            <button class="btn-primary" type="button" :disabled="vm.actionLoading" @click="vm.resubmitCase()">
              <RotateCcw :size="16" /> {{ t('case_center.action.resubmit') }}
            </button>
          </template>

          <template v-else-if="vm.currentCase.status === 'APPROVED'">
            <span class="approved-note">
              <BookOpen :size="16" />
              {{ t('case_center.approved_note') }}
            </span>
          </template>
        </div>
      </div>

      <!-- ─── Report Body ─── -->
      <div v-if="hasStats" class="case-stats">
        <div v-if="evidenceItems.length" class="case-stat">
          <span>{{ t('case_center.field.evidence_chain') }}</span>
          <strong>{{ evidenceItems.length }}</strong>
        </div>
        <div v-if="fixSteps.length" class="case-stat">
          <span>{{ t('case_center.field.fix_steps') }}</span>
          <strong>{{ fixSteps.length }}</strong>
        </div>
        <div v-if="callChainNodes.length" class="case-stat">
          <span>{{ t('case_center.field.call_chain') }}</span>
          <strong>{{ callChainNodes.length }}</strong>
        </div>
        <div v-if="confidence !== null" class="case-stat is-accent">
          <span>{{ t('case_center.field.confidence') }}</span>
          <strong>{{ confidence }}%</strong>
        </div>
      </div>

      <div class="report-grid">
        <div class="report-main">
          <CaseReportSection index="01" :title="t('case_center.field.problem_description')" :icon="AlertCircle" tone="rose">
            <p class="section-text case-lead">{{ vm.currentCase.problem_description || t('case_center.not_set') }}</p>
          </CaseReportSection>

          <CaseReportSection index="02" :title="t('case_center.field.evidence_chain')" :icon="ClipboardList">
            <div v-if="evidenceItems.length" class="case-evidence">
              <div class="case-evidence-head"><span>序号</span><span>证据</span></div>
              <div v-for="(item, index) in evidenceItems" :key="index" class="case-evidence-row">
                <span class="case-evidence-no">{{ formatIndex(index) }}</span>
                <p class="case-evidence-text" v-html="renderInlineMarkdown(item)" />
              </div>
            </div>
            <p v-else class="section-text">{{ vm.currentCase.analysis_process || t('case_center.not_set') }}</p>
          </CaseReportSection>

          <CaseReportSection index="03" :title="t('case_center.field.root_cause')" :icon="Target" tone="amber">
            <div class="case-root-cause" v-html="renderInlineMarkdown(vm.currentCase.root_cause || t('case_center.not_set'))" />
          </CaseReportSection>

          <CaseReportSection index="04" :title="t('case_center.field.fix_steps')" :icon="Wrench" tone="emerald">
            <ol v-if="fixSteps.length" class="case-fix-steps">
              <li v-for="(step, index) in fixSteps" :key="index" class="case-fix-step">
                <span class="case-fix-no">{{ formatIndex(index) }}</span>
                <p class="case-fix-text" v-html="renderInlineMarkdown(step)" />
              </li>
            </ol>
            <p v-else class="section-text">{{ vm.currentCase.solution || t('case_center.not_set') }}</p>

            <div v-if="fixCode" class="case-code-block">
              <div class="case-code-head">
                <span class="case-code-dots" aria-hidden="true"><i></i><i></i><i></i></span>
                <span class="case-code-title">{{ t('case_center.field.fix_code') }}</span>
                <button class="case-code-copy" type="button" :title="t('case_center.report.copy_code')" @click="copyFixCode">
                  <Check v-if="copied" :size="14" />
                  <Copy v-else :size="14" />
                </button>
              </div>
              <pre class="case-code">{{ fixCode }}</pre>
            </div>
          </CaseReportSection>

          <CaseReportSection index="05" :title="t('case_center.field.call_chain')" :icon="GitBranch">
            <div v-if="callChainNodes.length" class="case-chain">
              <div v-for="(node, index) in callChainNodes" :key="index" class="case-chain-item">
                <span class="case-chain-seq">{{ node.seq }}</span>
                <div class="case-chain-body">
                  <div class="case-chain-title">
                    <span>{{ node.label }}</span>
                    <span v-if="node.filePath" class="case-chain-file">{{ node.filePath }}</span>
                  </div>
                  <p v-if="node.description" class="case-chain-desc">{{ node.description }}</p>
                </div>
              </div>
            </div>
            <p v-else class="section-text">{{ t('case_center.not_set') }}</p>
          </CaseReportSection>

          <CaseReportSection index="06" :title="t('case_center.field.code_context')" :icon="FileCode2">
            <div v-if="codeContextItems.length" class="case-context-list">
              <div v-for="(item, index) in codeContextItems" :key="index" class="case-context-item">
                <div class="case-context-title">
                  <FileCode2 :size="14" />
                  <span>{{ item.location }}</span>
                  <span v-if="item.note" class="case-context-note">{{ item.note }}</span>
                </div>
                <pre v-if="item.snippet" class="case-context-snippet">{{ item.snippet }}</pre>
              </div>
            </div>
            <pre v-else-if="vm.currentCase.code_context" class="case-context-fallback">{{ vm.currentCase.code_context }}</pre>
            <p v-else class="section-text">{{ t('case_center.not_set') }}</p>
          </CaseReportSection>

          <CaseReportSection v-if="similarCases.length" index="07" :title="t('case_center.field.similar_cases')" :icon="History">
            <div class="case-similar-list">
              <div v-for="(item, index) in similarCases" :key="index" class="case-similar-item">
                <div class="case-similar-title">
                  <span>{{ item.title }}</span>
                  <span v-if="item.similarity" class="case-similar-badge">{{ item.similarity }}</span>
                </div>
                <p v-if="item.summary" class="case-similar-summary">{{ item.summary }}</p>
                <p v-if="item.reference" class="case-similar-ref">{{ item.reference }}</p>
              </div>
            </div>
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
                <dt>{{ t('case_center.field.project') }}</dt>
                <dd>{{ vm.currentCase.project_name || t('case_center.not_set') }}</dd>
              </div>
              <div class="info-row">
                <dt>{{ t('case_center.field.repositories') }}</dt>
                <dd>
                  <template v-if="Array.isArray(vm.currentCase.repositories) && vm.currentCase.repositories.length">
                    <span
                      v-for="repo in vm.currentCase.repositories"
                      :key="repo.id || repo.name"
                      class="repo-chip"
                    >{{ repo.name }}</span>
                  </template>
                  <span v-else>{{ t('case_center.not_set') }}</span>
                </dd>
              </div>
              <div class="info-row">
                <dt>{{ t('case_center.field.workspace') }}</dt>
                <dd>{{ vm.currentCase.workspace_name || t('case_center.current_workspace') }}</dd>
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

    <!-- ─── Review decision modal ─── -->
    <ConfirmActionModal
      :show="vm.reviewDialogVisible"
      :title="vm.reviewConclusion === 'approve' ? t('case_center.action.approve') : t('case_center.action.reject')"
      :message="vm.reviewConclusion === 'approve' ? t('case_center.review_approve_message') : t('case_center.review_reject_message')"
      :cancel-text="t('common.cancel')"
      :confirm-text="vm.reviewConclusion === 'approve' ? t('case_center.action.approve') : t('case_center.action.reject')"
      :tone="vm.reviewConclusion === 'approve' ? 'success' : 'danger'"
      :loading="vm.actionLoading"
      @cancel="vm.closeReviewDialog()"
      @confirm="vm.confirmReview()"
    >
      <template #icon>
        <CheckCircle2 v-if="vm.reviewConclusion === 'approve'" class="w-6 h-6 flex-shrink-0" />
        <XCircle v-else class="w-6 h-6 flex-shrink-0" />
      </template>
      <template #content>
        <div class="review-dialog-content">
          <label class="review-dialog-label">{{ t('case_center.review_comment_label') }}</label>
          <textarea
            v-model="vm.reviewComment"
            class="review-dialog-textarea"
            rows="4"
            :placeholder="t('case_center.review_comment_placeholder')"
          />
        </div>
      </template>
    </ConfirmActionModal>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.case-report {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: none;
  width: 100%;
  margin: 0;
  overflow-y: auto;
  height: 100%;
}
/* ─── 顶部标题区：与产品 / 项目详情统一 ─── */
.mgmt-back-row {
  margin-bottom: 0.5rem;
}

.mgmt-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  font-weight: 500;
  padding: 0.4rem 0.9rem;
  color: var(--color-primary-600);
  background: var(--color-surface-white);
  border: 1px solid var(--color-primary-100);
  border-radius: 8px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.mgmt-back-btn:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-100);
}

.mgmt-detail-title {
  margin-top: 0.25rem;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.mgmt-detail-title .mgmt-status-pill {
  -webkit-text-fill-color: currentColor;
}

.mgmt-case-meta {
  color: #64748b;
  font-size: 0.85rem;
  margin-right: 0.8rem;
}

.case-reject-note {
  display: flex;
  align-items: flex-start;
  gap: 0.4rem;
  margin: 0.6rem 0 0;
  padding: 0.5rem 0.8rem;
  border: 1px solid #fecaca;
  border-radius: 8px;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 0.82rem;
}

.case-report-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: flex-end;
}
.case-btn-danger {
  color: #b91c1c;
  border-color: #fecaca;
}

.case-btn-danger:hover {
  background: #fef2f2;
  border-color: #fca5a5;
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
  grid-template-columns: minmax(0, 1fr) minmax(320px, 380px);
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

.case-lead {
  font-size: 0.94rem;
  line-height: 1.8;
  color: #1e293b;
}

.case-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
}

.case-stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 11px 14px;
  border: 1px solid #e8edf3;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
}

.case-stat span {
  font-size: 0.72rem;
  font-weight: 600;
  color: #94a3b8;
}

.case-stat strong {
  font-size: 1.15rem;
  font-weight: 700;
  color: #0f172a;
  line-height: 1;
}

.case-stat.is-accent {
  border-color: #bfdbfe;
  background: #eff6ff;
}

.case-stat.is-accent strong {
  color: #1d4ed8;
}

.case-evidence {
  border: 1px solid #e8edf3;
  border-radius: 12px;
  background: #ffffff;
  overflow: hidden;
}

.case-evidence-head,
.case-evidence-row {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.case-evidence-head {
  padding: 8px 14px;
  border-bottom: 1px solid #e8edf3;
  background: #f8fafc;
  color: #94a3b8;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.case-evidence-head span:first-child {
  padding-left: 5px;
}

.case-evidence-row {
  padding: 12px 14px;
}

.case-evidence-row + .case-evidence-row {
  border-top: 1px solid #f1f5f9;
}

.case-evidence-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  background: #eff6ff;
  color: #1d4ed8;
  font-family: var(--font-mono);
  font-size: 0.66rem;
  font-weight: 700;
}

.case-evidence-text {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.72;
  color: #334155;
  line-break: strict;
  text-wrap: pretty;
}

.case-root-cause {
  padding: 14px 16px;
  border: 1px solid #fde68a;
  border-radius: 12px;
  background: #fffbeb;
  color: #78350f;
  font-size: 0.92rem;
  font-weight: 500;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.case-fix-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.case-fix-step {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 10px;
}

.case-fix-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid #a7f3d0;
  border-radius: 8px;
  background: #ecfdf5;
  color: #047857;
  font-family: var(--font-mono);
  font-size: 0.66rem;
  font-weight: 700;
}

.case-fix-text {
  margin: 3px 0 0;
  font-size: 0.88rem;
  line-height: 1.72;
  color: #334155;
  line-break: strict;
  text-wrap: pretty;
}

.case-code-block {
  margin-top: 14px;
  border: 1px solid #1e293b;
  border-radius: 10px;
  background: #0f172a;
  overflow: hidden;
}

.case-code-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-bottom: 1px solid #1e293b;
  background: #111c33;
  color: #94a3b8;
  font-family: var(--font-mono);
  font-size: 0.68rem;
}

.case-code-dots {
  display: inline-flex;
  gap: 4px;
  margin-right: 2px;
}

.case-code-dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #475569;
}

.case-code-dots i:nth-child(1) { background: #f87171; }
.case-code-dots i:nth-child(2) { background: #fbbf24; }
.case-code-dots i:nth-child(3) { background: #4ade80; }

.case-code-title {
  color: #94a3b8;
}

.case-code-copy {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  margin-left: auto;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
}

.case-code-copy:hover {
  background: #1e293b;
  color: #e2e8f0;
}

.case-code {
  margin: 0;
  padding: 12px 14px;
  color: #e2e8f0;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  line-height: 1.6;
  white-space: pre;
  overflow: auto;
  max-width: 100%;
}

.case-chain {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.case-chain-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 13px;
  border: 1px solid #e8edf3;
  border-radius: 10px;
  background: #fbfdff;
}

.case-chain-seq {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 0.68rem;
  font-weight: 700;
}

.case-chain-body {
  min-width: 0;
  flex: 1;
}

.case-chain-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
  font-size: 0.86rem;
  font-weight: 650;
  color: #0f172a;
}

.case-chain-file {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  font-weight: 500;
  color: #94a3b8;
  overflow-wrap: anywhere;
}

.case-chain-desc {
  margin: 3px 0 0;
  font-size: 0.82rem;
  line-height: 1.65;
  color: #475569;
  overflow-wrap: anywhere;
}

.case-context-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.case-context-item {
  padding: 10px 12px;
  border: 1px solid #e8edf3;
  border-radius: 10px;
  background: #ffffff;
}

.case-context-title {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  min-width: 0;
  font-size: 0.84rem;
  font-weight: 600;
  color: #0f172a;
}

.case-context-title svg {
  flex-shrink: 0;
  color: #2563eb;
}

.case-context-title > span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.case-context-note {
  font-size: 0.72rem;
  font-weight: 500;
  color: #94a3b8;
}

.case-context-snippet {
  margin: 8px 0 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #0f172a;
  color: #e2e8f0;
  font-family: var(--font-mono);
  font-size: 0.76rem;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-all;
  overflow: auto;
  max-height: 260px;
}

.case-context-fallback {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid #e8edf3;
  border-radius: 8px;
  background: #f8fafc;
  color: #334155;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  overflow: auto;
  max-height: 260px;
}

.case-similar-list {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.case-similar-item {
  padding: 11px 13px;
  border: 1px solid #e8edf3;
  border-radius: 10px;
  background: #fbfdff;
}

.case-similar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 0.86rem;
  font-weight: 650;
  color: #0f172a;
}

.case-similar-badge {
  padding: 1px 7px;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 0.66rem;
  font-weight: 600;
}

.case-similar-summary {
  margin: 4px 0 0;
  font-size: 0.82rem;
  line-height: 1.65;
  color: #475569;
}

.case-similar-ref {
  margin: 3px 0 0;
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: #64748b;
}

.case-evidence-text :deep(.inline-code),
.case-fix-text :deep(.inline-code),
.case-root-cause :deep(.inline-code) {
  display: inline-block;
  padding: 0 4px;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  background: #f1f5f9;
  color: #0f172a;
  font-family: var(--font-mono);
  font-size: 0.88em;
  line-height: 1.45;
  white-space: nowrap;
}

.case-evidence-text :deep(.inline-nb),
.case-fix-text :deep(.inline-nb),
.case-root-cause :deep(.inline-nb) {
  white-space: nowrap;
}

.case-evidence-text :deep(strong),
.case-fix-text :deep(strong),
.case-root-cause :deep(strong) {
  color: #0f172a;
  font-weight: 700;
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

.repo-chip {
  display: inline-block;
  margin: 2px 6px 2px 0;
  padding: 2px 8px;
  border-radius: 6px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  font-size: 0.75rem;
  color: #334155;
}

@media (max-width: 1100px) {
  .report-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .report-aside {
    position: static;
  }
}

/* ─── 评审确认弹窗内容样式（与全局 ConfirmActionModal 融合） ─── */
.review-dialog-content {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.review-dialog-label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #334155;
}

.review-dialog-textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 0.625rem 0.75rem;
  border: 1px solid #cbd5e1;
  border-radius: var(--radius-md);
  font-family: inherit;
  font-size: 0.875rem;
  color: #1e293b;
  background-color: #f8fafc;
  resize: vertical;
  min-height: 96px;
  line-height: 1.5;
  transition: border-color var(--transition-fast), background-color var(--transition-fast), box-shadow var(--transition-fast);
}

.review-dialog-textarea:focus {
  outline: none;
  border-color: var(--color-primary-500);
  background-color: #ffffff;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}
</style>
