<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Search,
  Plus,
  CheckCircle2,
  AlertCircle,
  ShieldCheck,
  Clock,
  Activity,
  X,
  Loader2,
  Sparkles,
  Copy,
  Check,
  Workflow,
} from 'lucide-vue-next'
import api from '@/utils/api'
import type { PlaybookSpec } from '@/types/diagnosisPlaybook'
import { DEMO_PLAYBOOK_YAML } from './demoPlaybook'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import DeleteActionButton from '@/components/DeleteActionButton.vue'

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

const props = defineProps<{ workspaceId?: string }>()

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const items = shallowRef<PlaybookSpec[]>([])
const loading = ref(false)
const error = ref('')
const search = ref('')
const page = ref(1)
const pageSize = 12
const total = ref(0)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const applySearch = () => { page.value = 1; void load() }
const changePage = (next: number) => { page.value = next; void load() }

const source = ref('')
const showImportModal = ref(false)
const busy = ref(false)
const copiedId = ref('')

const showDeleteConfirm = ref(false)
const playbookToDelete = ref<PlaybookSpec | null>(null)
const deleting = ref(false)

const openDeleteConfirm = (item: PlaybookSpec) => {
  playbookToDelete.value = item
  showDeleteConfirm.value = true
}

const confirmDeletePlaybook = async () => {
  if (!playbookToDelete.value) return
  deleting.value = true
  try {
    const wsId = String(playbookToDelete.value.workspace_id || props.workspaceId || route.params.wsId || '').trim()
    const endpoint = wsId
      ? `/workspaces/${wsId}/cases/playbooks/${playbookToDelete.value.id}`
      : `/cases/playbooks/${playbookToDelete.value.id}`
    await api.delete(endpoint)
    showDeleteConfirm.value = false
    playbookToDelete.value = null
    await load()
  } catch (e: any) {
    error.value = formatError(e) || '删除规程失败'
  } finally {
    deleting.value = false
  }
}

const goToDetail = (item: PlaybookSpec) => {
  const wsId = String(item.workspace_id || props.workspaceId || route.params.wsId || '')
  if (!wsId) return
  const isKnowledge = route.path.startsWith('/knowledge')
  router.push(
    isKnowledge
      ? { name: 'knowledgePlaybookDetail', params: { wsId, playbookId: item.id } }
      : { name: 'workspacePlaybookDetail', params: { wsId, playbookId: item.id } },
  )
}

let generation = 0

const load = async () => {
  const captured = ++generation
  loading.value = true
  error.value = ''
  try {
    const wsId = String(props.workspaceId || '').trim()
    const endpoint = wsId ? `/workspaces/${wsId}/cases/playbooks` : '/cases/playbooks'
    const { data } = await api.get(endpoint, { params: { page: page.value, page_size: pageSize, keyword: search.value.trim() } })
    if (captured === generation) {
      items.value = Array.isArray(data.items) ? data.items : []
      total.value = Number(data.total ?? items.value.length)
    }
  } catch (e: any) {
    if (captured === generation) {
      error.value = formatError(e)
    }
  } finally {
    if (captured === generation) {
      loading.value = false
    }
  }
}

watch(() => props.workspaceId, () => {
  error.value = ''
  page.value = 1
  void load()
}, { immediate: true })

const copySpecKey = (item: PlaybookSpec) => {
  navigator.clipboard.writeText(item.spec_key || item.id)
  copiedId.value = item.id
  setTimeout(() => {
    if (copiedId.value === item.id) copiedId.value = ''
  }, 2000)
}

const importSpec = async () => {
  if (!source.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    const wsId = String(props.workspaceId || '').trim()
    const endpoint = wsId ? `/workspaces/${wsId}/cases/playbooks` : '/cases/playbooks'
    const payload = wsId ? { document: source.value } : { document: source.value, workspace_id: wsId }
    await api.post(endpoint, payload)
    source.value = ''
    showImportModal.value = false
    await load()
  } catch (e: any) {
    error.value = formatError(e)
  } finally {
    busy.value = false
  }
}

const loadDemoYaml = () => {
  source.value = DEMO_PLAYBOOK_YAML.trim()
}
</script>

