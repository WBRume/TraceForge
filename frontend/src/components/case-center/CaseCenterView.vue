<script setup lang="ts">
import { computed, onMounted, onUnmounted, proxyRefs, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Search, Plus, Loader2, BookMarked, RefreshCw, Workflow } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import { useCaseCenter } from '@/composables/useCaseCenter'
import CaseStatusPill from './CaseStatusPill.vue'
import CaseCategoryTag from './CaseCategoryTag.vue'
import CasePriorityTag from './CasePriorityTag.vue'
import CaseFormDialog from './CaseFormDialog.vue'
import PlaybookLibrary from './PlaybookLibrary.vue'
import CasePromotionAction from './CasePromotionAction.vue'

interface WorkspaceOption {
  label: string
  value: string
}

const props = withDefaults(defineProps<{
  workspaceId?: string
  embedded?: boolean
  workspaceOptions?: WorkspaceOption[]
}>(), {
  embedded: false,
  workspaceOptions: () => [],
})

const emit = defineEmits<{
  (e: 'update:workspaceId', value: string): void
}>()

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const activeWorkspaceId = computed(() => {
  if (props.workspaceId !== undefined) return String(props.workspaceId || '')
  return String(route.params.wsId || '')
})

const vm = proxyRefs(useCaseCenter({ workspaceId: () => activeWorkspaceId.value }))

const workspaceFilter = computed({
  get: () => props.workspaceId ?? '',
  set: (value: string) => emit('update:workspaceId', String(value || '')),
})

const searchInput = ref('')
const activeTab = ref(route.query.tab === 'playbooks' ? 'playbooks' : 'cases')
const showPromotionTab = () => { activeTab.value = 'cases' }
watch(() => route.query.promotionJob, (id) => { if (id) showPromotionTab() }, { immediate: true })
onMounted(() => window.addEventListener('playbook-promotion-open', showPromotionTab))
onUnmounted(() => window.removeEventListener('playbook-promotion-open', showPromotionTab))
const selectedCases = ref<Record<string, string>>({})
const promotionWorkspace = computed(() => activeWorkspaceId.value || Object.values(selectedCases.value)[0] || '')
const toggleCase = (id: string, workspace: string) => {
  if (selectedCases.value[id]) delete selectedCases.value[id]
  else selectedCases.value[id] = workspace
}

const statusOptions = ['ALL', 'TECHNICALLY_VERIFIED', 'DRAFT', 'PENDING_REVIEW', 'IN_REVIEW', 'APPROVED', 'REJECTED']
const priorityOptions = ['ALL', 'P0', 'P1', 'P2', 'P3']

const statusSelectOptions = computed(() =>
  statusOptions.map((s) => ({
    label: s === 'ALL' ? t('case_center.status_all') : s === 'TECHNICALLY_VERIFIED' ? '物理验证归档' : t(`case_center.status.${s}`),
    value: s,
  })),
)
const prioritySelectOptions = computed(() =>
  priorityOptions.map((p) => ({
    label: p === 'ALL' ? t('case_center.priority_all') : p,
    value: p,
  })),
)

const runSearch = () => {
  vm.keyword = searchInput.value
  vm.applyFilters()
}

const goToReport = (caseId: string, item?: { workspace_id?: string }) => {
  const wsId = String(item?.workspace_id || route.params.wsId || '')
  if (!wsId) return
  router.push(
    props.embedded
      ? { name: 'knowledgeCaseDetail', params: { wsId, caseId } }
      : { name: 'workspaceCaseDetail', params: { wsId, caseId } },
  )
}

const handleOpenCase = (item: { id: string; workspace_id?: string }) => {
  goToReport(item.id, item)
}

// 兼容旧的 ?case= 深链：直接跳转到独立报告页
const redirectQueryCase = () => {
  const caseId = String(route.query.case || '')
  if (!caseId) return
  const target = vm.items.find((item) => item.id === caseId)
  const wsId = String(target?.workspace_id || route.params.wsId || '')
  if (!wsId) return
  router.replace(
    props.embedded
      ? { name: 'knowledgeCaseDetail', params: { wsId, caseId } }
      : { name: 'workspaceCaseDetail', params: { wsId, caseId } },
  )
}

onMounted(async () => {
  await vm.loadCases({ reset: true })
  redirectQueryCase()
})

watch(
  () => route.query.case,
  (value) => {
    if (value) redirectQueryCase()
  },
)

watch(activeWorkspaceId, () => {
  selectedCases.value = {}
  void vm.loadCases({ reset: true })
})
</script>

