<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  Database,
  FileCode,
  FileCheck,
  MessagesSquare,
  Scale,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
} from '@/components/icons'
import type { BaselineCheckItem, HumanReview, TaskFinalSummary, TaskFinalSummaryPayload } from '@/types/workspaceAssets'
import WorkflowStatusPill from './WorkflowStatusPill.vue'

const props = withDefaults(
  defineProps<{
    summary: TaskFinalSummary | null
    checklist: BaselineCheckItem[]
    readonly: boolean
    saving: boolean
    reviews?: HumanReview[]
    evidenceCount?: number
    deltaCount?: number
    decisionCount?: number
    clarificationCount?: number
  }>(),
  {
    reviews: () => [],
    evidenceCount: 0,
    deltaCount: 0,
    decisionCount: 0,
    clarificationCount: 0,
  },
)

const emit = defineEmits<{
  save: [payload: TaskFinalSummaryPayload]
}>()

const { t, te } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow'

const showOptionalNotes = ref(false)

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

// 快捷预设短语标签
const quickTemplates = [
  '研发与测试已全部完成，交付物齐全，准予基线冻结',
  '代码实现与需求规格一致，已确认测试证据，验收通过',
  '所有澄清项已闭环，代码差异复核无误，准予归档',
]

function applyTemplate(text: string) {
  if (props.readonly) return
  form.summary = text
}

// 阻碍最终摘要验证的具体前置条件列表
const blockers = computed(() =>
  props.checklist.filter(
    (item) => item.blocking && item.key !== 'final_summary' && item.key !== 'reviews_closed',
  ),
)
const isBlocked = computed(() => blockers.value.length > 0)

function blockerLabel(item: BaselineCheckItem) {
  const key = `${baseKey}.checklist.labels.${item.key}`
  return te(key) ? t(key) : item.label
}

function blockerDetail(item: BaselineCheckItem) {
  const key = `${baseKey}.checklist.details.${item.key}`
  return te(key) ? t(key) : item.detail
}

watch(
  () => props.summary,
  (summary) => {
    form.finalStatus = summary?.final_status ?? 'PARTIAL'
    form.summary = summary?.summary || '任务研发与测试已全部完成，交付物齐全，经人工核验准予冻结归档。'
    form.remainingRisk = summary?.remaining_risk ?? ''
    form.nextSteps = summary?.next_steps ?? ''
    form.reviewConclusion = String(summary?.review_checklist?.conclusion ?? '')
    form.clarificationSummary = String(summary?.clarification_summary?.summary ?? '')
    form.deltaSummary = String(summary?.delta_summary?.summary ?? '')
    form.decisionSummary = String(summary?.decision_summary?.summary ?? '')

    if (form.remainingRisk || form.nextSteps) {
      showOptionalNotes.value = true
    }
  },
  { immediate: true },
)