<template>
  <section class="playbook-library">
    <!-- 顶部工具条：搜索框对齐案例库风格且在右侧 -->
    <div class="pl-toolbar">
      <div class="pl-actions">
        <div class="search-box">
          <Search :size="16" class="search-icon" />
          <input
            v-model="search"
            type="text"
            class="search-input"
            placeholder="搜索规程标题、标识、适用症状..."
            @keyup.enter="applySearch"
          />
          <button class="btn-primary" :disabled="loading" @click="applySearch">
            {{ t('case_center.search') }}
          </button>
        </div>

        <button class="btn-primary flex items-center gap-2" @click="showImportModal = true">
          <Plus :size="16" />
          <span>导入规程 YAML</span>
        </button>
      </div>
    </div>

    <!-- 错误横幅 -->
    <div v-if="error" class="pl-alert" role="alert">
      <AlertCircle :size="16" class="alert-icon" />
      <span>{{ error }}</span>
      <button class="alert-close" @click="error = ''"><X :size="14" /></button>
    </div>

    <!-- 加载中 -->
    <div v-if="loading && !items.length" class="pl-loading">
      <Loader2 class="w-6 h-6 spin" />
      <span>加载故障诊断规程库...</span>
    </div>

    <!-- 空状态 -->
    <div v-else-if="!items.length" class="pl-empty">
      <div class="empty-icon-wrap">
        <Workflow :size="40" class="empty-icon" />
      </div>
      <h3>{{ search ? '未找到匹配的诊断规程' : '暂无故障诊断规程' }}</h3>
      <p>
        {{
          search
            ? '请尝试更换搜索关键字'
            : '在案例库列表多选案例晋升诊断规程，复用调用链和排查经验；新建问题定位任务时可推荐并选择。也支持导入已有规程。'
        }}
      </p>
      <button v-if="!search" class="btn-primary" @click="showImportModal = true">
        <Plus :size="16" />
        <span>导入第一份诊断规程</span>
      </button>
    </div>

    <!-- 规程卡片网格 -->
    <div v-else class="playbook-grid">
      <div v-for="item in items" :key="item.id" class="playbook-card">
        <!-- 卡片头部 -->
        <div class="card-header">
          <div class="title-wrap">
            <h3 class="card-title"><button class="pl-title-link" @click="goToDetail(item)">{{ item.title }}</button></h3>
            <span class="version-badge">v{{ item.version }}</span>
          </div>
          <span
            class="status-pill"
            :class="item.validation_state === 'VERIFIED_ON_ENVIRONMENT' ? 'verified' : 'unverified'"
          >
            <ShieldCheck v-if="item.validation_state === 'VERIFIED_ON_ENVIRONMENT'" :size="13" />
            <AlertCircle v-else :size="13" />
            <span>{{ item.validation_state === 'VERIFIED_ON_ENVIRONMENT' ? '已验证' : '待演练' }}</span>
          </span>
        </div>

        <!-- 规程描述与元信息 -->
        <div class="card-body">
          <div class="meta-row">
            <span class="meta-label">适用症状</span>
            <div class="tag-cloud">
              <span
                v-for="symptom in item.match?.symptoms || []"
                :key="symptom"
                class="symptom-tag"
              >
                {{ symptom }}
              </span>
              <span v-if="!item.match?.symptoms?.length" class="text-muted">待补充</span>
            </div>
          </div>

          <div v-if="item.match?.requiredFacts && Object.keys(item.match.requiredFacts).length" class="meta-row">
            <span class="meta-label">环境依赖</span>
            <div class="fact-cloud">
              <span
                v-for="(val, key) in item.match.requiredFacts"
                :key="key"
                class="fact-pill"
              >
                {{ key }} = {{ val }}
              </span>
            </div>
          </div>

          <!-- 实测统计看板 -->
          <div v-if="item.statistics && item.statistics.run_count > 0" class="stats-box">
            <div class="stat-item">
              <Activity :size="13" class="stat-icon" />
              <span>排查 <strong>{{ item.statistics.run_count }}</strong> 次</span>
            </div>
            <div class="stat-item">
              <CheckCircle2 :size="13" class="stat-icon text-emerald" />
              <span>通过 <strong>{{ item.statistics.verified_runs }}</strong> 次</span>
            </div>
            <div v-if="item.statistics.average_verified_duration_seconds !== null" class="stat-item">
              <Clock :size="13" class="stat-icon" />
              <span>均耗 <strong>{{ Math.round(item.statistics.average_verified_duration_seconds) }}s</strong></span>
            </div>
          </div>

          <!-- 来源案例 -->
          <div v-if="item.source_case_refs?.length" class="source-cases">
            <span class="meta-label">来源案例</span>
            <div class="source-links">
              <RouterLink
                v-for="id in item.source_case_refs"
                :key="id"
                :to="{ name: 'knowledgeCaseDetail', params: { wsId: item.workspace_id || props.workspaceId, caseId: id } }"
                class="source-link"
              >
                #{{ id.slice(0, 8) }}
              </RouterLink>
            </div>
          </div>
        </div>

        <!-- 卡片底部操作 -->
        <div class="card-footer">
          <button class="btn-secondary" @click="goToDetail(item)">查看详情</button>
          <div class="card-footer-actions">
            <button class="icon-action-btn" :title="copiedId === item.id ? '已复制标识' : '复制规程标识'" @click="copySpecKey(item)">
              <Check v-if="copiedId === item.id" :size="14" class="text-emerald" />
              <Copy v-else :size="14" />
            </button>
            <DeleteActionButton
              mode="icon"
              title="删除规程"
              @click.stop="openDeleteConfirm(item)"
            />
          </div>
        </div>
      </div>
    </div>

    <nav v-if="total > 0" class="pl-pagination" aria-label="规程分页">
      <span>共 {{ total }} 条</span>
      <button class="btn-secondary" :disabled="loading || page <= 1" @click="changePage(page - 1)">上一页</button>
      <span>{{ page }} / {{ pageCount }}</span>
      <button class="btn-secondary" :disabled="loading || page >= pageCount" @click="changePage(page + 1)">下一页</button>
    </nav>

    <!-- 弹窗 2：导入规程版本 YAML -->
    <div v-if="showImportModal" class="modal-backdrop" @click.self="showImportModal = false">
      <div class="modal-content import-dialog">
        <div class="modal-header">
          <div>
            <h3>导入故障诊断规程</h3>
            <p class="modal-sub">支持标准的 TroubleshootingPlaybook (v1) YAML 规范</p>
          </div>
          <button class="modal-close" @click="showImportModal = false"><X :size="18" /></button>
        </div>

        <div class="modal-body">
          <div class="import-toolbar">
            <span class="text-muted">粘贴您的规程定义：</span>
            <button type="button" class="btn-text-action" @click="loadDemoYaml">
              <Sparkles :size="13" /> 填入 MySQL 死锁官方示例
            </button>
          </div>
          <textarea
            v-model="source"
            rows="16"
            class="form-textarea code-font import-editor"
            placeholder="请在此粘贴 TroubleshootingPlaybook 规程 YAML 内容..."
          />
        </div>

        <div class="modal-footer">
          <button class="btn-secondary" :disabled="busy" @click="showImportModal = false">取消</button>
          <button
            class="btn-primary"
            :disabled="busy || !source.trim()"
            @click="importSpec"
          >
            <Loader2 v-if="busy" class="w-4 h-4 spin" />
            <ShieldCheck v-else :size="14" />
            <span>校验并保存入库</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 弹窗 3：删除规程确认（对齐删除工作区体验） -->
    <ConfirmActionModal
      :show="showDeleteConfirm"
      title="删除诊断规程？"
      :message="`确定要删除诊断规程“${playbookToDelete?.title || ''}”吗？删除后该规程将无法再被定位任务推荐或运行。`"
      emphasis-label="规程标题"
      :emphasis-value="playbookToDelete?.title || ''"
      description="此操作无法撤销。已有的历史排查案例不会被删除。"
      cancel-text="保留规程"
      confirm-text="彻底删除"
      tone="danger"
      :loading="deleting"
      @cancel="showDeleteConfirm = false; playbookToDelete = null"
      @confirm="confirmDeletePlaybook"
    />

  </section>
