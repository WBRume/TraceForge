<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import {
  ArrowLeft,
  Workflow,
  AlertCircle,
  Loader2,
  Pencil,
  Save,
  X,
  Plus,
  Trash2,
  Copy,
  Check,
  FileText,
  Boxes,
  Layers,
  Link as LinkIcon,
} from 'lucide-vue-next'
import api from '@/utils/api'

const route = useRoute()
const router = useRouter()

const wsId = computed(() => String(route.params.wsId || ''))
const playbookId = computed(() => String(route.params.playbookId || ''))

const document = ref<any>(null)
const canEdit = ref(false)
const loading = ref(false)
const saving = ref(false)
const editing = ref(false)
const error = ref('')
const symptomsText = ref('')
const copied = ref(false)

let generation = 0
let backupDocument: any = null

const ERROR_MESSAGES: Record<string, string> = {
  SHELL_OR_BUNDLE_INVALID: '规程必须声明 execution.bundle（可信执行包地址）且 execution.shell 必须为 false',
  INVALID_YAML: 'YAML 语法格式错误，请检查缩进与标记',
  INVALID_SPEC: '规程文档内容为空或非有效映射结构',
  INVALID_SPEC_VERSION: '规程版本不匹配（必须为 traceforge.dev/troubleshooting/v1 / TroubleshootingPlaybook）',
  ALL_GATES_REQUIRED: '规程必须声明 completion.requireAllStageGates: true',
  INVALID_STAGES: '阶段 stages 必须定义 1~32 个有效阶段',
  INVALID_DAG: '阶段流转 DAG 存在环路或未以 completed 终结',
  UNREACHABLE_STAGE: '存在不可达的规程阶段',
  PATCH_WITHOUT_REPRODUCTION: '补丁阶段（PATCH）必须在复现阶段（REPRODUCE）成功后才能进入',
  INVALID_VERIFICATION: '阶段验证配置不完整（必须包含 command, expectExitCodes, artifacts, passWhen）',
  INVALID_PERMISSION_TIER: '阶段权限级别不合法（PATCH 必须为 WORKSPACE_WRITE，其余阶段必须为 READONLY）',
  INVALID_COMMAND: '命令配置不完整（必须包含 argv, cwd, timeoutSeconds, effect）',
  CONCURRENT_WRITE: '存在并发写入冲突，请重试',
}

const formatError = (e: any): string => {
  const resp = e.response?.data
  const code = resp?.detail?.code || resp?.detail || resp?.message || e.message || '操作失败'
  return ERROR_MESSAGES[code] || String(code)
}

const loadDetail = async () => {
  if (!wsId.value || !playbookId.value) return
  const current = ++generation
  loading.value = true
  error.value = ''
  editing.value = false

  try {
    const { data } = await api.get(`/workspaces/${wsId.value}/cases/playbooks/${playbookId.value}`)
    if (current !== generation) return
    document.value = data.document
    canEdit.value = Boolean(data.can_edit)
    symptomsText.value = (data.document?.match?.symptoms || []).join('\n')
  } catch (e: any) {
    if (current === generation) {
      error.value = formatError(e) || '规程加载失败'
    }
  } finally {
    if (current === generation) {
      loading.value = false
    }
  }
}

watch([wsId, playbookId], () => {
  void loadDetail()
}, { immediate: true })

const goBackToList = () => {
  const isKnowledge = route.path.startsWith('/knowledge')
  if (isKnowledge) {
    router.push({
      path: wsId.value ? `/knowledge/cases/${wsId.value}` : '/knowledge/cases',
      query: { tab: 'playbooks' },
    })
    return
  }
  router.push({
    name: 'workspaceCases',
    params: { wsId: wsId.value },
    query: { tab: 'playbooks' },
  })
}

const startEdit = () => {
  backupDocument = JSON.parse(JSON.stringify(document.value))
  editing.value = true
}

const cancelEdit = () => {
  if (backupDocument) {
    document.value = JSON.parse(JSON.stringify(backupDocument))
    symptomsText.value = (backupDocument?.match?.symptoms || []).join('\n')
  }
  editing.value = false
  error.value = ''
}

const addStep = () => {
  if (!document.value.stages) {
    document.value.stages = []
  }
  const randomSuffix = crypto.randomUUID().replaceAll('-', '')
  document.value.stages.push({
    id: `step_${randomSuffix}`,
    objective: '',
  })
}

const removeStep = (index: number | string) => {
  document.value.stages.splice(Number(index), 1)
}

