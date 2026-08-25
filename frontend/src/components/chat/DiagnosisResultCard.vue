<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Bot,
  Check,
  CheckCircle2,
  ClipboardList,
  Code2,
  Copy,
  Download,
  ExternalLink,
  FileCode2,
  GitBranch,
  History,
  ListChecks,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  X,
} from 'lucide-vue-next'
import {
  normalizeDiagnosisPayload,
  type DiagnosisCallChainNode,
  type DiagnosisCodeContextItem,
  type DiagnosisResultPayload,
} from '@/types/diagnosis'

const props = defineProps<{
  payload: DiagnosisResultPayload
  status: string
  extractedFromAi: boolean
  caseLink: string
  saving: boolean
  caseCreating: boolean
  summarizing?: boolean
  adopted?: boolean
}>()

const emit = defineEmits<{
  save: [payload: DiagnosisResultPayload]
  confirm: []
  openCase: [caseId: string]
  export: [payload: DiagnosisResultPayload]
  regenerate: []
}>()

const { t } = useI18n()

const local = ref<DiagnosisResultPayload>(normalizeDiagnosisPayload(props.payload))
const editing = shallowRef(false)
const copied = shallowRef(false)

watch(
  () => props.payload,
  (next) => {
    local.value = normalizeDiagnosisPayload(next)
  },
  { deep: false },
)

const resultConfirmed = computed(() => String(props.status || '') === 'CONFIRMED')
const adopted = computed(() => props.adopted || resultConfirmed.value || Boolean(props.caseLink))
const canEdit = computed(() => !adopted.value && !props.saving)

const hasContent = computed(() => {
  const value = local.value
  return Boolean(
    value.summary ||
      value.root_cause ||
      value.evidence_chain ||
      value.fix_suggestion ||
      value.fix_code ||
      value.code_context.length ||
      value.similar_cases.length ||
      value.call_chain.length,
  )
})

const sortedCallChain = computed(() =>
  [...local.value.call_chain].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0)),
)

const confidenceLabel = computed(() => `${local.value.confidence}%`)

function startEdit() {
  if (!canEdit.value) return
  editing.value = true
}

function cancelEdit() {
  local.value = normalizeDiagnosisPayload(props.payload)
  editing.value = false
}

function handleSave() {
  emit('save', normalizeDiagnosisPayload(local.value))
  editing.value = false
}

async function copyFixCode() {
  const code = String(local.value.fix_code || '').trim()
  if (!code) return
  try {
    await navigator.clipboard.writeText(code)
    copied.value = true
    window.setTimeout(() => {
      copied.value = false
    }, 1500)
  } catch {
    copied.value = false
  }
}

function addCodeContext() {
  local.value.code_context.push({ file_path: '' })
}

function removeCodeContext(index: number) {
  local.value.code_context.splice(index, 1)
}

function addSimilarCase() {
  local.value.similar_cases.push({ title: '' })
}

function removeSimilarCase(index: number) {
  local.value.similar_cases.splice(index, 1)
}

function addCallChain() {
  const nextSeq =
    local.value.call_chain.reduce((max, node) => Math.max(max, Number(node.seq ?? 0)), 0) + 1
  local.value.call_chain.push({ seq: nextSeq })
}

function removeCallChain(index: number) {
  local.value.call_chain.splice(index, 1)
}

function lineLabel(item: DiagnosisCodeContextItem): string {
  const start = item.start_line
  const end = item.end_line
  let location = ''
  if (start && end && end !== start) location = `:${start}-${end}`
  else if (start) location = `:${start}`
  return `${item.file_path || ''}${location}`
}

function chainLabel(node: DiagnosisCallChainNode): string {
  return [node.module, node.function].filter(Boolean).join('.') || node.file_path || ''
}
</script>

