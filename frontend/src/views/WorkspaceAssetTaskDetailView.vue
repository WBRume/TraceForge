<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, shallowRef, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import {
  ArrowLeft,
  Database,
  FileText,
  GitBranch,
  History,
  ShieldCheck,
  TerminalSquare,
  LayoutGrid,
} from 'lucide-vue-next'
import TaskDetailHeader from '@/components/workspace-assets/task-detail/TaskDetailHeader.vue'
import TaskFilePanel from '@/components/workspace-assets/task-detail/TaskFilePanel.vue'
import { useTaskDetailSections } from '@/composables/useTaskDetailSections'
import type { TaskWorkbenchSectionKey } from '@/types/workspaceAssets'

const TaskFinalWorkflowEntryPanel = defineAsyncComponent(() => import('@/components/workspace-assets/task-final-workflow/TaskFinalWorkflowEntryPanel.vue'))
const HumanDeltaPanel = defineAsyncComponent(() => import('@/components/workspace-assets/task-detail/HumanDeltaPanel.vue'))
const EvidencePanel = defineAsyncComponent(() => import('@/components/workspace-assets/task-detail/EvidencePanel.vue'))
const DecisionPanel = defineAsyncComponent(() => import('@/components/workspace-assets/task-detail/DecisionPanel.vue'))
const TaskProcessAuditPanel = defineAsyncComponent(() => import('@/components/workspace-assets/task-detail/TaskProcessAuditPanel.vue'))

type WorkbenchSection = {
  key: TaskWorkbenchSectionKey
  title: string
  body: string
  icon: Component
}

const route = useRoute()
const { t } = useI18n()

const {
  summary,
  summaryLoading,
  summaryError,
  sections: sectionStates,
  loadSummary,
  loadSection,
  refreshSummary,
  invalidateSection,
} = useTaskDetailSections()

const wsId = computed(() => String(route.params.wsId || ''))
const taskId = computed(() => String(route.params.taskId || ''))
const backToTasks = computed(() => `/ws/${wsId.value}/assets/tasks`)

const sectionKeys: TaskWorkbenchSectionKey[] = [
  'taskFile',
  'finalWorkflow',
  'humanDelta',
  'evidence',
  'decisions',
  'processAudit',
]

const normalizeSection = (value: unknown): TaskWorkbenchSectionKey | null => {
  const normalized = String(value || '').replace(/[-_](\w)/g, (_, char: string) => char.toUpperCase())
  return sectionKeys.includes(normalized as TaskWorkbenchSectionKey) ? normalized as TaskWorkbenchSectionKey : null
}

const activeSection = shallowRef<TaskWorkbenchSectionKey>(normalizeSection(route.query.section) || 'taskFile')

const sections = computed<WorkbenchSection[]>(() => [
  {
    key: 'taskFile',
    title: t('workspace_assets.task_detail.workbench.nav.task_file'),
    body: t('workspace_assets.task_detail.workbench.nav.task_file_body'),
    icon: FileText,
  },
  {
    key: 'finalWorkflow',
    title: t('workspace_assets.task_detail.workbench.nav.final_workflow'),
    body: t('workspace_assets.task_detail.workbench.nav.final_workflow_body'),
    icon: ShieldCheck,
  },
  {
    key: 'humanDelta',
    title: t('workspace_assets.task_detail.workbench.nav.human_delta'),
    body: t('workspace_assets.task_detail.workbench.nav.human_delta_body'),
    icon: TerminalSquare,
  },
  {
    key: 'evidence',
    title: t('workspace_assets.task_detail.workbench.nav.evidence'),
    body: t('workspace_assets.task_detail.workbench.nav.evidence_body'),
    icon: Database,
  },
  {
    key: 'decisions',
    title: t('workspace_assets.task_detail.workbench.nav.decisions'),
    body: t('workspace_assets.task_detail.workbench.nav.decisions_body'),
    icon: GitBranch,
  },
  {
    key: 'processAudit',
    title: t('workspace_assets.task_detail.workbench.nav.process_audit'),
    body: t('workspace_assets.task_detail.workbench.nav.process_audit_body'),
    icon: History,
  },
])

const crossSectionDeps: Partial<Record<TaskWorkbenchSectionKey, TaskWorkbenchSectionKey[]>> = {
  humanDelta: [],
  evidence: ['humanDelta'],
  decisions: ['humanDelta', 'evidence'],
}

