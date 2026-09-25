<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Plus, Trash2, X } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import RequirementSpecificationBlock from '@/components/workspace-assets/requirements/RequirementSpecificationBlock.vue'
import { useWorkspaceAssets } from '@/composables/useWorkspaceAssets'
import { useProvisioningStore } from '@/stores/provisioning'
import { useAuthStore } from '@/stores/auth'
import api from '@/utils/api'
import type {
  RequirementDetail,
  RequirementImportBatch,
  RequirementImportConfirmItem,
  RequirementSplitDraft,
  RequirementSplitPayload,
} from '@/types/workspaceAssets'

type EditableSplitItem = {
  item_id: string
  include: boolean
  title: string
  body: string
  acceptance_criteria: string[]
  priority: string
  task_prompt: string
  newCriterionText: string
}

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const wsId = computed(() => String(route.params.wsId || ''))
const requirementId = computed(() => String(route.params.requirementId || ''))
const batchId = computed(() => String(route.params.batchId || ''))

const {
  loadRequirementDetail,
  loadImportBatch,
  confirmRequirementSplit,
  saveRequirementSplitDraft,
  clearRequirementSplitDraft,
} = useWorkspaceAssets()
const provisioningStore = useProvisioningStore()

const loading = ref(true)
const submitting = ref(false)
const requirementDetail = ref<RequirementDetail | null>(null)
const changeReason = ref('')
const items = reactive<EditableSplitItem[]>([])
const activeIndex = ref(0)

// ── 服务端草稿：自动保存 / 恢复 / 「取消」删除 ──
const draftStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const lastSavedLabel = ref('')
const discardConfirmOpen = ref(false)
const discarding = ref(false)
/** 初始装载/草稿恢复期间、以及草稿终结（取消/确认）后禁止自动保存 */
let draftAutosavePaused = true
let draftClosed = false
let draftSaveTimer: ReturnType<typeof setTimeout> | undefined
let draftSavePromise: Promise<boolean> | null = null

const parentRequirement = computed(() => requirementDetail.value?.requirement || null)
const activeItem = computed(() => items[activeIndex.value] || null)

const selectedCount = computed(() => items.filter((item) => item.include).length)
const allSelected = computed({
  get: () => items.length > 0 && items.every((item) => item.include),
  set: (val: boolean) => {
    items.forEach((item) => {
      item.include = val
    })
  },
})

const priorityOptions = [
  { label: 'P0 High', value: 'High' },
  { label: 'P1 Medium', value: 'Medium' },
  { label: 'P2 Low', value: 'Low' },
]

function getPriorityBadgeClass(priority: string) {
  const p = String(priority || '').toLowerCase()
  if (p.includes('high') || p === 'p0') return 'priority-high'
  if (p.includes('low') || p === 'p2') return 'priority-low'
  return 'priority-medium'
}

/** 批次 AI 原始预览 + 服务端草稿覆盖层 → 可编辑列表；草稿优先，缺失字段回落原始预览 */
function applyDraft(batch: RequirementImportBatch, draft: RequirementSplitDraft | null | undefined) {
  const draftById = new Map((draft?.items || []).map((draftItem) => [draftItem.item_id, draftItem]))
  const matchedIds = new Set<string>()
  items.splice(0, items.length)
  for (const raw of batch.items || []) {
    const draftItem = draftById.get(raw.id)
    if (draftItem) matchedIds.add(raw.id)
    const draftCriteria = draftItem?.acceptance_criteria
    items.push({
      item_id: raw.id,
      include: draftItem ? draftItem.include : raw.status !== 'SKIPPED',
      title: draftItem?.title ?? raw.title ?? '',
      body: draftItem?.body ?? raw.body ?? '',
      acceptance_criteria: Array.isArray(draftCriteria)
        ? [...draftCriteria]
        : Array.isArray(raw.acceptance_criteria)
          ? [...raw.acceptance_criteria]
          : [],
      priority: draftItem?.priority ?? raw.priority ?? 'Medium',
      task_prompt: draftItem?.task_prompt ?? raw.task_prompt ?? '',
      newCriterionText: '',
    })
  }
  // 草稿中比批次多出的条目：评审页手工新建、尚未确认回传的自定义子需求
  for (const draftItem of draft?.items || []) {
    if (matchedIds.has(draftItem.item_id)) continue
    items.push({
      item_id: draftItem.item_id,
      include: draftItem.include,
      title: draftItem.title ?? '',
      body: draftItem.body ?? '',
      acceptance_criteria: Array.isArray(draftItem.acceptance_criteria) ? [...draftItem.acceptance_criteria] : [],
      priority: draftItem.priority ?? 'Medium',
      task_prompt: draftItem.task_prompt ?? '',
      newCriterionText: '',
    })
  }
  if (items.length > 0) {
    activeIndex.value = 0
  }
}