const save = async () => {
  if (!document.value?.metadata?.title?.trim()) {
    error.value = '规程标题不能为空'
    return
  }
  saving.value = true
  error.value = ''

  try {
    const payloadDoc = JSON.parse(JSON.stringify(document.value))
    payloadDoc.match = {
      ...payloadDoc.match,
      symptoms: symptomsText.value.split('\n').map((v) => v.trim()).filter(Boolean),
    }
    await api.put(`/workspaces/${wsId.value}/cases/playbooks/${playbookId.value}`, {
      document: payloadDoc,
    })
    await loadDetail()
  } catch (e: any) {
    error.value = formatError(e)
  } finally {
    saving.value = false
  }
}

const copyId = () => {
  const text = document.value?.metadata?.id || playbookId.value
  navigator.clipboard.writeText(text)
  copied.value = true
  setTimeout(() => {
    copied.value = false
  }, 2000)
}
</script>

<template>
  <div class="playbook-detail-page">
    <!-- 顶部加载状态 -->
    <div v-if="loading && !document" class="pd-loading">
      <Loader2 class="w-8 h-8 spin" />
      <span>加载故障诊断规程详情...</span>
    </div>

    <!-- 加载失败或未找到 -->
    <div v-else-if="!document && error" class="pd-not-found">
      <AlertCircle :size="36" class="text-rose" />
      <h3>{{ error }}</h3>
      <button class="btn-secondary" @click="goBackToList">
        <ArrowLeft :size="16" /> 返回规程列表
      </button>
    </div>

    <template v-else-if="document">
      <!-- 页面顶部导航与操作栏 -->
      <div class="pd-header">
        <div class="pd-header-left">
          <div class="pd-back-row">
            <button class="btn-back" type="button" @click="goBackToList">
              <ArrowLeft :size="16" /> 返回规程列表
            </button>
          </div>

          <div class="pd-title-row">
            <h2 v-if="!editing" class="pd-title">{{ document.metadata.title }}</h2>
            <input
              v-else
              v-model="document.metadata.title"
              type="text"
              class="pd-title-input"
              placeholder="请输入规程标题"
            />

            <div class="pd-badges">
              <span class="badge-version">v{{ document.metadata.version }}</span>
              <span
                v-if="document.execution?.mode"
                class="badge-mode"
                :class="document.execution.mode.toLowerCase()"
              >
                {{ document.execution.mode === 'ANALYSIS_GUIDE' ? '排查指引' : '物理验证' }}
              </span>
              <button
                class="badge-id-btn"
                :title="copied ? '已复制标识' : '点击复制规程标识'"
                @click="copyId"
              >
                <span>ID: {{ playbookId.slice(0, 10) }}...</span>
                <Check v-if="copied" :size="12" class="text-emerald" />
                <Copy v-else :size="12" />
              </button>
            </div>
          </div>
        </div>

        <div class="pd-actions">
          <template v-if="!editing">
            <button
              v-if="canEdit"
              class="btn-primary flex items-center gap-2"
              @click="startEdit"
            >
              <Pencil :size="15" />
              <span>编辑规程</span>
            </button>
          </template>
          <template v-else>
            <button class="btn-secondary flex items-center gap-2" :disabled="saving" @click="cancelEdit">
              <X :size="15" />
              <span>取消</span>
            </button>
            <button
              class="btn-primary flex items-center gap-2"
              :disabled="saving || !document.metadata.title?.trim()"
              @click="save"
            >
              <Loader2 v-if="saving" :size="15" class="spin" />
              <Save v-else :size="15" />
              <span>{{ saving ? '保存中...' : '保存新版本' }}</span>
            </button>
          </template>
        </div>
      </div>

      <!-- 错误横幅提示 -->
      <div v-if="error" class="pd-alert" role="alert">
        <AlertCircle :size="16" class="alert-icon" />
        <span>{{ error }}</span>
        <button class="alert-close" @click="error = ''"><X :size="14" /></button>
      </div>

      <!-- 核心内容网格 -->
      <div class="pd-grid">
        <!-- 主内容区 -->
        <div class="pd-main">
          <!-- 适用症状卡片 -->
          <div class="pd-card">
            <div class="pd-card-header">
              <div class="pd-card-title">
                <Workflow :size="18" class="text-sky" />
                <span>适用症状 (Symptoms)</span>
              </div>
            </div>
            <div class="pd-card-body">
              <div v-if="!editing" class="symptom-tags">
                <span
                  v-for="symptom in document.match?.symptoms || []"
                  :key="symptom"
                  class="symptom-pill"
                >
                  {{ symptom }}
                </span>
                <span v-if="!document.match?.symptoms?.length" class="text-muted">暂无适用症状</span>
              </div>
              <div v-else class="edit-symptoms-wrap">
                <p class="edit-tip">每行输入一个症状描述：</p>
                <textarea
                  v-model="symptomsText"
                  class="form-textarea"
                  rows="4"
                  placeholder="例如：支付重复入账&#10;订单状态未同步"
                ></textarea>
              </div>
            </div>
          </div>

          <!-- 摘要说明卡片 -->
          <div v-if="document.context?.summary || editing" class="pd-card">
            <div class="pd-card-header">
              <div class="pd-card-title">
                <FileText :size="18" class="text-sky" />
                <span>规程摘要 (Summary)</span>
              </div>
            </div>
            <div class="pd-card-body">
              <p v-if="!editing" class="summary-text">{{ document.context?.summary || '暂无摘要说明' }}</p>
              <textarea
                v-else
                v-model="document.context.summary"
                class="form-textarea"
                rows="4"
                placeholder="请输入规程背景与排查目标摘要..."
              ></textarea>
            </div>
          </div>

          <!-- 诊断与执行阶段步骤卡片 -->
          <div class="pd-card">
            <div class="pd-card-header flex justify-between items-center">
              <div class="pd-card-title">
                <Layers :size="18" class="text-sky" />
                <span>诊断与排查步骤 (Stages)</span>
                <span class="pd-count-badge">{{ document.stages?.length || 0 }}</span>
              </div>
              <button
                v-if="editing && document.execution?.mode === 'ANALYSIS_GUIDE'"
                type="button"
                class="btn-secondary btn-sm flex items-center gap-1.5"
                @click="addStep"
              >
                <Plus :size="14" />
                <span>添加步骤</span>
              </button>
            </div>

            <div class="pd-card-body">
              <div v-if="!document.stages?.length" class="text-muted">
                暂无排查步骤
              </div>
              <div v-else class="steps-list">
                <div
                  v-for="(step, index) in document.stages"
                  :key="step.id"
                  class="step-item"
                >
                  <div class="step-num">{{ Number(index) + 1 }}</div>
                  <div class="step-content">
                    <div class="step-header">
                      <span class="step-id">ID: {{ step.id }}</span>
                      <button
                        v-if="editing && document.execution?.mode === 'ANALYSIS_GUIDE'"
                        type="button"
                        class="btn-icon-danger"
                        aria-label="删除步骤"
                        title="删除该步骤"
                        @click="removeStep(index)"
                      >
                        <Trash2 :size="15" />
                      </button>
                    </div>

                    <div class="step-body">
                      <p v-if="!editing" class="step-objective">{{ step.objective || '无明确目标' }}</p>
                      <textarea
                        v-else
                        v-model="step.objective"
                        class="form-textarea"
                        rows="3"
                        placeholder="请输入该阶段排查或验证的具体目标..."
                      ></textarea>

                      <!-- 验证规则展开 -->
                      <details v-if="step.verification" class="verification-details">
                        <summary>验证配置详情 (Verification Rule)</summary>
                        <pre class="json-code">{{ JSON.stringify(step.verification, null, 2) }}</pre>
                      </details>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 侧边栏/关联信息 -->
        <div class="pd-side">
          <!-- 来源案例 -->
          <div class="pd-card">
            <div class="pd-card-header">
              <div class="pd-card-title">
                <LinkIcon :size="16" class="text-sky" />
                <span>来源案例 (Source Cases)</span>
              </div>
            </div>
            <div class="pd-card-body">
              <div v-if="document.metadata?.sourceCaseRefs?.length" class="source-case-list">
                <RouterLink
                  v-for="id in document.metadata.sourceCaseRefs"
                  :key="id"
                  :to="
                    route.path.startsWith('/knowledge')
                      ? { name: 'knowledgeCaseDetail', params: { wsId: wsId, caseId: id } }
                      : { name: 'workspaceCaseDetail', params: { wsId: wsId, caseId: id } }
                  "
                  class="source-case-item"
                >
                  <FileText :size="14" />
                  <span class="source-title">
                    {{ document.context?.source_cases?.find((c: any) => c.id === id)?.title || `#${id.slice(0, 8)}` }}
                  </span>
                </RouterLink>
              </div>
              <div v-else class="text-muted">无关联来源案例</div>
            </div>
          </div>

          <!-- 调用链节点 -->
          <div v-if="document.context?.call_chain?.length" class="pd-card">
            <div class="pd-card-header">
              <div class="pd-card-title">
                <Boxes :size="16" class="text-sky" />
                <span>关联调用链 (Call Chain)</span>
              </div>
            </div>
            <div class="pd-card-body">
              <details class="chain-details">
                <summary>查看完整链路配置 ({{ document.context.call_chain.length }} 节点)</summary>
                <pre class="json-code">{{ JSON.stringify(document.context.call_chain, null, 2) }}</pre>
              </details>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.playbook-detail-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
  padding-bottom: 40px;
}