<template>
  <div class="diagnosis-card">
    <div class="dc-header">
      <div class="dc-header-row">
        <ClipboardList class="dc-icon" />
        <span class="dc-title">{{ t('diagnosis.panel_title') }}</span>
        <span v-if="extractedFromAi" class="dc-pill dc-pill-ai">
          <Bot class="dc-pill-icon" />
          {{ t('diagnosis.ai_filled') }}
        </span>
        <span v-if="resultConfirmed" class="dc-pill dc-pill-confirmed">{{ t('diagnosis.result_confirmed') }}</span>
        <span v-else class="dc-pill dc-pill-draft">{{ t('diagnosis.result_draft') }}</span>
        <button
          v-if="canEdit && !editing && !summarizing"
          class="dc-btn-icon"
          type="button"
          :title="t('diagnosis.edit')"
          @click="startEdit"
        >
          <Pencil class="dc-btn-icon-svg" />
        </button>
      </div>
    </div>

    <div v-if="!hasContent && !editing" class="dc-empty">{{ t('diagnosis.result_empty') }}</div>

    <div v-else class="dc-body">
      <!-- 结果内容 / 根因结论 -->
      <div class="dc-section">
        <div class="dc-section-head">
          <ListChecks class="dc-section-icon" />
          <span>{{ t('diagnosis.result_content') }}</span>
        </div>
        <template v-if="editing">
          <label class="dc-label">{{ t('diagnosis.summary') }}</label>
          <textarea v-model="local.summary" class="dc-textarea" rows="3" :placeholder="t('diagnosis.summary_placeholder')" />
          <label class="dc-label">{{ t('diagnosis.root_cause') }}</label>
          <textarea v-model="local.root_cause" class="dc-textarea" rows="2" :placeholder="t('diagnosis.root_cause_placeholder')" />
        </template>
        <template v-else>
          <p v-if="local.summary" class="dc-text dc-summary">{{ local.summary }}</p>
          <p v-if="local.root_cause" class="dc-text dc-root-cause">{{ local.root_cause }}</p>
        </template>
      </div>

      <!-- 证据链 -->
      <div v-if="local.evidence_chain || editing" class="dc-section">
        <div class="dc-section-head">
          <ClipboardList class="dc-section-icon" />
          <span>{{ t('diagnosis.evidence_chain') }}</span>
        </div>
        <textarea v-if="editing" v-model="local.evidence_chain" class="dc-textarea" rows="3" :placeholder="t('diagnosis.evidence_chain_placeholder')" />
        <p v-else class="dc-text">{{ local.evidence_chain }}</p>
      </div>

      <!-- 代码上下文 -->
      <div v-if="local.code_context.length || editing" class="dc-section">
        <div class="dc-section-head">
          <FileCode2 class="dc-section-icon" />
          <span>{{ t('diagnosis.code_context') }}</span>
        </div>
        <div v-for="(item, index) in local.code_context" :key="index" class="dc-item">
          <template v-if="editing">
            <div class="dc-item-row">
              <input v-model="item.file_path" class="dc-input" :placeholder="t('diagnosis.file_path_placeholder')" />
              <input v-model.number="item.start_line" class="dc-input dc-input-num" type="number" min="1" :placeholder="t('diagnosis.start_line')" />
              <input v-model.number="item.end_line" class="dc-input dc-input-num" type="number" min="1" :placeholder="t('diagnosis.end_line')" />
              <button class="dc-btn-icon dc-btn-danger" type="button" :title="t('common.delete')" @click="removeCodeContext(index)">
                <Trash2 class="dc-btn-icon-svg" />
              </button>
            </div>
            <input v-model="item.note" class="dc-input" :placeholder="t('diagnosis.note_placeholder')" />
            <textarea v-model="item.snippet" class="dc-textarea dc-snippet" rows="3" :placeholder="t('diagnosis.snippet_placeholder')" />
          </template>
          <template v-else>
            <div class="dc-item-title">
              <Code2 class="dc-item-icon" />
              <span>{{ lineLabel(item) }}</span>
              <span v-if="item.note" class="dc-item-note">{{ item.note }}</span>
            </div>
            <pre v-if="item.snippet" class="dc-snippet">{{ item.snippet }}</pre>
          </template>
        </div>
        <button v-if="editing" class="dc-btn-add" type="button" @click="addCodeContext">
          <Plus class="dc-btn-icon-svg" />
          {{ t('diagnosis.add_code_context') }}
        </button>
      </div>

      <!-- 修复方案 / 修复代码 -->
      <div v-if="local.fix_suggestion || local.fix_code || editing" class="dc-section">
        <div class="dc-section-head">
          <Code2 class="dc-section-icon" />
          <span>{{ t('diagnosis.fix_plan') }}</span>
        </div>
        <template v-if="editing">
          <label class="dc-label">{{ t('diagnosis.fix_suggestion') }}</label>
          <textarea v-model="local.fix_suggestion" class="dc-textarea" rows="2" :placeholder="t('diagnosis.fix_suggestion_placeholder')" />
          <label class="dc-label">{{ t('diagnosis.fix_code') }}</label>
          <textarea v-model="local.fix_code" class="dc-textarea dc-code" rows="5" :placeholder="t('diagnosis.fix_code_placeholder')" />
        </template>
        <template v-else>
          <p v-if="local.fix_suggestion" class="dc-text">{{ local.fix_suggestion }}</p>
          <div v-if="local.fix_code" class="dc-code-block">
            <button class="dc-btn-icon" type="button" :title="t('diagnosis.copy_code')" @click="copyFixCode">
              <Check v-if="copied" class="dc-btn-icon-svg" />
              <Copy v-else class="dc-btn-icon-svg" />
            </button>
            <pre class="dc-code">{{ local.fix_code }}</pre>
          </div>
        </template>
      </div>

      <!-- 相似案例 -->
      <div v-if="local.similar_cases.length || editing" class="dc-section">
        <div class="dc-section-head">
          <History class="dc-section-icon" />
          <span>{{ t('diagnosis.similar_cases') }}</span>
        </div>
        <div v-for="(item, index) in local.similar_cases" :key="index" class="dc-item">
          <template v-if="editing">
            <div class="dc-item-row">
              <input v-model="item.title" class="dc-input" :placeholder="t('diagnosis.case_title_placeholder')" />
              <input v-model="item.similarity" class="dc-input dc-input-sm" :placeholder="t('diagnosis.similarity')" />
              <button class="dc-btn-icon dc-btn-danger" type="button" :title="t('common.delete')" @click="removeSimilarCase(index)">
                <Trash2 class="dc-btn-icon-svg" />
              </button>
            </div>
            <input v-model="item.reference" class="dc-input" :placeholder="t('diagnosis.reference_placeholder')" />
            <textarea v-model="item.summary" class="dc-textarea" rows="2" :placeholder="t('diagnosis.case_summary_placeholder')" />
          </template>
          <template v-else>
            <div class="dc-item-title">
              <History class="dc-item-icon" />
              <span>{{ item.title }}</span>
              <span v-if="item.similarity" class="dc-item-note">{{ item.similarity }}</span>
            </div>
            <p v-if="item.summary" class="dc-text dc-item-text">{{ item.summary }}</p>
            <p v-if="item.reference" class="dc-text dc-item-ref">{{ item.reference }}</p>
          </template>
        </div>
        <button v-if="editing" class="dc-btn-add" type="button" @click="addSimilarCase">
          <Plus class="dc-btn-icon-svg" />
          {{ t('diagnosis.add_similar_case') }}
        </button>
      </div>

      <!-- 调用链路 -->
      <div v-if="local.call_chain.length || editing" class="dc-section">
        <div class="dc-section-head">
          <GitBranch class="dc-section-icon" />
          <span>{{ t('diagnosis.call_chain') }}</span>
        </div>
        <div v-for="(node, index) in sortedCallChain" :key="index" class="dc-item dc-chain-node">
          <template v-if="editing">
            <div class="dc-item-row">
              <input v-model.number="node.seq" class="dc-input dc-input-num" type="number" min="0" :placeholder="t('diagnosis.seq')" />
              <input v-model="node.module" class="dc-input" :placeholder="t('diagnosis.module_placeholder')" />
              <input v-model="node.function" class="dc-input" :placeholder="t('diagnosis.function_placeholder')" />
              <button class="dc-btn-icon dc-btn-danger" type="button" :title="t('common.delete')" @click="removeCallChain(index)">
                <Trash2 class="dc-btn-icon-svg" />
              </button>
            </div>
            <input v-model="node.file_path" class="dc-input" :placeholder="t('diagnosis.file_path_placeholder')" />
            <input v-model="node.description" class="dc-input" :placeholder="t('diagnosis.node_description_placeholder')" />
          </template>
          <template v-else>
            <span class="dc-chain-seq">{{ node.seq ?? index + 1 }}</span>
            <div class="dc-chain-body">
              <div class="dc-item-title">
                <span>{{ chainLabel(node) }}</span>
                <span v-if="node.file_path" class="dc-item-note">{{ node.file_path }}</span>
              </div>
              <p v-if="node.description" class="dc-text dc-item-text">{{ node.description }}</p>
            </div>
          </template>
        </div>
        <button v-if="editing" class="dc-btn-add" type="button" @click="addCallChain">
          <Plus class="dc-btn-icon-svg" />
          {{ t('diagnosis.add_call_chain') }}
        </button>
      </div>

      <!-- 置信度 -->
      <div class="dc-section dc-confidence">
        <div class="dc-section-head">
          <span>{{ t('diagnosis.confidence') }}</span>
          <span class="dc-confidence-value">{{ confidenceLabel }}</span>
        </div>
        <el-slider v-if="editing" v-model="local.confidence" :min="0" :max="100" :step="5" />
        <el-slider v-else v-model="local.confidence" :min="0" :max="100" :step="5" disabled />
      </div>
    </div>

    <div v-if="!adopted" class="dc-actions">
      <template v-if="editing">
        <button class="dc-btn dc-btn-secondary" type="button" :disabled="saving" @click="cancelEdit">
          <X class="dc-btn-icon-svg" />
          {{ t('diagnosis.cancel_edit') }}
        </button>
        <button class="dc-btn dc-btn-primary" type="button" :disabled="saving || summarizing" @click="handleSave">
          <Loader2 v-if="saving" class="dc-btn-icon-svg dc-spin" />
          <Save v-else class="dc-btn-icon-svg" />
          {{ t('diagnosis.save_draft') }}
        </button>
      </template>
      <template v-else>
        <button v-if="canEdit && !summarizing" class="dc-btn dc-btn-secondary" type="button" @click="startEdit">
          <Pencil class="dc-btn-icon-svg" />
          {{ t('diagnosis.edit') }}
        </button>
        <button v-if="hasContent" class="dc-btn dc-btn-secondary" type="button" @click="emit('export', local)">
          <Download class="dc-btn-icon-svg" />
          {{ t('diagnosis.export_markdown') }}
        </button>
        <button v-if="canEdit" class="dc-btn dc-btn-secondary" type="button" :disabled="saving || summarizing" @click="emit('regenerate')">
          <Loader2 v-if="summarizing" class="dc-btn-icon-svg dc-spin" />
          <RefreshCw v-else class="dc-btn-icon-svg" />
          {{ t('diagnosis.regenerate') }}
        </button>
        <button class="dc-btn dc-btn-primary" type="button" :disabled="saving || caseCreating || summarizing" @click="emit('confirm')">
          <Loader2 v-if="caseCreating" class="dc-btn-icon-svg dc-spin" />
          <CheckCircle2 v-else class="dc-btn-icon-svg" />
          {{ t('diagnosis.confirm_create_case') }}
        </button>
      </template>
    </div>
    <div v-if="adopted && hasContent" class="dc-actions">
      <button class="dc-btn dc-btn-secondary" type="button" @click="emit('export', local)">
        <Download class="dc-btn-icon-svg" />
        {{ t('diagnosis.export_markdown') }}
      </button>
      <button v-if="caseLink" class="dc-btn dc-btn-link" type="button" @click="emit('openCase', caseLink)">
        <ExternalLink class="dc-btn-icon-svg" />
        {{ t('diagnosis.view_case') }}
      </button>
    </div>
    <div v-if="caseLink && !resultConfirmed && !hasContent" class="dc-actions">
      <button class="dc-btn dc-btn-link" type="button" @click="emit('openCase', caseLink)">
        <ExternalLink class="dc-btn-icon-svg" />
        {{ t('diagnosis.view_case') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
/* 背景淡黄；其余元素独立配色（靛蓝强调 / 石板文字 / 深色代码块） */
.diagnosis-card {
  width: 100%;
  max-width: 640px;
  min-width: 0;
  box-sizing: border-box;
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: var(--radius-lg, 12px);
  background: #fffbeb;
  padding: 14px 16px;
  box-shadow: 0 10px 24px rgba(120, 53, 15, 0.08);
}

.dc-header-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.dc-icon {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  color: #1d4ed8;
}

.dc-title {
  font-weight: 700;
  font-size: 0.95rem;
  color: #1e3a8a;
}

.dc-pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 650;
  line-height: 1.5;
}

.dc-pill-icon {
  width: 11px;
  height: 11px;
}

.dc-pill-ai { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; }
.dc-pill-confirmed { color: #15803d; background: #dcfce7; border: 1px solid #86efac; }
.dc-pill-draft { color: #9a3412; background: #ffedd5; border: 1px solid #fdba74; }

.dc-empty {
  padding: 10px 0 2px;
  font-size: 0.82rem;
  color: #78716c;
}

.dc-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 10px;
}

.dc-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dc-section-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.78rem;
  font-weight: 700;
  color: #334155;
}

.dc-section-icon {
  width: 14px;
  height: 14px;
  color: #64748b;
}

.dc-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #334155;
}