async function loadData() {
  loading.value = true
  try {
    // 批次一律取服务端真身：草稿覆盖层只存在于服务端（同 workspace 其他用户可见）
    const [detail, batch] = await Promise.all([
      loadRequirementDetail(wsId.value, requirementId.value),
      loadImportBatch(wsId.value, batchId.value),
    ])

    requirementDetail.value = detail
    if (batch) {
      applyDraft(batch, batch.draft)
      if (batch.draft) {
        changeReason.value = batch.draft.change_reason || ''
        ElMessage.info(t('workspace_assets.requirements.split_review.draft_restored'))
      }
    }
    // 恢复产生的变更不算编辑：watcher 在恢复期间保持暂停
    await nextTick()
    draftAutosavePaused = false
  } finally {
    loading.value = false
  }
}

function selectItem(index: number) {
  activeIndex.value = index
}

function addCriterion(item: EditableSplitItem) {
  const text = item.newCriterionText.trim()
  if (!text) return
  item.acceptance_criteria.push(text)
  item.newCriterionText = ''
}

function removeCriterion(item: EditableSplitItem, index: number) {
  item.acceptance_criteria.splice(index, 1)
}

function addNewItem() {
  items.push({
    item_id: `custom-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    include: true,
    title: '',
    body: '',
    acceptance_criteria: [],
    priority: 'Medium',
    task_prompt: '',
    newCriterionText: '',
  })
  activeIndex.value = items.length - 1
}

function removeItem(index: number) {
  items.splice(index, 1)
  if (activeIndex.value >= items.length) {
    activeIndex.value = Math.max(0, items.length - 1)
  }
}

function buildDraftPayload(): RequirementSplitDraft {
  return {
    change_reason: changeReason.value.trim() || null,
    items: items.map((item) => ({
      item_id: item.item_id,
      include: item.include,
      title: item.title,
      body: item.body || null,
      acceptance_criteria: [...item.acceptance_criteria],
      priority: item.priority || null,
      task_prompt: item.task_prompt || null,
    })),
  }
}

function scheduleDraftSave() {
  if (draftAutosavePaused || draftClosed) return
  if (draftSaveTimer) clearTimeout(draftSaveTimer)
  draftSaveTimer = setTimeout(() => {
    draftSaveTimer = undefined
    draftSavePromise = flushDraftSave()
  }, 800)
}

async function flushDraftSave(): Promise<boolean> {
  if (draftSaveTimer) {
    clearTimeout(draftSaveTimer)
    draftSaveTimer = undefined
  }
  if (draftAutosavePaused || draftClosed || !batchId.value) return false
  draftStatus.value = 'saving'
  const ok = await saveRequirementSplitDraft(wsId.value, batchId.value, buildDraftPayload())
  draftStatus.value = ok ? 'saved' : 'error'
  if (ok) {
    lastSavedLabel.value = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  return ok
}

watch([items, changeReason], () => {
  scheduleDraftSave()
}, { deep: true })

onBeforeUnmount(() => {
  if (draftSaveTimer) {
    clearTimeout(draftSaveTimer)
    draftSaveTimer = undefined
  }
  window.removeEventListener('pagehide', handlePageHide)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})

/** 页面隐藏/卸载通道：防抖来不及触发时的兜底保存。
 *  用 fetch keepalive 让请求在页面卸载后仍能发完（axios 不支持 keepalive，
 *  sendBeacon 带不了 Authorization 头）；草稿体远小于 64KB 浏览器上限。 */
function keepaliveDraftSave() {
  if (draftAutosavePaused || draftClosed || !batchId.value) return
  const authStore = useAuthStore()
  if (!authStore.token) return
  const url = `${api.defaults.baseURL}/workspaces/${wsId.value}/workspace-assets/requirements/import-batches/${batchId.value}/draft`
  try {
    void fetch(url, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authStore.token}`,
      },
      body: JSON.stringify(buildDraftPayload()),
      keepalive: true,
    })
  } catch {
    // 页面正在卸载，尽力而为
  }
}