</template>

<style scoped>
.pl-pagination { display: flex; align-items: center; justify-content: flex-end; gap: 12px; }
.pl-title-link { border: 0; padding: 0; color: inherit; background: none; text-align: left; font: inherit; cursor: pointer; }
.pl-title-link:hover { color: #0284c7; }

.playbook-library {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
}

/* 工具栏：靠右排布，搜索框对齐案例库 */
.pl-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.pl-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 3px 3px 3px 12px;
  background: #ffffff;
}

.search-icon {
  color: #94a3b8;
  flex-shrink: 0;
}

.search-input {
  border: none;
  outline: none;
  font-size: 0.85rem;
  width: 240px;
  background: transparent;
  font-family: inherit;
  color: #0f172a;
}

/* 警示条 */
.pl-alert {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #dc2626;
  font-size: 0.85rem;
}

.alert-icon {
  flex-shrink: 0;
}

.alert-close {
  margin-left: auto;
  border: none;
  background: transparent;
  color: #dc2626;
  cursor: pointer;
  padding: 2px;
}

/* 加载态与空状态 */
.pl-loading,
.pl-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  text-align: center;
}

.pl-loading {
  gap: 12px;
  color: #64748b;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.empty-icon-wrap {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: #f0f9ff;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
}

.empty-icon {
  color: #0284c7;
}

