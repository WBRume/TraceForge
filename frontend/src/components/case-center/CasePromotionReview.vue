<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Sparkles, ChevronLeft, ChevronRight, FileText } from 'lucide-vue-next'
import type { PromotionDraft } from '@/types/playbookPromotion'

const draft = defineModel<PromotionDraft>({ required: true })
const props = defineProps<{ cases: { id: string; title: string }[]; busy: boolean; error: string }>()
const emit = defineEmits<{ confirm: []; discard: []; merge: [] }>()

const lines = (value: string) => value.split('\n')
const activeIndex = ref(0)

watch(
  () => draft.value.playbooks.length,
  (len) => {
    if (activeIndex.value >= len) {
      activeIndex.value = Math.max(0, len - 1)
    }
  },
  { immediate: true },
)

const activeCandidate = computed(() => {
  return draft.value.playbooks[activeIndex.value] || draft.value.playbooks[0] || null
})

const getCaseTitle = (id: string) => {
  return props.cases.find((c) => c.id === id)?.title || id
}
</script>

<template>
  <section class="promotion-review">
    <!-- 头部草案概览与状态说明 -->
    <header class="review-header-card">
      <div class="review-heading">
        <div class="title-with-badge">
          <div class="header-icon-badge">
            <Sparkles :size="18" />
          </div>
          <div>
            <h3>确认规程草案</h3>
            <p class="subtitle">AI 提炼归纳的诊断规程与症状排查经验，可审查并编辑各规程细节后入库</p>
          </div>
        </div>
        <div class="draft-badge">
          <span>{{ draft.playbooks.length }} 套规程 · 待入库</span>
        </div>
      </div>

      <div v-if="draft.grouping_reason" class="grouping-reason-box">
        <div class="reason-label">
          <Sparkles :size="14" />
          <span>AI 分组策略依据</span>
        </div>
        <p class="grouping-reason">{{ draft.grouping_reason }}</p>
      </div>

      <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    </header>

    <!-- 主体：Master-Detail 布局（非瀑布流，规程间切换） -->
    <div class="review-layout" :class="{ 'single-playbook': draft.playbooks.length <= 1 }">
      <!-- 左侧：规程导航目录 (Master Rail) -->
      <aside v-if="draft.playbooks.length > 1" class="playbook-nav-rail">
        <div class="nav-rail-header">
          <span class="nav-rail-title">规程清单</span>
          <span class="nav-rail-count">{{ draft.playbooks.length }} 套</span>
        </div>
        <div class="nav-items-list" role="tablist">
          <button
            v-for="(candidate, index) in draft.playbooks"
            :key="index"
            type="button"
            role="tab"
            :aria-selected="activeIndex === index"
            class="playbook-nav-item"
            :class="{ active: activeIndex === index }"
            @click="activeIndex = index"
          >
            <div class="nav-item-top">
              <span class="playbook-chip">规程 {{ index + 1 }}</span>
              <span class="cases-count-tag">{{ candidate.source_case_ids.length }} 个案例</span>
            </div>
            <div class="playbook-nav-title" :title="candidate.title">
              {{ candidate.title || '（未设置规程标题）' }}
            </div>
            <div class="nav-item-cases-preview">
              <span
                v-for="cid in candidate.source_case_ids.slice(0, 2)"
                :key="cid"
                class="case-micro-tag"
                :title="getCaseTitle(cid)"
              >
                {{ getCaseTitle(cid) }}
              </span>
              <span v-if="candidate.source_case_ids.length > 2" class="case-micro-more">
                +{{ candidate.source_case_ids.length - 2 }}
              </span>
            </div>
          </button>
        </div>
      </aside>

      <!-- 右侧：当前选中规程的聚焦编辑卡片 (Detail Workbench) -->
      <main v-if="activeCandidate" class="playbook-detail-card">
        <div class="detail-card-toolbar">
          <div class="detail-card-title-group">
            <span class="detail-badge">规程 {{ activeIndex + 1 }}</span>
            <span class="detail-hint">正在审查第 {{ activeIndex + 1 }} / {{ draft.playbooks.length }} 套规程</span>
          </div>

          <div v-if="draft.playbooks.length > 1" class="pagination-controls">
            <button
              type="button"
              class="pager-btn"
              :disabled="activeIndex === 0"
              @click="activeIndex--"
              title="查看上一套规程"
            >
              <ChevronLeft :size="16" />
              <span>上一套</span>
            </button>
            <span class="pager-indicator">{{ activeIndex + 1 }} / {{ draft.playbooks.length }}</span>
            <button
              type="button"
              class="pager-btn"
              :disabled="activeIndex === draft.playbooks.length - 1"
              @click="activeIndex++"
              title="查看下一套规程"
            >
              <span>下一套</span>
              <ChevronRight :size="16" />
            </button>
          </div>
        </div>

        <article class="editor-content">
          <!-- 包含案例展示 -->
          <div class="field-block source-cases-block">
            <span class="field-label">包含案例</span>
            <ul class="cases-pills-list">
              <li v-for="id in activeCandidate.source_case_ids" :key="id" class="case-pill">
                <FileText :size="14" class="case-icon" />
                <span class="case-text">{{ getCaseTitle(id) }}</span>
              </li>
            </ul>
          </div>

          <!-- 规程标题输入 -->
          <div class="field-block">
            <div class="field-label-row">
              <label :for="`playbook-title-${activeIndex}`" class="field-label">规程标题</label>
              <span class="char-count">{{ activeCandidate.title.length }}/200</span>
            </div>
            <input
              :id="`playbook-title-${activeIndex}`"
              v-model="activeCandidate.title"
              :disabled="busy"
              maxlength="200"
              placeholder="请输入具有概括性的诊断规程标题..."
              class="form-input"
            />
          </div>

          <!-- 定位方法 -->
          <div class="field-block">
            <label :for="`playbook-summary-${activeIndex}`" class="field-label">定位方法</label>
            <textarea
              :id="`playbook-summary-${activeIndex}`"
              v-model="activeCandidate.summary"
              :disabled="busy"
              rows="4"
              placeholder="描述该规程的核心定位方法、复现手段与证伪核对策略..."
              class="form-textarea"
            />
          </div>

          <!-- 症状短语 -->
          <div class="field-block">
            <div class="field-label-row">
              <label :for="`playbook-symptoms-${activeIndex}`" class="field-label">症状短语</label>
              <span class="field-hint">每行一条短语，用于故障识别与模式匹配</span>
            </div>
            <textarea
              :id="`playbook-symptoms-${activeIndex}`"
              :value="activeCandidate.symptoms.join('\n')"
              :disabled="busy"
              rows="3"
              placeholder="例如：&#10;配置更新后实例仍执行旧版本&#10;同一账号在不同会话展示不一致"
              class="form-textarea"
              @input="activeCandidate.symptoms = lines(($event.target as HTMLTextAreaElement).value)"
            />
          </div>

          <!-- 诊断步骤 -->
          <div class="field-block">
            <div class="field-label-row">
              <label :for="`playbook-steps-${activeIndex}`" class="field-label">诊断步骤</label>
              <span class="field-hint">每行一个具体排查步骤</span>
            </div>
            <textarea
              :id="`playbook-steps-${activeIndex}`"
              :value="activeCandidate.steps.join('\n')"
              :disabled="busy"
              rows="6"
              placeholder="例如：&#10;1. 先把展示或执行所用的版本与权威源中的版本核对&#10;2. 验证受控重载后实例是否收敛"
              class="form-textarea"
              @input="activeCandidate.steps = lines(($event.target as HTMLTextAreaElement).value)"
            />
          </div>
        </article>
      </main>
    </div>

    <!-- 底部操作栏（自然排列，避免遮挡内容） -->
    <footer class="review-actions-bar">
      <div class="actions-left-note">
        <span>核对并微调所有规程后即可入库至诊断知识库</span>
      </div>
      <div class="actions-right-btns">
        <button type="button" class="btn-secondary" :disabled="busy" @click="emit('discard')">
          放弃草案
        </button>
        <button
          v-if="draft.playbooks.length > 1"
          type="button"
          class="btn-secondary"
          :disabled="busy"
          @click="emit('merge')"
        >
          全部合并，重新提炼
        </button>
        <button type="button" class="btn-primary" :disabled="busy" @click="emit('confirm')">
          {{ busy ? '处理中...' : '确认入库' }}
        </button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.promotion-review {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
}