function handlePageHide() {
  keepaliveDraftSave()
}

function handleVisibilityChange() {
  if (document.visibilityState === 'hidden') {
    keepaliveDraftSave()
  }
}

const draftStatusText = computed(() => {
  switch (draftStatus.value) {
    case 'saving':
      return t('workspace_assets.requirements.split_review.draft_saving')
    case 'saved':
      return t('workspace_assets.requirements.split_review.draft_saved', { time: lastSavedLabel.value })
    case 'error':
      return t('workspace_assets.requirements.split_review.draft_save_failed')
    default:
      return ''
  }
})

async function navigateBack() {
  await router.push({
    name: 'workspaceAssetsRequirementDetail',
    params: {
      wsId: wsId.value,
      requirementId: requirementId.value,
    },
  })
}

/** 「返回需求详情」= 保留草稿退出：先 flush 在途编辑，下次「拆分」直接回本页续编 */
async function goBack() {
  await flushDraftSave()
  await navigateBack()
}

/** 草稿删除/确认消费后，清掉浮窗里绑定该批次的旧拆分作业卡片：
 *  否则「拆分」入口会经 findLatestPreviewResult 再跳回已消费的批次。 */
function dismissBatchJob() {
  const job = provisioningStore.jobList.find(
    (candidate) => candidate.kind === 'requirement_split_preview' && candidate.batch?.id === batchId.value,
  )
  if (job) provisioningStore.dismiss(job.jobId)
}

/** 「取消」= 删除草稿（破坏性操作，先二次确认） */
function requestDiscard() {
  discardConfirmOpen.value = true
}

async function confirmDiscard() {
  if (discarding.value) return
  discarding.value = true
  try {
    // 先终结自动保存并等在途请求收敛，避免「先 PUT 后 DELETE」复活草稿
    draftClosed = true
    if (draftSaveTimer) {
      clearTimeout(draftSaveTimer)
      draftSaveTimer = undefined
    }
    if (draftSavePromise) {
      await draftSavePromise
      draftSavePromise = null
    }
    const ok = await clearRequirementSplitDraft(wsId.value, batchId.value)
    if (!ok) {
      // 删除失败保持原状：允许继续编辑，自动保存重新启用
      draftClosed = false
      ElMessage.error(t('workspace_assets.requirements.split_review.draft_discard_failed'))
      return
    }
    discardConfirmOpen.value = false
    dismissBatchJob()
    ElMessage.success(t('workspace_assets.requirements.split_review.draft_discarded'))
    await navigateBack()
  } finally {
    discarding.value = false
  }
}

async function handleConfirm() {
  if (!selectedCount.value) return
  // 确认即消费草稿：服务端 confirm 会清批次草稿，本地停止自动保存并等在途请求收敛
  draftClosed = true
  if (draftSaveTimer) {
    clearTimeout(draftSaveTimer)
    draftSaveTimer = undefined
  }
  if (draftSavePromise) {
    await draftSavePromise
    draftSavePromise = null
  }
  submitting.value = true
  try {
    const confirmItems: RequirementImportConfirmItem[] = items.map((item) => ({
      item_id: item.item_id,
      include: item.include,
      title: item.title.trim(),
      body: item.body.trim() || null,
      acceptance_criteria: item.acceptance_criteria,
      priority: item.priority || null,
      task_prompt: item.task_prompt.trim() || null,
      status: 'DRAFT',
    }))

    const payload: RequirementSplitPayload = {
      batch_id: batchId.value,
      items: confirmItems,
      change_reason: changeReason.value.trim() || null,
    }

    const result = await confirmRequirementSplit(wsId.value, requirementId.value, payload)
    if (result) {
      ElMessage.success(t('workspace_assets.requirements.split_review.confirm_success'))
      dismissBatchJob()
      await navigateBack()
    } else {
      // 确认失败恢复编辑态（草稿自动保存重新启用）
      draftClosed = false
    }
  } finally {
    submitting.value = false
  }
}

// 页内路由离开（含浏览器返回键）：等在途草稿保存收敛后再离开，不丢最后一段编辑
onBeforeRouteLeave(async () => {
  await flushDraftSave()
})

onMounted(() => {
  window.addEventListener('pagehide', handlePageHide)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  void loadData()
})
</script>

