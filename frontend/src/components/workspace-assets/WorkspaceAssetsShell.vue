<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import { useWorkspaceAssets } from '@/composables/useWorkspaceAssets'
import RequirementsWorkbench from '@/components/workspace-assets/requirements/RequirementsWorkbench.vue'
import TaskTableWorkbench from '@/components/workspace-assets/tasks/TaskTableWorkbench.vue'
import WorkspaceAssetsUnderConstruction from '@/components/workspace-assets/WorkspaceAssetsUnderConstruction.vue'
import {
  Database,
  FileText,
  GitBranch,
  MessageSquare,
} from '@/components/icons'

type WorkspaceAssetsSection = 'requirements' | 'tasks' | 'traceability' | 'knowledgeBase'

type NavItem = {
  key: WorkspaceAssetsSection
  label: string
  description: string
  to: string
  icon: Component
}

const props = defineProps<{
  section: WorkspaceAssetsSection
}>()

const route = useRoute()
const { t } = useI18n()
const {
  loading,
  requirements,
  tasks,
  loadRequirements,
  loadTasks,
} = useWorkspaceAssets()

const wsId = computed(() => String(route.params.wsId || ''))

const navItems = computed<NavItem[]>(() => [
  {
    key: 'requirements',
    label: t('workspace_assets.nav.requirements'),
    description: t('workspace_assets.nav_desc.requirements'),
    to: `/workspaces/${wsId.value}/assets/requirements`,
    icon: FileText,
  },
  {
    key: 'tasks',
    label: t('workspace_assets.nav.tasks'),
    description: t('workspace_assets.nav_desc.tasks'),
    to: `/workspaces/${wsId.value}/assets/tasks`,
    icon: MessageSquare,
  },
  {
    key: 'traceability',
    label: t('workspace_assets.nav.traceability'),
    description: t('workspace_assets.nav_desc.traceability'),
    to: `/workspaces/${wsId.value}/assets/traceability`,
    icon: GitBranch,
  },
  {
    key: 'knowledgeBase',
    label: t('workspace_assets.nav.knowledge_base'),
    description: t('workspace_assets.nav_desc.knowledgeBase'),
    to: `/workspaces/${wsId.value}/assets/knowledge-base`,
    icon: Database,
  },
])

const requirementItems = computed(() => requirements.value?.items ?? [])
const taskItems = computed(() => tasks.value?.items ?? [])

watch(
  [wsId, () => props.section],
  async ([currentWsId, currentSection]) => {
    if (!currentWsId) {
      return
    }
    if (currentSection === 'requirements') {
      await loadRequirements(currentWsId)
      return
    }
    if (currentSection === 'tasks') {
      await loadTasks(currentWsId)
      return
    }
  },
  { immediate: true },
)

</script>

<template>
  <div class="workspace-assets">

    <header class="assets-header">
      <nav class="assets-top-nav glass-panel" :aria-label="t('workspace_assets.nav_label')">
        <RouterLink
          v-for="item in navItems"
          :key="item.key"
          class="nav-tab"
          :class="{ 'is-active': item.key === section }"
          :to="item.to"
        >
          <div class="icon-glow-wrapper">
            <component :is="item.icon" class="nav-icon" />
          </div>
          <strong>{{ item.label }}</strong>
        </RouterLink>
      </nav>
    </header>

    <main class="assets-content">

        <section v-if="section === 'requirements'" class="structured-page">
          <RequirementsWorkbench
            :workspace-id="wsId"
            :requirements="requirementItems"
            :loading="loading"
            @refresh="loadRequirements(wsId)"
          />
        </section>

        <section v-else-if="section === 'tasks'" class="structured-page">
            <TaskTableWorkbench
              :items="taskItems"
              :total="tasks?.total || 0"
              :page="tasks?.page || 1"
              :page-size="tasks?.page_size || 20"
              :stats="tasks?.stats || null"
              :loading="loading"
              @query-change="(query) => loadTasks(wsId, query)"
              @open="(task) => $router.push(`/workspaces/${wsId}/assets/tasks/${task.id}`)"
            />
        </section>

        <section v-else-if="section === 'traceability'" class="structured-page">
          <WorkspaceAssetsUnderConstruction
            :badge="t('workspace_assets.under_construction.badge')"
            :title="t('workspace_assets.under_construction.traceability_title')"
            :description="t('workspace_assets.under_construction.traceability_body')"
          />
        </section>

        <section v-else class="structured-page">
          <WorkspaceAssetsUnderConstruction
            :badge="t('workspace_assets.under_construction.badge')"
            :title="t('workspace_assets.under_construction.knowledge_base_title')"
            :description="t('workspace_assets.under_construction.knowledge_base_body')"
          />
        </section>
      </main>
    </div>
  </template><style scoped>
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');