.pl-empty h3 {
  font-size: 1.1rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 8px;
}

.pl-empty p {
  color: #64748b;
  font-size: 0.875rem;
  max-width: 480px;
  margin: 0 0 20px;
  line-height: 1.5;
}

/* 规程卡片网格 */
.playbook-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 16px;
}

.playbook-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.playbook-card:hover {
  border-color: #38bdf8;
  box-shadow: 0 6px 16px rgba(14, 165, 233, 0.08);
  transform: translateY(-2px);
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.card-title {
  font-size: 1rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.version-badge {
  font-size: 0.75rem;
  font-weight: 600;
  color: #0284c7;
  background: #e0f2fe;
  padding: 2px 6px;
  border-radius: 6px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 9999px;
  flex-shrink: 0;
}

.status-pill.verified {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
}

.status-pill.unverified {
  background: #f8fafc;
  color: #64748b;
  border: 1px solid #e2e8f0;
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 0.85rem;
  flex: 1;
}

.meta-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.meta-label {
  font-size: 0.75rem;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.symptom-tag {
  font-size: 0.78rem;
  color: #334155;
  background: #f1f5f9;
  padding: 3px 8px;
  border-radius: 6px;
}

.fact-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.fact-pill {
  font-size: 0.75rem;
  font-family: var(--font-mono, monospace);
  color: #0369a1;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  padding: 2px 6px;
  border-radius: 4px;
}

.stats-box {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #f8fafc;
  border-radius: 8px;
  padding: 8px 12px;
  margin-top: 4px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.78rem;
  color: #64748b;
}

.stat-icon {
  color: #94a3b8;
}

.text-emerald {
  color: #10b981;
}

.source-cases {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.78rem;
}

.source-links {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.source-link {
  color: #0284c7;
  text-decoration: none;
  background: #e0f2fe;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.75rem;
}

.source-link:hover {
  text-decoration: underline;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}

.card-footer-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.start-btn {
  flex: 1;
  padding: 7px 12px;
  font-size: 0.85rem;
}

.icon-action-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.icon-action-btn:hover {
  color: #0284c7;
  border-color: #38bdf8;
}

/* 弹窗样式 */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal-content {
  background: #ffffff;
  border-radius: 14px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  width: 100%;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.setup-dialog {
  max-width: 580px;
}

.import-dialog {
  max-width: 720px;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #e2e8f0;
}

.modal-header h3 {
  font-size: 1.1rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.modal-sub {
  font-size: 0.8rem;
  color: #64748b;
  margin: 2px 0 0;
}

.modal-close {
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
}

.modal-close:hover {
  color: #0f172a;
  background: #f1f5f9;
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.modal-footer {
  padding: 14px 20px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  background: #f8fafc;
  border-bottom-left-radius: 14px;
  border-bottom-right-radius: 14px;
}

/* 表单组件 */
.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
}

.required {
  color: #ef4444;
  margin-left: 2px;
}

.form-hint {
  font-size: 0.75rem;
  color: #94a3b8;
  margin: 0;
}

.form-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 0.875rem;
  outline: none;
  transition: border-color 0.2s;
}

.form-input:focus {
  border-color: #0284c7;
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.1);
}

.input-with-action {
  display: flex;
  gap: 8px;
}

.form-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 0.85rem;
  outline: none;
  resize: vertical;
}

.form-textarea:focus {
  border-color: #0284c7;
}

.code-font {
  font-family: var(--font-mono, 'Fira Code', monospace);
}

.advisory-box {
  background: #fffbeb;
  border: 1px solid #fef3c7;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #92400e;
  cursor: pointer;
}

.advisory-desc {
  font-size: 0.75rem;
  color: #b45309;
  margin: 0 0 0 24px;
}

.import-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: -4px;
}

.btn-text-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: #0284c7;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}

.btn-text-action:hover {
  text-decoration: underline;
}

.import-editor {
  line-height: 1.5;
  tab-size: 2;
}
</style>