.pd-loading,
.pd-not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  text-align: center;
  gap: 14px;
  color: #64748b;
}

.pd-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 18px 24px;
}

.pd-header-left {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.pd-back-row {
  display: flex;
  align-items: center;
}

.btn-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 0.85rem;
  cursor: pointer;
  padding: 0;
  font-weight: 500;
  transition: color 0.15s;
}

.btn-back:hover {
  color: #0284c7;
}

.pd-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.pd-title {
  margin: 0;
  font-size: 1.35rem;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.3;
}

.pd-title-input {
  flex: 1;
  min-width: 260px;
  max-width: 540px;
  font-size: 1.15rem;
  font-weight: 600;
  padding: 6px 12px;
  border: 1px solid #0284c7;
  border-radius: 8px;
  outline: none;
  background: #ffffff;
  color: #0f172a;
}

.pd-badges {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.badge-version {
  display: inline-flex;
  align-items: center;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
}

.badge-mode {
  font-size: 0.72rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid transparent;
}

.badge-mode.analysis_guide {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #bfdbfe;
}

.badge-mode.physical_verification {
  background: #ecfdf5;
  color: #047857;
  border-color: #a7f3d0;
}

.badge-id-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px dashed #cbd5e1;
  background: #f8fafc;
  color: #64748b;
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.badge-id-btn:hover {
  border-color: #0284c7;
  color: #0284c7;
}

.pd-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pd-alert {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 10px;
  color: #dc2626;
  font-size: 0.85rem;
}

.alert-close {
  margin-left: auto;
  border: none;
  background: transparent;
  color: #dc2626;
  cursor: pointer;
  padding: 2px;
}

/* 栅格布局 */
.pd-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 20px;
  align-items: start;
}