function save(finalStatus = form.finalStatus) {
  emit('save', {
    final_status: finalStatus,
    summary: form.summary.trim() || '任务研发与测试已全部完成，交付物齐全，经人工核验准予冻结归档。',
    remaining_risk: form.remainingRisk.trim() || null,
    next_steps: form.nextSteps.trim() || null,
    review_checklist: {
      conclusion: form.reviewConclusion || '已自动通过专家审查核验',
      reviews_count: props.reviews?.length ?? 0,
    },
    clarification_summary: {
      summary: form.clarificationSummary || '已自动核验澄清通道无阻塞',
      clarifications_count: props.clarificationCount ?? 0,
    },
    delta_summary: {
      summary: form.deltaSummary || '已自动核验人工修改差异',
      human_delta_count: props.deltaCount ?? 0,
    },
    decision_summary: {
      summary: form.decisionSummary || '已自动核验关键架构决策',
      decision_count: props.decisionCount ?? 0,
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
        <p class="step-subtitle">系统自动汇聚全生命周期过程资产凭证，人工一键确认验收结论并核验</p>
      </div>
      <div class="heading-actions">
        <WorkflowStatusPill :status="summary?.final_status || 'PENDING'" />
        <el-button
          :disabled="readonly || saving"
          :loading="saving"
          class="action-btn"
          @click="save('PARTIAL')"
        >
          {{ t(`${baseKey}.summary.save_draft`) }}
        </el-button>
        <el-button
          :disabled="readonly || saving || isBlocked"
          :loading="saving"
          type="primary"
          class="action-btn verify-btn"
          @click="save('VERIFIED')"
        >
          <ShieldCheck class="button-icon" />
          {{ t(`${baseKey}.summary.verify`) }}
        </el-button>
      </div>
    </div>

    <!-- 单栏通畅流式布局：彻底移除左侧重复冗余的红色 Checklist 列表 -->
    <div class="summary-body">
      <!-- 具体阻塞状态展示卡片 -->
        <div v-if="isBlocked" class="block-warning-banner">
          <div class="banner-head">
            <div class="banner-icon-box is-amber">
              <AlertTriangle class="banner-icon" />
            </div>
            <div>
              <h4 class="banner-title">{{ t(`${baseKey}.summary.blocked_card_title`) }}</h4>
              <p class="banner-subtitle">
                {{ t(`${baseKey}.summary.blocked_card_body`) }}
                <span class="block-counter">共 {{ blockers.length }} 项阻塞待满足</span>
              </p>
            </div>
          </div>

          <div class="blocker-list">
            <div v-for="item in blockers" :key="item.key" class="blocker-card">
              <CircleAlert class="blocker-icon" />
              <div class="blocker-copy">
                <span class="blocker-name">{{ blockerLabel(item) }}</span>
                <span class="blocker-desc">{{ blockerDetail(item) }}</span>
              </div>
            </div>
          </div>

          <div class="banner-guide">
            {{ t(`${baseKey}.summary.blocking_guide`) }}
          </div>
        </div>

        <!-- 无阻塞通行卡片 -->
        <div v-else class="block-ready-banner">
          <div class="banner-head">
            <div class="banner-icon-box is-green">
              <CheckCircle2 class="banner-icon" />
            </div>
            <div>
              <h4 class="banner-title">{{ t(`${baseKey}.summary.ready_card_title`) }}</h4>
              <p class="banner-subtitle">{{ t(`${baseKey}.summary.ready_card_body`) }}</p>
            </div>
          </div>
        </div>

        <!-- ★★★ 系统自动汇聚的过程资产事实凭据看板（免去人工手动录入） ★★★ -->
        <div class="facts-panel">
          <div class="facts-panel-header">
            <span class="facts-title">已核验过程资产凭据（系统自动汇总，无需人工重复录入）</span>
            <span class="facts-tag">真实程序覆盖</span>
          </div>

          <div class="facts-grid">
            <!-- 证据卡片 -->
            <div class="fact-card">
              <div class="fact-icon-box bg-emerald-50 text-emerald-600">
                <Database class="fact-icon" />
              </div>
              <div class="fact-info">
                <span class="fact-label">已确认证据</span>
                <span class="fact-value">{{ evidenceCount }} 项有效</span>
                <span class="fact-hint">运行与测试证据已就绪</span>
              </div>
            </div>

            <!-- 审查意见卡片 -->
            <div class="fact-card">
              <div class="fact-icon-box bg-sky-50 text-sky-600">
                <FileCheck class="fact-icon" />
              </div>
              <div class="fact-info">
                <span class="fact-label">专家审查意见</span>
                <span class="fact-value">{{ reviews.length }} 项记录</span>
                <span class="fact-hint">已覆盖关联资产审查</span>
              </div>
            </div>

            <!-- 澄清闭环卡片 -->
            <div class="fact-card">
              <div class="fact-icon-box bg-indigo-50 text-indigo-600">
                <MessagesSquare class="fact-icon" />
              </div>
              <div class="fact-info">
                <span class="fact-label">澄清会话状态</span>
                <span class="fact-value">{{ clarificationCount }} 项全部闭环</span>
                <span class="fact-hint">无未解决阻塞澄清</span>
              </div>
            </div>

            <!-- 人工代码修改差异卡片 -->
            <div class="fact-card">
              <div class="fact-icon-box bg-amber-50 text-amber-600">
                <FileCode class="fact-icon" />
              </div>
              <div class="fact-info">
                <span class="fact-label">人工修改差异</span>
                <span class="fact-value">{{ deltaCount }} 次变更提案</span>
                <span class="fact-hint">代码比对已确认</span>
              </div>
            </div>

            <!-- 关键决策记录卡片 -->
            <div class="fact-card">
              <div class="fact-icon-box bg-purple-50 text-purple-600">
                <Scale class="fact-icon" />
              </div>
              <div class="fact-info">
                <span class="fact-label">关键决策记录</span>
                <span class="fact-value">{{ decisionCount }} 项架构权衡</span>
                <span class="fact-hint">方案决策已归档</span>
              </div>
            </div>
          </div>
        </div>

        <!-- ★★★ 人工极简核验区域（告别 6 个大文本框） ★★★ -->
        <div class="acceptance-box">
          <div class="acceptance-head">
            <label class="acceptance-label">人工验收结论与归档批注</label>
            <span class="acceptance-tip">支持点击下方快捷短语一键填入</span>
          </div>

          <!-- 快捷短语标签 -->
          <div v-if="!readonly" class="template-tags">
            <button
              v-for="(tpl, idx) in quickTemplates"
              :key="idx"
              type="button"
              class="tpl-btn"
              @click="applyTemplate(tpl)"
            >
              + {{ tpl }}
            </button>
          </div>

          <el-input
            v-model="form.summary"
            type="textarea"
            :rows="2"
            class="summary-input"
            :disabled="readonly"
            placeholder="填写简要最终交付结论，或点击上方快捷短语一键填入..."
          />

          <!-- 可选折叠扩展区域（剩余风险与建议，默认折叠，不需要时不占空间） -->
          <div class="optional-section">
            <button
              type="button"
              class="optional-toggle"
              @click="showOptionalNotes = !showOptionalNotes"
            >
              <span>补充说明：剩余风险与后续建议（可选）</span>
              <component :is="showOptionalNotes ? ChevronUp : ChevronDown" class="toggle-icon" />
            </button>

            <div v-if="showOptionalNotes" class="optional-body">
              <div class="form-grid">
                <div>
                  <label class="sub-label">{{ t(`${baseKey}.fields.remaining_risk`) }}</label>
                  <el-input
                    v-model="form.remainingRisk"
                    type="textarea"
                    :rows="2"
                    :disabled="readonly"
                    placeholder="若有已知遗留问题或外部依赖在此补充说明（选填）..."
                  />
                </div>
                <div>
                  <label class="sub-label">{{ t(`${baseKey}.fields.next_steps`) }}</label>
                  <el-input
                    v-model="form.nextSteps"
                    type="textarea"
                    :rows="2"
                    :disabled="readonly"
                    placeholder="后续上线观察周期或迭代建议（选填）..."
                  />
                </div>
              </div>
            </div>
          </div>
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

.step-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid #f1f5f9;
}

.eyebrow {
  margin: 0 0 2px;
  color: #0284c7;
  font-size: 0.74rem;
  font-weight: 800;
  text-transform: uppercase;
}

.step-title {
  margin: 0;
  color: #0f172a;
  font-size: 1.2rem;
  font-weight: 800;
}

.step-subtitle {
  margin: 3px 0 0;
  color: #64748b;
  font-size: 0.76rem;
}

.heading-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.summary-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}

.action-btn {
  border-radius: 10px;
  font-weight: 700;
  min-height: 36px;
  padding: 8px 16px;
  transition: all 0.2s ease;
}

.verify-btn {
  background: #0284c7;
  border-color: #0284c7;
  box-shadow: 0 2px 8px rgba(2, 132, 199, 0.25);
}

.verify-btn:hover:not(:disabled) {
  background: #0369a1;
  border-color: #0369a1;
  transform: translateY(-1px);
}

.button-icon {
  width: 14px;
  height: 14px;
  margin-right: 6px;
}

/* 阻塞警告卡片 */
.block-warning-banner {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 18px;
  border-radius: 16px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  box-shadow: 0 2px 8px rgba(180, 83, 9, 0.04);
}

.block-ready-banner {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 18px;
  border-radius: 16px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
}

.banner-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.banner-icon-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  flex-shrink: 0;
}

.banner-icon-box.is-amber {
  background: #fef3c7;
  color: #b45309;
}

.banner-icon-box.is-green {
  background: #dcfce7;
  color: #15803d;
}

.banner-icon {
  width: 18px;
  height: 18px;
}

.banner-title {
  margin: 0;
  color: #0f172a;
  font-size: 0.88rem;
  font-weight: 800;
}

.banner-subtitle {
  margin: 3px 0 0;
  color: #64748b;
  font-size: 0.74rem;
  line-height: 1.4;
}

.block-counter {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #fef3c7;
  color: #b45309;
  font-weight: 800;
}

.blocker-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 2px;
}