.dc-text {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.6;
  color: #1f2937;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.dc-summary {
  font-weight: 600;
  color: #111827;
}

.dc-root-cause {
  padding: 8px 10px;
  border-left: 3px solid #2563eb;
  background: #eff6ff;
  border-radius: 4px;
}

.dc-textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 0.82rem;
  line-height: 1.5;
  color: #1f2937;
  background: #ffffff;
  font-family: inherit;
}

.dc-textarea:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
}

.dc-input {
  box-sizing: border-box;
  min-width: 0;
  flex: 1;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 6px 9px;
  font-size: 0.8rem;
  color: #1f2937;
  background: #ffffff;
  font-family: inherit;
}

.dc-input:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
}

.dc-input-num { flex: 0 0 76px; }
.dc-input-sm { flex: 0 0 90px; }

.dc-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 8px 10px;
  border: 1px solid #e8e6e3;
  border-radius: 8px;
  background: #ffffff;
}

.dc-item-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dc-item-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  font-weight: 650;
  color: #111827;
  flex-wrap: wrap;
  min-width: 0;
}

.dc-item-icon {
  width: 13px;
  height: 13px;
  color: #2563eb;
  flex-shrink: 0;
}

.dc-item-note {
  min-width: 0;
  font-size: 0.7rem;
  font-weight: 500;
  color: #64748b;
  overflow-wrap: anywhere;
}