.review-header-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.review-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.title-with-badge {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-icon-badge {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: #eff6ff;
  color: #2563eb;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.title-with-badge h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}

.title-with-badge .subtitle {
  margin: 2px 0 0 0;
  font-size: 13px;
  color: #64748b;
}

.draft-badge span {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 9999px;
  background: #fef3c7;
  color: #b45309;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid #fde68a;
}

.grouping-reason-box {
  background: #ffffff;
  border: 1px solid #e0e7ff;
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.reason-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #4f46e5;
}

.grouping-reason {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
}

.error-banner {
  margin: 0;
  padding: 8px 12px;
  border-radius: 6px;
  background: #fef2f2;
  color: #dc2626;
  font-size: 13px;
  border: 1px solid #fecaca;
}

/* Master-Detail 布局（非瀑布流） */
.review-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.review-layout.single-playbook {
  grid-template-columns: 1fr;
}

/* 左侧导航栏 */
.playbook-nav-rail {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.nav-rail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 4px 6px 4px;
  border-bottom: 1px solid #f1f5f9;
}

.nav-rail-title {
  font-size: 13px;
  font-weight: 700;
  color: #334155;
}

.nav-rail-count {
  font-size: 12px;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 9999px;
}

.nav-items-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.playbook-nav-item {
  width: 100%;
  text-align: left;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all 0.15s ease;
}

.playbook-nav-item:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
}

.playbook-nav-item.active {
  background: #eff6ff;
  border-color: #3b82f6;
  box-shadow: 0 0 0 1px #3b82f6;
}

.nav-item-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.playbook-chip {
  font-size: 12px;
  font-weight: 700;
  color: #1d4ed8;
}

.cases-count-tag {
  font-size: 11px;
  color: #64748b;
}

.playbook-nav-title {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-item-cases-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.case-micro-tag {
  font-size: 11px;
  color: #475569;
  background: rgba(0, 0, 0, 0.04);
  padding: 1px 6px;
  border-radius: 4px;
  max-width: 120px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.case-micro-more {
  font-size: 11px;
  color: #94a3b8;
}

/* 右侧单套规程卡片 */
.playbook-detail-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-card-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid #f1f5f9;
  flex-wrap: wrap;
  gap: 10px;
}

.detail-card-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.detail-badge {
  background: #dbeafe;
  color: #1e40af;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 700;
}

.detail-hint {
  font-size: 13px;
  color: #64748b;
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pager-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  font-size: 12px;
  font-weight: 500;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s;
}

.pager-btn:hover:not(:disabled) {
  background: #f8fafc;
  border-color: #94a3b8;
}

.pager-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.pager-indicator {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.editor-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.field-label {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}

.field-hint {
  font-size: 12px;
  color: #64748b;
  font-weight: 400;
}

.char-count {
  font-size: 12px;
  color: #94a3b8;
}

.cases-pills-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  list-style: none;
  padding: 0;
  margin: 0;
}

.case-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 12px;
  color: #334155;
}

.case-icon {
  color: #64748b;
}

.form-input,
.form-textarea {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 10px 12px;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.5;
  color: #0f172a;
  background: #ffffff;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.form-input:focus,
.form-textarea:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

.form-input:disabled,
.form-textarea:disabled {
  background: #f8fafc;
  color: #94a3b8;
  cursor: not-allowed;
}

.form-textarea {
  resize: vertical;
}

/* 底部操作栏 */
.review-actions-bar {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.actions-left-note {
  font-size: 13px;
  color: #64748b;
}

.actions-right-btns {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.btn-primary,
.btn-secondary {
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  border: 1px solid transparent;
}

.btn-primary {
  background: #0284c7;
  color: #ffffff;
}

.btn-primary:hover:not(:disabled) {
  background: #0369a1;
}

.btn-secondary {
  background: #ffffff;
  border-color: #cbd5e1;
  color: #334155;
}

.btn-secondary:hover:not(:disabled) {
  background: #f8fafc;
  border-color: #94a3b8;
}

.btn-primary:disabled,
.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 860px) {
  .review-layout {
    grid-template-columns: 1fr;
  }
}
</style>