<template>
  <div v-loading="loading" class="split-review-view">
    <!-- 顶部导航与主操作栏 -->
    <header class="top-nav-bar">
      <div class="nav-left">
        <button class="back-link" type="button" @click="goBack">
          <ArrowLeft class="back-icon" />
          <span>{{ t('workspace_assets.requirements.split_review.back_to_parent') }}</span>
        </button>
        <div class="nav-title-box">
          <span class="eyebrow-tag">AI 需求拆分工作台</span>
          <span class="nav-requirement-title" :title="parentRequirement?.title || ''">
            {{ parentRequirement?.title || t('workspace_assets.requirements.split_review.title') }}
          </span>
        </div>
      </div>

      <div class="nav-right">
        <span
          v-if="draftStatus !== 'idle'"
          class="draft-status"
          :class="`is-${draftStatus}`"
        >{{ draftStatusText }}</span>
        <input
          v-model="changeReason"
          type="text"
          class="reason-input"
          :placeholder="t('workspace_assets.requirements.placeholders.change_reason')"
        />
        <button class="btn-cancel" type="button" @click="requestDiscard">
          {{ t('workspace_assets.requirements.split_review.discard_action') }}
        </button>
        <button
          class="btn-confirm"
          type="button"
          :disabled="submitting || selectedCount === 0"
          @click="handleConfirm"
        >
          <span v-if="submitting">{{ t('workspace_assets.requirements.split_review.submitting') }}</span>
          <span v-else>{{ t('workspace_assets.requirements.split_review.confirm_action', { count: selectedCount }) }}</span>
        </button>
      </div>
    </header>

    <!-- 双栏宽阔工作台：左栏母需求规格全景 (45%) + 右栏子需求拆分工作区 (55%) -->
    <main class="workbench-grid">
      <!-- 栏 1：母需求原始规格（Ground Truth，宽敞全貌，独立滚动，绝不折叠） -->
      <section class="workbench-column spec-column content-card">
        <div class="column-header">
          <span class="column-eyebrow">对照基准</span>
          <h2 class="column-title">母需求原始规格</h2>
        </div>

        <div class="spec-scroll-body">
          <div class="spec-hero-box">
            <h3 class="parent-title">{{ parentRequirement?.title || '未命名需求' }}</h3>
            <div class="parent-meta-row">
              <span class="meta-tag status-tag">{{ parentRequirement?.status || 'DRAFT' }}</span>
              <span class="meta-tag priority-tag" :class="getPriorityBadgeClass(parentRequirement?.priority || '')">
                {{ parentRequirement?.priority || '未设置' }}
              </span>
            </div>
          </div>

          <div class="spec-section">
            <h4 class="spec-section-title">规格说明内容</h4>
            <div v-if="parentRequirement?.body" class="spec-body-wrapper">
              <RequirementSpecificationBlock
                :body="parentRequirement.body"
                :empty-text="t('workspace_assets.requirements.split_review.no_parent_spec')"
              />
            </div>
            <div v-else class="empty-spec-text">
              {{ t('workspace_assets.requirements.split_review.no_parent_spec') }}
            </div>
          </div>

          <div class="spec-section" v-if="parentRequirement?.acceptance_criteria?.length">
            <h4 class="spec-section-title">原始验收准则</h4>
            <ul class="criteria-list">
              <li v-for="(crit, idx) in parentRequirement.acceptance_criteria" :key="idx">
                {{ crit }}
              </li>
            </ul>
          </div>
        </div>
      </section>

      <!-- 栏 2：子需求拆分工作区（顶部水平卡片选择栏 + 下方宽阔深度编辑画布） -->
      <section class="workbench-column editor-column content-card">
        <!-- 顶部水平子需求选择条（紧凑卡片，彻底不占水平列宽） -->
        <div class="sub-nav-bar-wrapper">
          <div class="sub-nav-bar-header">
            <label class="checkbox-label" title="全选 / 取消全选">
              <input v-model="allSelected" type="checkbox" />
              <span class="list-count-text">{{ selectedCount }} / {{ items.length }} 项将纳入需求库</span>
            </label>
            <button class="btn-add-sub" type="button" @click="addNewItem">
              <Plus class="w-3-5 h-3-5" />
              <span>新建子需求</span>
            </button>
          </div>

          <!-- 横向子需求卡片滑动栏 -->
          <div class="sub-cards-strip">
            <div
              v-for="(item, idx) in items"
              :key="item.item_id"
              class="strip-card"
              :class="{ active: idx === activeIndex }"
              @click="selectItem(idx)"
            >
              <div class="strip-card-top">
                <label class="card-checkbox-label" @click.stop>
                  <input v-model="item.include" type="checkbox" />
                </label>
                <span class="card-seq-num">#{{ idx + 1 }}</span>
                <span class="card-priority-pill" :class="getPriorityBadgeClass(item.priority)">
                  {{ item.priority }}
                </span>
                <button
                  class="card-delete-btn"
                  type="button"
                  title="删除该子需求"
                  @click.stop="removeItem(idx)"
                >
                  <Trash2 class="w-3-5 h-3-5" />
                </button>
              </div>

              <div class="strip-card-title" :title="item.title || '（未命名子需求）'">
                {{ item.title || '（未命名子需求）' }}
              </div>

              <div class="strip-card-footer">
                <span class="criteria-count-chip">
                  {{ item.acceptance_criteria.length }} 项准则
                </span>
              </div>
            </div>

            <div v-if="items.length === 0" class="strip-empty-hint">
              <span>暂无子需求条目</span>
            </div>
          </div>
        </div>

        <!-- 下方主编辑画布（超宽超从容） -->
        <div v-if="activeItem" class="editor-scroll-body">
          <div class="editor-action-header">
            <div class="active-identity">
              <span class="active-badge">#{{ activeIndex + 1 }}</span>
              <h2 class="active-title">{{ activeItem.title || '编辑子需求规格' }}</h2>
            </div>
            <div class="active-controls">
              <label class="include-toggle-label">
                <input v-model="activeItem.include" type="checkbox" />
                <span>{{ t('workspace_assets.requirements.split_review.include_in_import') }}</span>
              </label>
              <button
                class="btn-danger-ghost"
                type="button"
                title="删除该子需求"
                @click="removeItem(activeIndex)"
              >
                <Trash2 class="w-4 h-4" />
                <span>{{ t('workspace_assets.requirements.actions.delete') }}</span>
              </button>
            </div>
          </div>

          <!-- 表单核心区域 -->
          <div class="form-container">
            <div class="form-row-grid">
              <div class="form-group flex-1">
                <label class="field-label">{{ t('workspace_assets.requirements.fields.title') }}</label>
                <input
                  v-model="activeItem.title"
                  type="text"
                  class="field-input"
                  :placeholder="t('workspace_assets.requirements.placeholders.title')"
                />
              </div>

              <div class="form-group priority-field-group">
                <label class="field-label">{{ t('workspace_assets.requirements.fields.priority') }}</label>
                <BaseSelect v-model="activeItem.priority" :options="priorityOptions" class="field-select" size="sm" />
              </div>
            </div>

            <div class="form-group">
              <label class="field-label">{{ t('workspace_assets.requirements.fields.body') }}</label>
              <textarea
                v-model="activeItem.body"
                rows="6"
                class="field-textarea"
                :placeholder="t('workspace_assets.requirements.placeholders.description')"
              ></textarea>
            </div>

            <div class="form-group">
              <div class="field-label-with-tip">
                <span class="field-label">{{ t('workspace_assets.requirements.fields.acceptance_criteria') }}</span>
                <span class="field-tip">条目化判定依据，回车可快捷新增</span>
              </div>

              <div class="criteria-editor-box">
                <div
                  v-for="(_, cIdx) in activeItem.acceptance_criteria"
                  :key="cIdx"
                  class="criterion-row-item"
                >
                  <span class="criterion-dot"></span>
                  <input
                    v-model="activeItem.acceptance_criteria[cIdx]"
                    type="text"
                    class="criterion-inline-input"
                  />
                  <button
                    class="criterion-remove-btn"
                    type="button"
                    title="移除准则"
                    @click="removeCriterion(activeItem, cIdx)"
                  >
                    <X class="w-3-5 h-3-5" />
                  </button>
                </div>

                <div class="criterion-append-row">
                  <input
                    v-model="activeItem.newCriterionText"
                    type="text"
                    class="criterion-append-input"
                    :placeholder="t('workspace_assets.requirements.split_review.criterion_placeholder')"
                    @keydown.enter.prevent="addCriterion(activeItem)"
                  />
                  <button
                    class="btn-append-criteria"
                    type="button"
                    :disabled="!activeItem.newCriterionText.trim()"
                    @click="addCriterion(activeItem)"
                  >
                    {{ t('workspace_assets.requirements.split_review.add_criterion') }}
                  </button>
                </div>
              </div>
            </div>

            <div class="form-group">
              <label class="field-label">{{ t('workspace_assets.requirements.split_review.task_prompt_label') }}</label>
              <textarea
                v-model="activeItem.task_prompt"
                rows="4"
                class="field-textarea font-mono"
                :placeholder="t('workspace_assets.requirements.placeholders.task_prompt')"
              ></textarea>
            </div>
          </div>
        </div>

        <div v-else class="no-active-empty">
          <p>{{ t('workspace_assets.requirements.split_review.no_items') }}</p>
        </div>
      </section>
    </main>

    <!-- 取消 = 删除草稿：破坏性操作二次确认（确认后下次「拆分」重新发起 AI 拆分） -->
    <ConfirmActionModal
      :show="discardConfirmOpen"
      :title="t('workspace_assets.requirements.split_review.discard_confirm_title')"
      :message="t('workspace_assets.requirements.split_review.discard_confirm_message')"
      :cancel-text="t('common.cancel')"
      :confirm-text="t('workspace_assets.requirements.split_review.discard_confirm_text')"
      :loading="discarding"
      tone="danger"
      @cancel="discardConfirmOpen = false"
      @confirm="confirmDiscard"
    />
  </div>