.dc-item-title > span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.dc-item-text { font-size: 0.78rem; color: #334155; }
.dc-item-ref { font-size: 0.75rem; color: #2563eb; }

/* 代码类内容：深色主题 */
.dc-snippet,
.dc-code {
  margin: 0;
  border-radius: 6px;
  border: 1px solid #1e293b;
  background: #0f172a;
  color: #e2e8f0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.75rem;
  line-height: 1.55;
  overflow: auto;
}

.dc-snippet {
  padding: 8px 10px;
  white-space: pre-wrap;
  word-break: break-all;
}

.dc-code {
  max-width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  white-space: pre;
}

.dc-code-block {
  position: relative;
  min-width: 0;
  max-width: 100%;
}

.dc-code-block .dc-btn-icon {
  position: absolute;
  top: 6px;
  right: 6px;
  color: #94a3b8;
}

.dc-code-block .dc-btn-icon:hover {
  background: #1e293b;
  color: #e2e8f0;
}

.dc-btn-add {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  align-self: flex-start;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: transparent;
  color: #475569;
  font-size: 0.75rem;
  padding: 4px 10px;
  cursor: pointer;
}

.dc-btn-add:hover {
  border-color: #2563eb;
  color: #2563eb;
  background: #eff6ff;
}

.dc-btn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
}

.dc-btn-icon:hover { background: #f1f5f9; color: #334155; }

.dc-btn-danger:hover { background: #fef2f2; color: #b91c1c; }

.dc-btn-icon-svg {
  width: 14px;
  height: 14px;
}

.dc-chain-node {
  flex-direction: row;
  align-items: flex-start;
  gap: 8px;
}

.dc-chain-seq {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 0.7rem;
  font-weight: 700;
}

.dc-chain-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1;
}

.dc-chain-body .dc-item-row {
  margin-top: 2px;
}

.dc-confidence {
  border: 1px solid #e8e6e3;
  border-radius: 8px;
  padding: 6px 10px 2px;
  background: #ffffff;
}

.dc-confidence-value {
  margin-left: auto;
  color: #2563eb;
  font-weight: 700;
}

.dc-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #fde68a;
}

.dc-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 0.78rem;
  font-weight: 650;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s ease;
}

.dc-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.dc-btn-primary {
  background: #2563eb;
  color: #ffffff;
}

.dc-btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
  transform: translateY(-1px);
}

.dc-btn-secondary {
  background: #ffffff;
  border-color: #e2e8f0;
  color: #334155;
}

.dc-btn-secondary:hover:not(:disabled) {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.dc-btn-link {
  background: transparent;
  color: #2563eb;
  padding-left: 2px;
  padding-right: 2px;
}

.dc-btn-link:hover {
  text-decoration: underline;
}

.dc-spin {
  animation: dc-spin 1s linear infinite;
}

@keyframes dc-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