<template>
  <div class="case-center" :class="{ 'case-center--embedded': embedded }">
    <!-- 案例中心一体化资产双标签导航 -->
    <div class="cc-tabs-container">
      <div class="cc-tabs" role="tablist" aria-label="案例中心资产类型">
        <button
          type="button"
          role="tab"
          class="cc-tab"
          :class="{ active: activeTab === 'cases' }"
          :aria-selected="activeTab === 'cases'"
          @click="activeTab = 'cases'"
        >
          <BookMarked :size="16" />
          <span>排查案例库</span>
          <span v-if="vm.total > 0" class="cc-tab-badge">{{ vm.total }}</span>
        </button>
        <button
          type="button"
          role="tab"
          class="cc-tab"
          :class="{ active: activeTab === 'playbooks' }"
          :aria-selected="activeTab === 'playbooks'"
          @click="activeTab = 'playbooks'"
        >
          <Workflow :size="16" />
          <span>故障诊断规程</span>
        </button>
      </div>
    </div>
    <PlaybookLibrary v-if="activeTab === 'playbooks'" :workspace-id="activeWorkspaceId" />
    <template v-else>
    <div class="cc-header" :class="{ 'cc-header-embedded': embedded }">
      <div v-if="!embedded" class="cc-title-row">
        <BookMarked class="w-6 h-6 cc-icon" />
        <div>
          <h2 class="cc-title">{{ t('case_center.title') }}</h2>
          <p class="cc-subtitle">{{ t('case_center.subtitle') }}</p>
        </div>
      </div>
      <div class="cc-actions">
        <div class="search-box">
          <Search :size="16" class="search-icon" />
          <input
            v-model="searchInput"
            type="text"
            class="search-input"
            :placeholder="t('case_center.search_placeholder')"
            @keyup.enter="runSearch"
          />
          <button class="btn-primary" @click="runSearch">{{ t('case_center.search') }}</button>
        </div>
        <button class="btn-primary flex items-center gap-2" @click="vm.openCreateForm()">
          <Plus :size="16" /> {{ t('case_center.create_button') }}
        </button>
      </div>
    </div>

    <div class="cc-filter-bar">
      <div class="filter-selects">
        <BaseSelect
          v-if="workspaceOptions.length > 0"
          v-model="workspaceFilter"
          :options="workspaceOptions"
          class="workspace-filter-select"
        />
        <BaseSelect v-model="vm.status" :options="statusSelectOptions" class="filter-select" @update:model-value="vm.applyFilters()" />
        <BaseSelect v-model="vm.priority" :options="prioritySelectOptions" class="filter-select" @update:model-value="vm.applyFilters()" />
        <button class="icon-btn refresh-btn" :title="t('common.refresh')" @click="vm.applyFilters()">
          <RefreshCw :size="16" />
        </button>
    <div class="cc-promotion"><CasePromotionAction :workspace-id="promotionWorkspace" :case-ids="Object.keys(selectedCases)" :requested-job-id="String(route.query.promotionJob || '')" @completed="vm.loadCases({ reset: true })" /></div>
      </div>
    </div>

    <div class="cc-list">
      <div v-if="vm.loading && vm.items.length === 0" class="cc-state">
        <Loader2 class="w-5 h-5 spin" />
        <span>{{ t('common.loading') }}</span>
      </div>

      <div v-else-if="vm.items.length === 0" class="cc-state">
        <BookMarked class="w-8 h-8" />
        <span>{{ t('case_center.empty') }}</span>
      </div>

      <div v-else class="cc-list-inner">
        <div v-for="item in vm.items" :key="item.id" class="cc-row" @click="handleOpenCase(item)">
          <input type="checkbox" :aria-label="`选择案例：${item.title}`" :title="item.status !== 'APPROVED' ? '只有评审入库的案例才能晋升' : '选择案例'" :checked="Boolean(selectedCases[item.id])" :disabled="item.status !== 'APPROVED' || !item.my_can_manage || Boolean(promotionWorkspace && promotionWorkspace !== item.workspace_id)" @click.stop @change="toggleCase(item.id, item.workspace_id)" />
          <div class="cc-row-main">
            <div class="cc-row-title">{{ item.title }}</div>
            <div class="cc-row-desc" v-if="item.problem_description">{{ item.problem_description }}</div>
            <div class="cc-row-meta">
              <CaseCategoryTag v-if="item.status !== 'APPROVED' || item.category !== 'TEMPORARY'" :category="item.category" />
              <CasePriorityTag :priority="item.priority" />
              <CaseStatusPill :status="item.status" />
              <span v-if="item.has_playbook" class="cc-promoted">已晋升规程</span>
              <span class="cc-row-source">{{ t('case_center.field.product_version') }}: {{ item.product_version || '-' }}</span>
              <span v-if="item.workspace_name" class="cc-row-source">{{ item.workspace_name }}</span>
              <span v-if="item.source_task_name" class="cc-row-source">{{ item.source_task_name }}</span>
              <span class="cc-row-creator">{{ item.creator_name || '-' }}</span>
            </div>
          </div>
          <div class="cc-row-side">
            <span class="cc-row-time">{{ new Date(item.updated_at || item.created_at).toLocaleString() }}</span>
            <span v-if="item.review_round > 1" class="cc-row-round">{{ t('case_center.review_round', { round: item.review_round }) }}</span>
          </div>
        </div>

        <div v-if="vm.hasMore" class="cc-load-more">
          <button class="btn-secondary" :disabled="vm.loading" @click="vm.loadMore()">
            <Loader2 v-if="vm.loading" :size="16" class="spin" />
            {{ t('common.load_more') }}
          </button>
        </div>
      </div>
    </div>

    <CaseFormDialog
      :visible="vm.formVisible"
      :saving="vm.formSaving"
      :model="vm.formModel"
      :is-edit="Boolean(vm.editingId)"
      @close="vm.closeForm()"
      @save="vm.saveForm()"
    />
    </template>
  </div>
