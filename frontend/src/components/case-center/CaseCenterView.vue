<script setup lang="ts">
import { computed, onMounted, onUnmounted, proxyRefs, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Plus, BookMarked, Workflow } from '@/components/icons'
import { useCaseCenter } from '@/composables/useCaseCenter'
import CaseFormDialog from './CaseFormDialog.vue'
import PlaybookLibrary from './PlaybookLibrary.vue'
import CasePromotionAction from './CasePromotionAction.vue'
import CaseListFilters from './CaseListFilters.vue'
import LibraryPagination from './LibraryPagination.vue'
import CaseList from './CaseList.vue'
import type { CaseListFilters as CaseFilters, CaseListItem, CaseSort } from '@/types/caseCenter'

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

const hasActiveFilters = computed(() => Object.entries(vm.filters).some(([key, value]) => !key.startsWith('sort_') && value && value !== 'ALL'))
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

const togglePage = (items: CaseListItem[]) => {
  const remove = items.every(item => Boolean(selectedCases.value[item.id]))
  for (const item of items) {
    if (remove) delete selectedCases.value[item.id]
    else selectedCases.value[item.id] = item.workspace_id
  }
}

const applyFilters = (filters: CaseFilters) => {
  Object.assign(vm.filters, filters)
  void vm.applyFilters()
}

const applySort = (sort: CaseSort) => {
  Object.assign(vm.filters, sort)
  void vm.applyFilters()
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
        <button class="btn-primary flex items-center gap-2" @click="vm.openCreateForm()">
          <Plus :size="16" /> {{ t('case_center.create_button') }}
        </button>
        <CasePromotionAction :workspace-id="promotionWorkspace" :case-ids="Object.keys(selectedCases)" :requested-job-id="String(route.query.promotionJob || '')" @completed="vm.loadCases({ reset: true })" />
      </div>
    </div>

    <CaseListFilters
      :model-value="vm.filters"
      :workspace-id="activeWorkspaceId"
      :workspace-options="workspaceOptions"
      :loading="vm.loading"
      @apply="applyFilters"
      @update:workspace-id="emit('update:workspaceId', $event)"
      @refresh="vm.loadCases({ reset: false })"
    />

    <p v-if="vm.listError" class="cc-error" role="alert">{{ vm.listError }}</p>

    <div class="cc-list-summary" role="status">
      <span>共 {{ vm.total }} 个案例</span>
      <template v-if="Object.keys(selectedCases).length">
        <span class="cc-selection-summary">已选 {{ Object.keys(selectedCases).length }} 项</span>
        <button type="button" class="cc-clear-selection" @click="selectedCases = {}">清除选择</button>
      </template>
    </div>

    <CaseList
      :items="vm.items"
      :loading="vm.loading"
      :error="vm.listError"
      :filtered="hasActiveFilters"
      :selected-cases="selectedCases"
      :promotion-workspace="promotionWorkspace"
      :sort-by="vm.filters.sort_by"
      :sort-order="vm.filters.sort_order"
      @open="handleOpenCase"
      @toggle="toggleCase"
      @toggle-page="togglePage"
      @sort="applySort"
    />

    <LibraryPagination
      class="cc-pagination"
      :total="vm.total"
      :page="vm.page"
      :page-count="vm.pageCount"
      :page-size="vm.pageSize"
      :loading="vm.loading"
      label="案例分页"
      @change="vm.changePage"
      @update:page-size="vm.changePageSize"
    />

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
.cc-list-summary { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; color: #64748b; font-size: 0.8125rem; }
.cc-selection-summary, .cc-clear-selection { color: #0284c7; }
.cc-clear-selection { padding: 0; border: none; background: none; font: inherit; cursor: pointer; }
.cc-error { margin: 0; padding: 10px 14px; color: #dc2626; background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; font-size: 0.85rem; }
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

</style>