</template>

<style scoped>
/* ── 全局页面容器与背景 ── */
.split-review-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  box-sizing: border-box;
  padding: 20px 28px;
  background-color: #f8fafc;
  color: #0f172a;
  font-family: 'Open Sans', var(--font-body);
  overflow: hidden;
}

/* ── 顶部导航与主操作栏 ── */
.top-nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 16px;
  flex-shrink: 0;
  min-height: 42px;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
  flex: 1;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 16px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  color: #475569;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  flex-shrink: 0;
}

.back-link:hover {
  color: #0ea5e9;
  border-color: rgba(14, 165, 233, 0.4);
  background: #ffffff;
  transform: translateX(-2px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.12);
}

.back-icon {
  width: 16px;
  height: 16px;
}

.nav-title-box {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}

.eyebrow-tag {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  background: #e0f2fe;
  color: #0369a1;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  border-radius: 5px;
  letter-spacing: 0.5px;
  flex-shrink: 0;
}

.nav-requirement-title {
  font-family: 'Poppins', sans-serif;
  font-size: 1.15rem;
  font-weight: 700;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.draft-status {
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
  color: #94a3b8;
}

.draft-status.is-saving {
  color: #0284c7;
}

.draft-status.is-saved {
  color: #16a34a;
}

.draft-status.is-error {
  color: #dc2626;
}

.reason-input {
  width: 250px;
  height: 38px;
  box-sizing: border-box;
  padding: 0 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.9);
  font-size: 0.85rem;
  color: #0f172a;
  transition: all 0.2s ease;
}