.pd-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pd-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pd-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.pd-card-header {
  padding: 14px 20px;
  border-bottom: 1px solid #f1f5f9;
  background: #fafafa;
}

.pd-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.92rem;
  font-weight: 700;
  color: #1e293b;
}

.pd-count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #e0f2fe;
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 1px 7px;
}

.pd-card-body {
  padding: 18px 20px;
}

.symptom-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.symptom-pill {
  font-size: 0.82rem;
  padding: 3px 10px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  color: #0369a1;
  border-radius: 6px;
  font-weight: 500;
}

.edit-symptoms-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.edit-tip {
  font-size: 0.78rem;
  color: #64748b;
  margin: 0;
}

.form-textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 10px;
  color: #334155;
  font: inherit;
  font-size: 0.86rem;
  line-height: 1.5;
  outline: none;
  resize: vertical;
  transition: border-color 0.15s;
}

.form-textarea:focus {
  border-color: #0284c7;
}

.summary-text {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
}

/* 步骤列表 */
.steps-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.step-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.step-num {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #0284c7;
  color: #ffffff;
  font-size: 0.75rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.step-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.step-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.step-id {
  font-size: 0.75rem;
  color: #64748b;
  font-family: monospace;
}

.btn-icon-danger {
  border: none;
  background: transparent;
  color: #ef4444;
  cursor: pointer;
  padding: 3px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.btn-icon-danger:hover {
  background: #fee2e2;
}

.step-objective {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.5;
  color: #1e293b;
  white-space: pre-wrap;
}

.verification-details {
  margin-top: 6px;
  font-size: 0.8rem;
  color: #64748b;
}

.verification-details summary {
  cursor: pointer;
  color: #0284c7;
  font-weight: 500;
}

.json-code {
  margin-top: 6px;
  background: #0f172a;
  color: #e2e8f0;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 0.75rem;
  overflow-x: auto;
  font-family: monospace;
}

/* 来源案例列表 */
.source-case-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.source-case-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  color: #0284c7;
  text-decoration: none;
  font-size: 0.82rem;
  font-weight: 500;
  transition: all 0.15s;
}

.source-case-item:hover {
  background: #f0f9ff;
  border-color: #bae6fd;
}

.source-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chain-details summary {
  cursor: pointer;
  color: #0284c7;
  font-size: 0.82rem;
  font-weight: 500;
}

.text-sky { color: #0284c7; }
.text-rose { color: #f43f5e; }
.text-emerald { color: #10b981; }
.text-muted { color: #94a3b8; font-size: 0.82rem; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

@media (max-width: 960px) {
  .pd-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
