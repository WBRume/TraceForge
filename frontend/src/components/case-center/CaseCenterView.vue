<script setup lang="ts">
import { onMounted, proxyRefs, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Search, Plus, Loader2, BookMarked, RefreshCw } from 'lucide-vue-next'
import { useCaseCenter } from '@/composables/useCaseCenter'
import CaseStatusPill from './CaseStatusPill.vue'
import CaseCategoryTag from './CaseCategoryTag.vue'
import CasePriorityTag from './CasePriorityTag.vue'
import CaseFormDialog from './CaseFormDialog.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const vm = proxyRefs(useCaseCenter())

const searchInput = ref('')

const categoryTabs = [
  { label: 'ALL', value: 'ALL' },
  { label: 'PUBLIC', value: 'PUBLIC' },
  { label: 'PRODUCT', value: 'PRODUCT' },
  { label: 'SITE', value: 'SITE' },
  { label: 'TEMPORARY', value: 'TEMPORARY' },
]

const statusOptions = ['ALL', 'DRAFT', 'PENDING_REVIEW', 'IN_REVIEW', 'APPROVED', 'REJECTED']
const priorityOptions = ['ALL', 'P0', 'P1', 'P2', 'P3']

const runSearch = () => {
  vm.keyword = searchInput.value
  vm.applyFilters()
}

const selectCategory = (value: string) => {
  vm.category = value
  vm.applyFilters()
}

const goToReport = (caseId: string) => {
  router.push({
    name: 'workspaceCaseDetail',
    params: { wsId: String(route.params.wsId || ''), caseId },
  })
}

const handleOpenCase = (caseId: string) => {
  goToReport(caseId)
}

// 兼容旧的 ?case= 深链：直接跳转到独立报告页
const redirectQueryCase = () => {
  const caseId = String(route.query.case || '')
  if (caseId) {
    router.replace({
      name: 'workspaceCaseDetail',
      params: { wsId: String(route.params.wsId || ''), caseId },
    })
  }
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
</script>

<template>
  <div class="case-center">
    <div class="cc-header">
      <div class="cc-title-row">
        <BookMarked class="w-6 h-6 cc-icon" />
        <div>
          <h2 class="cc-title">{{ t('case_center.title') }}</h2>
          <p class="cc-subtitle">{{ t('case_center.subtitle') }}</p>
        </div>
      </div>
      <div class="cc-actions">
        <div class="search-box">
          <Search class="w-4 h-4 search-icon" />
          <input
            v-model="searchInput"
            type="text"
            class="search-input"
            :placeholder="t('case_center.search_placeholder')"
            @keyup.enter="runSearch"
          />
          <button class="btn-primary search-btn" @click="runSearch">{{ t('case_center.search') }}</button>
        </div>
        <button class="btn-primary flex items-center gap-2" @click="vm.openCreateForm()">
          <Plus class="w-4 h-4" /> {{ t('case_center.create_button') }}
        </button>
      </div>
    </div>

    <div class="cc-filter-bar">
      <div class="category-tabs">
        <button
          v-for="tab in categoryTabs"
          :key="tab.value"
          class="category-tab"
          :class="{ active: vm.category === tab.value }"
          @click="selectCategory(tab.value)"
        >
          {{ tab.value === 'ALL' ? t('case_center.filter_all') : t(`case_center.category.${tab.value}`) }}
        </button>
      </div>
      <div class="filter-selects">
        <el-select v-model="vm.status" size="small" class="filter-select" @change="vm.applyFilters()">
          <el-option v-for="s in statusOptions" :key="s" :label="s === 'ALL' ? t('case_center.status_all') : t(`case_center.status.${s}`)" :value="s" />
        </el-select>
        <el-select v-model="vm.priority" size="small" class="filter-select" @change="vm.applyFilters()">
          <el-option v-for="p in priorityOptions" :key="p" :label="p === 'ALL' ? t('case_center.priority_all') : p" :value="p" />
        </el-select>
        <button class="icon-btn refresh-btn" :title="t('common.refresh')" @click="vm.applyFilters()">
          <RefreshCw class="w-4 h-4" />
        </button>
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
        <div v-for="item in vm.items" :key="item.id" class="cc-row" @click="handleOpenCase(item.id)">
          <div class="cc-row-main">
            <div class="cc-row-title">{{ item.title }}</div>
            <div class="cc-row-desc" v-if="item.problem_description">{{ item.problem_description }}</div>
            <div class="cc-row-meta">
              <CaseCategoryTag :category="item.category" />
              <CasePriorityTag :priority="item.priority" />
              <CaseStatusPill :status="item.status" />
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
            <Loader2 v-if="vm.loading" class="w-4 h-4 spin" />
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
  </div>
</template>

<style scoped>
.case-center {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
}

.cc-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
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
  padding: 4px 4px 4px 12px;
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

.search-btn {
  padding: 6px 14px;
  font-size: 0.8rem;
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

.category-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.category-tab {
  border: none;
  background: transparent;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.category-tab:hover {
  color: var(--color-primary-600);
  background: var(--color-primary-50);
}

.category-tab.active {
  color: var(--color-primary-600);
  background: var(--color-primary-100);
}

.filter-selects {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-select {
  width: 130px;
}

.refresh-btn {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  color: #64748b;
  cursor: pointer;
  padding: 6px;
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