.reason-input:focus {
  border-color: #0ea5e9;
  background: #ffffff;
  outline: none;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}

.btn-cancel {
  height: 38px;
  padding: 0 18px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  color: #475569;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-cancel:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
  color: #0f172a;
}

.btn-confirm {
  height: 38px;
  padding: 0 22px;
  border: 1px solid #0284c7;
  border-radius: 10px;
  background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
  color: #ffffff;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(14, 165, 233, 0.28);
  transition: all 0.2s ease;
}

.btn-confirm:hover:not(:disabled) {
  background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
  box-shadow: 0 6px 18px rgba(14, 165, 233, 0.38);
  transform: translateY(-1px);
}

.btn-confirm:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
}

/* ── 双栏布局主网格（45% 母规格 : 55% 子需求工作区） ── */
.workbench-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(420px, 45%) minmax(500px, 55%);
  gap: 20px;
}

/* 统一卡片样式（对齐 RequirementDetailContent） */
.content-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.03);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-sizing: border-box;
}

.column-header {
  padding: 14px 20px;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
  flex-shrink: 0;
}

.column-eyebrow {
  display: block;
  font-size: 11px;
  font-weight: 800;
  color: #0284c7;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 2px;
}

.column-title {
  margin: 0;
  font-family: 'Poppins', sans-serif;
  font-size: 1.05rem;
  font-weight: 700;
  color: #0f172a;
}

/* ── 栏 1：母需求规格面板（宽敞阅读区） ── */
.spec-column {
  /* 去除顶部色条，保持统一平整边框 */
}