async function handleSectionChange(key: TaskWorkbenchSectionKey) {
  activeSection.value = key
  await loadSection(wsId.value, taskId.value, key, { force: true })
  const deps = crossSectionDeps[key]
  if (deps) {
    await Promise.all(
      deps
        .map((dep) => loadSection(wsId.value, taskId.value, dep, { force: true })),
    )
  }
}

async function handleMutated(sectionKey: TaskWorkbenchSectionKey) {
  await refreshSummary(wsId.value, taskId.value)
  invalidateSection(sectionKey)
  await loadSection(wsId.value, taskId.value, sectionKey, { force: true, page: 1 })
}

async function handlePageChange(sectionKey: TaskWorkbenchSectionKey, payload: { page: number; pageSize: number }) {
  await loadSection(wsId.value, taskId.value, sectionKey, { force: true, page: payload.page, pageSize: payload.pageSize })
}

watch(
  () => route.query.section,
  (section) => {
    const next = normalizeSection(section)
    if (next) handleSectionChange(next)
  },
)

watch(
  [wsId, taskId],
  async ([currentWsId, currentTaskId]) => {
    if (!currentWsId || !currentTaskId) return
    await loadSummary(currentWsId, currentTaskId)
    await loadSection(currentWsId, currentTaskId, 'taskFile')
  },
  { immediate: true },
)

onMounted(() => {
  const initialSection = normalizeSection(route.query.section)
  if (initialSection && initialSection !== 'taskFile') {
    handleSectionChange(initialSection)
  }
})
</script>

<template>
  <div class="task-detail-view">
    <div class="view-header-bar">
      <RouterLink class="back-link" :to="backToTasks">
        <ArrowLeft class="back-icon" />
        <span>{{ t('workspace_assets.task_detail.back_to_tasks') }}</span>
      </RouterLink>
    </div>

    <TaskDetailHeader :detail="summary" :workspace-id="wsId" :task-id="taskId" />

    <el-alert
      v-if="summaryError"
      type="error"
      :closable="false"
      :title="summaryError"
      class="view-alert"
    />

    <div v-loading="summaryLoading" class="task-workbench">
      <nav class="workbench-nav">
        <div class="nav-header">
          <LayoutGrid class="nav-header-icon" />
          <span>{{ t('workspace_assets.task_detail.workbench.nav_title') }}</span>
        </div>
        <div class="nav-items-grid">
          <button
            v-for="section in sections"
            :key="section.key"
            type="button"
            class="nav-item"
            :class="{ 'is-active': activeSection === section.key }"
            @click="handleSectionChange(section.key)"
          >
            <div class="nav-item-icon-box">
              <component :is="section.icon" class="nav-item-icon" />
            </div>
            <div class="nav-item-text">
              <span class="nav-item-title">{{ section.title }}</span>
              <span class="nav-item-body">{{ section.body }}</span>
            </div>
          </button>
        </div>
      </nav>

      <main class="workbench-content">
        <Transition name="fade-panel" mode="out-in">
          <div :key="activeSection" class="panel-container">
            <div v-if="sectionStates[activeSection]?.loading" class="section-loading">
              <span>Loading...</span>
            </div>
            <div v-else-if="sectionStates[activeSection]?.error" class="section-error">
              <el-alert type="error" :closable="false" :title="sectionStates[activeSection].error" />
            </div>
            <template v-else>
              <TaskFilePanel
                v-if="activeSection === 'taskFile'"
                :files="sectionStates.taskFile.data ?? []"
                :workspace-id="wsId"
                :task-id="taskId"
                :total="sectionStates.taskFile.total"
                :page="sectionStates.taskFile.page"
                :page-size="sectionStates.taskFile.pageSize"
                @page-change="(p) => handlePageChange('taskFile', p)"
              />
              <TaskFinalWorkflowEntryPanel
                v-else-if="activeSection === 'finalWorkflow'"
                :workspace-id="wsId"
                :task-id="taskId"
              />
              <HumanDeltaPanel
                v-else-if="activeSection === 'humanDelta'"
                :deltas="sectionStates.humanDelta.data ?? []"
                :workspace-id="wsId"
                :task-id="taskId"
                :total="sectionStates.humanDelta.total"
                :page="sectionStates.humanDelta.page"
                :page-size="sectionStates.humanDelta.pageSize"
                @mutated="handleMutated('humanDelta')"
                @page-change="(p) => handlePageChange('humanDelta', p)"
              />
              <EvidencePanel
                v-else-if="activeSection === 'evidence'"
                :evidence="sectionStates.evidence.data ?? []"
                :workspace-id="wsId"
                :task-id="taskId"
                :task-status="summary?.task?.status"
                :total="sectionStates.evidence.total"
                :page="sectionStates.evidence.page"
                :page-size="sectionStates.evidence.pageSize"
                @mutated="handleMutated('evidence')"
                @page-change="(p) => handlePageChange('evidence', p)"
              />
              <DecisionPanel
                v-else-if="activeSection === 'decisions'"
                :decisions="sectionStates.decisions.data ?? []"
                :workspace-id="wsId"
                :task-id="taskId"
                :requirement-links="summary?.requirement_links"
                :human-deltas="sectionStates.humanDelta.data ?? []"
                :evidence="sectionStates.evidence.data ?? []"
                :total="sectionStates.decisions.total"
                :page="sectionStates.decisions.page"
                :page-size="sectionStates.decisions.pageSize"
                @mutated="handleMutated('decisions')"
                @page-change="(p) => handlePageChange('decisions', p)"
              />
              <TaskProcessAuditPanel
                v-else-if="activeSection === 'processAudit'"
                :audit-logs="sectionStates.processAudit.data ?? []"
                :workspace-id="wsId"
                :task-id="taskId"
              />
            </template>
          </div>
        </Transition>
      </main>
    </div>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');