</template>

<style scoped>
.cc-promotion { margin-left:auto }
.cc-promoted { color: #0369a1; background: #e0f2fe; border-radius: 6px; padding: 2px 6px; font-size: 12px; }
.cc-row input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  margin-top: 2px;
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
}

.cc-row input[type="checkbox"]:hover:not(:disabled) {
  border-color: #38bdf8;
  background-color: #f0f9ff;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}

.cc-row input[type="checkbox"]:checked {
  border-color: #0ea5e9;
  background-color: #0ea5e9;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M2.5 7L5.5 10L11.5 4' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  box-shadow: 0 2px 4px rgba(14, 165, 233, 0.25);
}

.cc-row input[type="checkbox"]:checked:hover:not(:disabled) {
  border-color: #0284c7;
  background-color: #0284c7;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.35);
}

.cc-row input[type="checkbox"]:focus-visible {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.22);
}

.cc-row input[type="checkbox"]:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  background-color: #f8fafc;
  border-color: #e2e8f0;
}
.case-center {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: none;
  width: 100%;
  margin: 0;
}

.case-center--embedded {
  padding: 0;
  max-width: none;
  margin: 0;
}

.cc-tabs-container {
  display: flex;
  align-items: center;
  margin-bottom: 4px;
}

.cc-tabs {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.3rem;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(12px);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.cc-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 38px;
  padding: 0.4rem 1.1rem;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: #64748b;
  font-family: inherit;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.cc-tab:hover {
  color: #0f172a;
  background: rgba(241, 245, 249, 0.8);
}

.cc-tab.active {
  color: #0284c7;
  background: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 100%);
  box-shadow: 0 1px 4px rgba(14, 165, 233, 0.18);
}

.cc-tab-badge {
  font-size: 0.75rem;
  font-weight: 700;
  padding: 0.1rem 0.5rem;
  border-radius: 9999px;
  background: rgba(2, 132, 199, 0.12);
  color: #0284c7;
}

.cc-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.cc-header-embedded {
  justify-content: flex-end;
}

.cc-title-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.cc-icon {
  color: var(--color-primary-600);
  margin-top: 2px;
}

.cc-title {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--color-primary-900);
}

.cc-subtitle {
  margin: 2px 0 0;
  font-size: 0.85rem;
  color: #64748b;
}

.cc-actions {
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
  width: 220px;
  background: transparent;
  font-family: inherit;
}

.cc-filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.filter-selects {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-select {
  width: 130px;
}

.workspace-filter-select {
  width: 160px;
}

.refresh-btn {
  width: 42px;
  height: 42px;
  padding: 0;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  color: #64748b;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.refresh-btn:hover {
  color: var(--color-primary-600);
  border-color: var(--color-primary-300);
}

.cc-list {
  display: flex;
  flex-direction: column;
}

.cc-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #94a3b8;
  padding: 60px 0;
  font-size: 0.9rem;
}

.cc-list-inner {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cc-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.25s;
}

.cc-row:hover {
  border-color: rgba(14, 165, 233, 0.4);
  box-shadow: 0 8px 16px -8px rgba(14, 165, 233, 0.15);
  transform: translateY(-1px);
}

.cc-row-main {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cc-row-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e293b;
}

.cc-row-desc {
  font-size: 0.8rem;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.cc-row-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.cc-row-source {
  font-size: 0.72rem;
  color: #64748b;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  padding: 1px 8px;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cc-row-creator {
  font-size: 0.72rem;
  color: #94a3b8;
}

.cc-row-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  flex-shrink: 0;
}

.cc-row-time {
  font-size: 0.72rem;
  color: #94a3b8;
}

.cc-row-round {
  font-size: 0.7rem;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 999px;
  padding: 0 8px;
}

.cc-load-more {
  display: flex;
  justify-content: center;
  padding: 12px 0;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