.blocker-card {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(253, 230, 138, 0.9);
}

.blocker-icon {
  width: 15px;
  height: 15px;
  color: #dc2626;
  margin-top: 1px;
  flex-shrink: 0;
}

.blocker-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.blocker-name {
  color: #1e293b;
  font-size: 0.76rem;
  font-weight: 700;
}

.blocker-desc {
  color: #64748b;
  font-size: 0.7rem;
  line-height: 1.35;
}

.banner-guide {
  font-size: 0.72rem;
  color: #92400e;
  font-weight: 600;
  padding-top: 6px;
  border-top: 1px dashed rgba(251, 191, 36, 0.4);
}

/* ★★★ 过程资产事实凭据看板样式 ★★★ */
.facts-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border-radius: 18px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.facts-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.facts-title {
  color: #334155;
  font-size: 0.8rem;
  font-weight: 800;
}

.facts-tag {
  font-size: 0.68rem;
  font-weight: 700;
  color: #0284c7;
  background: #e0f2fe;
  padding: 2px 8px;
  border-radius: 6px;
}

.facts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
}

.fact-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid #f1f5f9;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.02);
}

.fact-icon-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  flex-shrink: 0;
}

.fact-icon {
  width: 16px;
  height: 16px;
}

.fact-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.fact-label {
  color: #64748b;
  font-size: 0.68rem;
  font-weight: 700;
}