.task-detail-view {
  min-height: 100vh;
  padding: 32px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  background-color: #f8fafc;
  background-image:
    radial-gradient(circle at 0% 0%, #eff6ff 0%, transparent 40%),
    radial-gradient(circle at 100% 100%, #f0f9ff 0%, transparent 40%);
  color: #0f172a;
  font-family: 'Open Sans', sans-serif;
}

.view-header-bar {
  display: flex;
  align-items: center;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  color: #64748b;
  font-size: 0.875rem;
  font-weight: 600;
  text-decoration: none;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.back-link:hover {
  color: #0ea5e9;
  border-color: #0ea5e966;
  background: #f0f9ff;
  transform: translateX(-4px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.1);
}

.back-icon {
  width: 18px;
  height: 18px;
}

.view-alert {
  border-radius: 12px;
}

.task-workbench {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 24px;
  min-height: 600px;
}

.workbench-nav {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 20px;
  height: fit-content;
  position: sticky;
  top: 32px;
}

.nav-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 8px 8px;
  border-bottom: 1px solid #f1f5f9;
  color: #64748b;
  font-size: 0.75rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.nav-header-icon {
  width: 16px;
  height: 16px;
}

.nav-items-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 12px;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.8);
  border-color: #f1f5f9;
}

.nav-item.is-active {
  background: white;
  border-color: #0ea5e933;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.08);
}

.nav-item-icon-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  background: #f8fafc;
  border-radius: 10px;
  color: #64748b;
  transition: all 0.2s;
}

.nav-item.is-active .nav-item-icon-box {
  background: #0ea5e9;
  color: white;
}

.nav-item-icon {
  width: 18px;
  height: 18px;
}

.nav-item-text {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.nav-item-title {
  color: #1e293b;
  font-size: 0.875rem;
  font-weight: 600;
}

.nav-item.is-active .nav-item-title {
  color: #0ea5e9;
}

.nav-item-body {
  color: #94a3b8;
  font-size: 0.75rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.workbench-content {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 20px;
  padding: 32px;
  min-width: 0;
}

.panel-container {
  height: 100%;
}

.section-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 3rem;
  color: #94a3b8;
  font-size: 0.875rem;
}

.section-error {
  padding: 1rem 0;
}

/* Transitions */
.fade-panel-enter-active,
.fade-panel-leave-active {
  transition: all 0.3s ease;
}

.fade-panel-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.fade-panel-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

@media (max-width: 1200px) {
  .task-workbench {
    grid-template-columns: 1fr;
  }

  .workbench-nav {
    position: static;
  }
}

@media (max-width: 768px) {
  .task-detail-view {
    padding: 16px;
  }

  .workbench-content {
    padding: 20px;
  }
}
</style>