.spec-scroll-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.spec-hero-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 18px;
}

.parent-title {
  margin: 0 0 10px;
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.35;
}

.parent-meta-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.meta-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.status-tag {
  background: #f1f5f9;
  color: #475569;
}

.priority-tag.priority-high { background: #fee2e2; color: #b91c1c; }
.priority-tag.priority-medium { background: #fef3c7; color: #b45309; }
.priority-tag.priority-low { background: #e0f2fe; color: #0369a1; }

.spec-section-title {
  margin: 0 0 10px;
  font-family: 'Poppins', sans-serif;
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e3a8a;
}

.spec-body-wrapper {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 20px;
  font-size: 0.9rem;
  line-height: 1.65;
}

.empty-spec-text {
  font-size: 0.85rem;
  color: #94a3b8;
  font-style: italic;
}

/* 准则列表样式（对齐 RequirementDetailContent） */
.criteria-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.criteria-list li {
  position: relative;
  padding-left: 28px;
  font-size: 0.875rem;
  color: #334155;
  line-height: 1.6;
}

.criteria-list li::before {
  content: '✓';
  position: absolute;
  left: 0;
  top: 2px;
  width: 18px;
  height: 18px;
  background: #e0f2fe;
  color: #0ea5e9;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 900;
}

/* ── 栏 2：子需求拆分工作区 ── */
.editor-column {
  /* 去除顶部色条，保持统一平整边框 */
}

/* 顶部水平子需求选择带 */
.sub-nav-bar-wrapper {
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  padding: 14px 18px 12px;
  flex-shrink: 0;
}

.sub-nav-bar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.list-count-text {
  font-size: 0.82rem;
  color: #0284c7;
  font-weight: 700;
}

.btn-add-sub {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 12px;
  border: 1px solid #bae6fd;
  border-radius: 8px;
  background: #f0f9ff;
  color: #0284c7;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-add-sub:hover {
  background: #e0f2fe;
  border-color: #7dd3fc;
}

.sub-cards-strip {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.sub-cards-strip::-webkit-scrollbar {
  height: 4px;
}

.sub-cards-strip::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 4px;
}

.strip-card {
  flex: 0 0 210px;
  width: 210px;
  box-sizing: border-box;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 8px 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.strip-card:hover {
  border-color: #94a3b8;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
}

.strip-card.active {
  background: #f0f9ff;
  border-color: #0ea5e9;
  box-shadow: 0 2px 10px rgba(14, 165, 233, 0.16);
}

.strip-card-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.card-seq-num {
  font-size: 0.78rem;
  font-weight: 700;
  color: #64748b;
  font-family: var(--font-mono);
}

.card-priority-pill {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  text-transform: uppercase;
}

.card-priority-pill.priority-high { background: #fee2e2; color: #b91c1c; }
.card-priority-pill.priority-medium { background: #fef3c7; color: #b45309; }
.card-priority-pill.priority-low { background: #e0f2fe; color: #0369a1; }

.card-delete-btn {
  margin-left: auto;
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.card-delete-btn:hover {
  color: #ef4444;
  background: #fee2e2;
}

.strip-card-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #0f172a;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.strip-card-footer {
  display: flex;
  align-items: center;
}

.criteria-count-chip {
  font-size: 0.7rem;
  font-weight: 600;
  color: #64748b;
  background: rgba(241, 245, 249, 0.8);
  padding: 1px 5px;
  border-radius: 4px;
}

.strip-empty-hint {
  padding: 10px;
  color: #94a3b8;
  font-size: 0.82rem;
}

/* ── 下方宽阔编辑区 ── */
.editor-scroll-body {
  flex: 1;
  overflow-y: auto;
  padding: 22px 26px;
}

.editor-action-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid #e2e8f0;
  margin-bottom: 18px;
}

.active-identity {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.active-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  border-radius: 6px;
  background: #e0f2fe;
  color: #0369a1;
  font-weight: 800;
  font-size: 0.85rem;
  font-family: var(--font-mono);
}

.active-title {
  margin: 0;
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.active-controls {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}

.include-toggle-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
  user-select: none;
}

.btn-danger-ghost {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
  background: rgba(254, 242, 242, 0.6);
  color: #ef4444;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-danger-ghost:hover {
  background: #fee2e2;
  border-color: #fca5a5;
}

/* 表单组件规范 */
.form-container {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.form-row-grid {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.flex-1 {
  flex: 1;
}

.priority-field-group {
  width: 160px;
  flex-shrink: 0;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 0.8125rem;
  font-weight: 700;
  color: #475569;
  letter-spacing: 0.01em;
}

.field-label-with-tip {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.field-tip {
  font-size: 0.75rem;
  color: #94a3b8;
}

.field-input,
.field-select,
.field-textarea {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  color: #0f172a;
  font-family: inherit;
  font-size: 0.875rem;
  padding: 10px 14px;
  transition: all 0.2s ease;
}

.field-input:focus,
.field-select:focus,
.field-textarea:focus {
  border-color: #0ea5e9;
  outline: none;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}

.field-select {
  height: 40px;
  cursor: pointer;
}

.field-textarea {
  resize: vertical;
  line-height: 1.6;
}

.font-mono {
  font-family: var(--font-mono);
  font-size: 0.8125rem;
}

/* 验收准则编辑器卡片 */
.criteria-editor-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.criterion-row-item {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 12px;
  transition: all 0.2s ease;
}

.criterion-row-item:hover {
  border-color: #cbd5e1;
}

.criterion-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #0ea5e9;
  flex-shrink: 0;
}

.criterion-inline-input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 0.875rem;
  color: #0f172a;
  padding: 2px 4px;
  outline: none;
}

.criterion-remove-btn {
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.criterion-remove-btn:hover {
  color: #ef4444;
  background: #fee2e2;
}

.criterion-append-row {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.criterion-append-input {
  flex: 1;
  height: 38px;
  box-sizing: border-box;
  padding: 0 14px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: #ffffff;
  font-size: 0.875rem;
  color: #0f172a;
  outline: none;
  transition: all 0.2s ease;
}

.criterion-append-input:focus {
  border-style: solid;
  border-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}

.btn-append-criteria {
  height: 38px;
  padding: 0 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  color: #0284c7;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-append-criteria:hover:not(:disabled) {
  background: #f0f9ff;
  border-color: #bae6fd;
}

.btn-append-criteria:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.no-active-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #94a3b8;
  font-size: 0.95rem;
}

/* ── 全局 Checkbox 规范（对齐 ChatView 与 NewTaskModal） ── */
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  user-select: none;
}

.card-checkbox-label {
  display: flex;
  align-items: center;
}

.checkbox-label input[type="checkbox"],
.card-checkbox-label input[type="checkbox"],
.include-toggle-label input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  margin: 0;
  border-radius: 4px;
  border: 1.5px solid #cbd5e1;
  background-color: #ffffff;
  background-repeat: no-repeat;
  background-position: center;
  background-size: 11px 11px;
  cursor: pointer;
  transition: all 0.16s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
  outline: none;
  display: inline-block;
  vertical-align: middle;
}

.checkbox-label input[type="checkbox"]:hover:not(:disabled),
.card-checkbox-label input[type="checkbox"]:hover:not(:disabled),
.include-toggle-label input[type="checkbox"]:hover:not(:disabled) {
  border-color: #38bdf8;
  background-color: #f0f9ff;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}

.checkbox-label input[type="checkbox"]:checked,
.card-checkbox-label input[type="checkbox"]:checked,
.include-toggle-label input[type="checkbox"]:checked {
  border-color: #0ea5e9;
  background-color: #0ea5e9;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M2.5 7L5.5 10L11.5 4' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  box-shadow: 0 2px 4px rgba(14, 165, 233, 0.25);
}

.checkbox-label input[type="checkbox"]:checked:hover:not(:disabled),
.card-checkbox-label input[type="checkbox"]:checked:hover:not(:disabled),
.include-toggle-label input[type="checkbox"]:checked:hover:not(:disabled) {
  border-color: #0284c7;
  background-color: #0284c7;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.35);
}

.checkbox-label input[type="checkbox"]:focus-visible,
.card-checkbox-label input[type="checkbox"]:focus-visible,
.include-toggle-label input[type="checkbox"]:focus-visible {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.22);
}

/* 图标工具类 */
.w-3-5 { width: 14px; }
.h-3-5 { height: 14px; }
.w-4 { width: 16px; }
.h-4 { height: 16px; }

/* 响应式调整 */
@media (max-width: 1000px) {
  .workbench-grid {
    grid-template-columns: 1fr;
  }
}
</style>