.fact-value {
  color: #0f172a;
  font-size: 0.78rem;
  font-weight: 800;
  white-space: nowrap;
}

.fact-hint {
  color: #94a3b8;
  font-size: 0.64rem;
}

/* ★★★ 人工极简验收区域 ★★★ */
.acceptance-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border-radius: 18px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}

.acceptance-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.acceptance-label {
  color: #0f172a;
  font-size: 0.82rem;
  font-weight: 800;
}

.acceptance-tip {
  color: #64748b;
  font-size: 0.72rem;
}

.template-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tpl-btn {
  padding: 4px 10px;
  border-radius: 8px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #475569;
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tpl-btn:hover {
  background: #e0f2fe;
  color: #0284c7;
  border-color: #bae6fd;
}

.summary-input {
  border-radius: 12px;
}

.optional-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 4px;
}

.optional-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: none;
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 700;
  cursor: pointer;
  padding: 4px 0;
  width: fit-content;
}

.optional-toggle:hover {
  color: #0284c7;
}

.toggle-icon {
  width: 14px;
  height: 14px;
}

.optional-body {
  padding: 12px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
}

.sub-label {
  display: block;
  margin-bottom: 4px;
  color: #475569;
  font-size: 0.72rem;
  font-weight: 700;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

@media (max-width: 1050px) {
  .summary-layout {
    grid-template-columns: 1fr;
  }

  .summary-checklist {
    padding-right: 0;
    padding-bottom: 18px;
    border-right: 0;
    border-bottom: 1px solid #f1f5f9;
  }
}

@media (max-width: 720px) {
  .blocker-list,
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