.workspace-assets {
  min-height: 100%;
  padding: 32px;
  display: flex;
  flex-direction: column;
  gap: 32px;
  background-color: #ffffff;
  background-image:
    radial-gradient(circle at 10% 20%, #eff6ff 0%, transparent 45%),
    radial-gradient(circle at 90% 80%, #f0f9ff 0%, transparent 45%);
  color: #1e3a8a;
  font-family: 'Open Sans', sans-serif;
  animation: fade-in 0.8s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Header & Top Nav */
.assets-header {
  width: 100%;
}

.assets-top-nav {
  display: flex;
  gap: 0.75rem;
  padding: 0.5rem !important;
  border-radius: 1.25rem !important;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(226, 232, 240, 0.8);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.nav-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 0.625rem 1rem;
  border-radius: 0.875rem;
  text-decoration: none;
  color: #64748b;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  border: 1px solid transparent;
}

.nav-tab:hover {
  background: white;
  transform: translateY(-4px);
  border-color: rgba(14, 165, 233, 0.2);
  box-shadow: 0 10px 20px -5px rgba(14, 165, 233, 0.1);
  color: #0ea5e9;
}

.nav-tab.is-active {
  background: white;
  border-color: #0ea5e9;
  color: #1e3a8a;
  box-shadow: 0 15px 25px -5px rgba(14, 165, 233, 0.15);
}

.icon-glow-wrapper {
  width: 32px;
  height: 32px;
  background: #f8fafc;
  color: #94a3b8;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
  flex-shrink: 0;
}

.nav-icon {
  width: 16px;
  height: 16px;
}

.nav-tab:hover .icon-glow-wrapper {
  background: #f0f9ff;
  color: #0ea5e9;
  transform: scale(1.05);
}

.nav-tab.is-active .icon-glow-wrapper {
  background: linear-gradient(135deg, #0ea5e9, #3b82f6);
  color: white;
  box-shadow: 0 8px 20px rgba(14, 165, 233, 0.4);
}

.nav-label-group {
  display: flex;
  flex-direction: column;
}

.nav-tab strong {
  display: block;
  font-size: 0.875rem;
  font-weight: 700;
  font-family: 'Poppins', sans-serif;
  letter-spacing: -0.01em;
}

.nav-tab small {
  display: none;
}

/* Content Area */
.assets-content {
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.structured-page {
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.glass-panel {
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-radius: 2rem;
  padding: 2.5rem;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.05), 0 10px 10px -5px rgba(0, 0, 0, 0.02);
}

/* Summary Strip */
.summary-strip {
  display: flex;
  justify-content: space-around;
  padding: 1.25rem 2rem; /* Reduced padding from 3rem */
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 1rem; /* Adjust radius since padding is smaller */
}

.summary-item {
  text-align: center;
  flex: 1;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.25rem; /* Tighter gap between label and value */
}

.summary-item:not(:last-child)::after {
  content: '';
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 1px;
  height: 24px; /* Reduced from 40px */
  background-color: #e2e8f0;
}

.summary-label {
  display: block;
  font-weight: 600;
  color: #64748b;
  font-size: 0.8125rem; /* Reduced slightly */
  margin-bottom: 0; /* Let flex gap handle spacing */
}

.summary-value {
  font-family: 'Poppins', sans-serif;
  font-size: 1.75rem; /* Reduced from 2.25rem */
  font-weight: 800;
  background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  display: block;
  line-height: 1;
}

/* Two Column Layouts */
.two-column-workspace,
.selected-view-container {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 32px;
}

.list-container,
.view-frame {
  background: white;
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 2rem;
  padding: 2.5rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.container-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2rem;
}

.container-head h3 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.5rem;
  font-weight: 800;
  margin: 0;
  letter-spacing: -0.02em;
}

.container-head span {
  background: #f0f9ff;
  color: #0ea5e9;
  padding: 0.5rem 1rem;
  border-radius: 999px;
  font-size: 0.8125rem;
  font-weight: 700;
  border: 1px solid rgba(14, 165, 233, 0.1);
}

.data-row {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 1.25rem;
  padding: 1.5rem;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
  text-decoration: none;
  display: block;
}

.data-row:hover {
  background: white;
  transform: translateY(-6px);
  border-color: #0ea5e9;
  box-shadow: 0 20px 25px -5px rgba(14, 165, 233, 0.1), 0 10px 10px -5px rgba(14, 165, 233, 0.04);
}

.data-row strong {
  display: block;
  font-size: 1.125rem;
  color: #0f172a;
  margin-bottom: 0.5rem;
  font-family: 'Poppins', sans-serif;
  font-weight: 700;
}

.data-row small {
  color: #64748b;
  font-size: 0.875rem;
  font-weight: 500;
}

.data-row span {
  display: block;
  margin-top: 1rem;
  font-size: 0.8125rem;
  color: #94a3b8;
  font-family: 'Fira Code', monospace;
  background: #f1f5f9;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  width: fit-content;
}

/* Empty State */
.empty-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  text-align: center;
  background: #f8fafc;
  border: 2px dashed #e2e8f0;
  border-radius: 1.5rem;
  color: #94a3b8;
}

.empty-icon {
  width: 48px;
  height: 48px;
  margin-bottom: 1.5rem;
  opacity: 0.5;
}

/* Responsive */
@media (max-width: 1200px) {
  .assets-top-nav {
    flex-wrap: wrap;
  }
  .nav-tab {
    flex: 1 1 calc(50% - 1.5rem);
  }
}

@media (max-width: 1024px) {
  .two-column-workspace,
  .selected-view-container {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .nav-tab {
    flex: 1 1 100%;
  }
}
</style>
