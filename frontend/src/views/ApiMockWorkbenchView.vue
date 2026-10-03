<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { formatApiError } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'
import ApiMockEndpointCatalog from '@/components/api-mock/ApiMockEndpointCatalog.vue'
import ApiMockEndpointWorkspace from '@/components/api-mock/ApiMockEndpointWorkspace.vue'
import ApiMockGlobalEntityDrawer from '@/components/api-mock/ApiMockGlobalEntityDrawer.vue'
import ApiMockTaskBar from '@/components/api-mock/ApiMockTaskBar.vue'
import ApiMockConfigDrawer from '@/components/api-mock/ApiMockConfigDrawer.vue'
import ApiMockTaskPickerPanel from '@/components/api-mock/ApiMockTaskPickerPanel.vue'
import ShortcutHelpModal from '@/components/api-mock/ShortcutHelpModal.vue'
import { useWorkspaceContext } from '@/components/api-mock/workbench/useWorkspaceContext'
import { useWorkbenchNotifications } from '@/components/api-mock/workbench/notifications'
import { useProjectContext } from '@/components/api-mock/workbench/useProjectContext'
import { useProjectJobs } from '@/components/api-mock/workbench/useProjectJobs'
import { useProjectCollaboration } from '@/components/api-mock/workbench/useProjectCollaboration'
import { useProjectSources } from '@/components/api-mock/workbench/useProjectSources'
import { useProjectEditing } from '@/components/api-mock/workbench/useProjectEditing'
import type { ProjectContext } from '@/components/api-mock/workbench/useProjectContext'

const route = useRoute()
const { t } = useI18n()
const authStore = useAuthStore()
const wsId = computed(() => String(route.params.wsId || ''))
const selectedTaskId = ref('')
const notifications = useWorkbenchNotifications()
const workspace = useWorkspaceContext(wsId)
const context = useProjectContext(wsId, selectedTaskId, notifications)
const jobs = useProjectJobs(context, notifications)
const refreshProjectContext: ProjectContext['refreshProjectContext'] = async (options) => {
  const version = context.contextVersion.value
  await context.refreshProjectContext(options)
  if (version === context.contextVersion.value) await jobs.loadActiveJobs()
}
const collaboration = useProjectCollaboration(context, notifications, jobs, workspace, refreshProjectContext)
const sources = useProjectSources(context, notifications, jobs, refreshProjectContext)
const editing = useProjectEditing(context, notifications, jobs, collaboration, refreshProjectContext)
const { tasks, permissionsReady, pageError, canView, canManage, canPublish, loadPermissions, loadWorkspaceMembers, loadTasks } = workspace
const { project, sourceVersions, endpoints, entities, mockCases, selectedEndpointId, selectedMockCaseId, documentData, documentLoading, endpointKeyword, contextVersion, selectedEndpoint, currentSourceLabel, resetTaskContext, loadMockCases } = context
const { activeJob, activeAutoMockJob, isAutoMockRunning, isCurrentEndpointAutoMockLocked, isProjectSwaggerMutationLocked } = jobs
const { notifyError, notifyProjectSwaggerLocked } = notifications
const { collabConnected, onlineUsers, connectCollab, closeSocket, sendCollabEvent } = collaboration
const { syncBusy, importBusy, cancelJobBusy, autoMockStartBusy, onSync, onImportSwagger, onStartAutoMock, onCancelActiveJob, onActivateSource, onUpdateProxy } = sources
const { savingEndpoint, savingDocument, savingCase, deletingCase, onSaveEndpoint, onSaveDocument, onCreateCase, onSaveCase, onDeleteCase, onCreateEntity, onUpdateEntity, onDeleteEntity } = editing
const selectedTask = computed(() => tasks.value.find(item => item.id === selectedTaskId.value) || null)
const canManageSwagger = computed(() => canManage.value && !isProjectSwaggerMutationLocked.value)
const endpointCatalogRef = ref<InstanceType<typeof ApiMockEndpointCatalog> | null>(null)

const workspaceRef = ref<InstanceType<typeof ApiMockEndpointWorkspace> | null>(null)

const showConfigDrawer = ref(false)

const showGlobalEntityDrawer = ref(false)

const globalEntityDrawerRef = ref<InstanceType<typeof ApiMockGlobalEntityDrawer> | null>(null)

const configDrawerMode = ref<'sync' | 'versions' | 'proxy' | 'import'>('sync')

const showShortcuts = ref(false)

const showSideTaskPicker = ref(false)

const handleTaskPicked = (taskId: string) => {
  selectedTaskId.value = taskId
  showSideTaskPicker.value = false
}

const handleSelectEndpoint = async (endpointId: string) => {
  selectedEndpointId.value = endpointId
  selectedMockCaseId.value = ''
  await loadMockCases()
  sendCollabEvent('draft', { endpoint_id: endpointId })
}

const openGlobalEntityDrawer = () => {
  if (!canManageSwagger.value) {
    notifyProjectSwaggerLocked()
    return
  }
  showGlobalEntityDrawer.value = true
  setTimeout(() => {
    globalEntityDrawerRef.value?.openCreateForm()
  }, 100)
}

const onShortcuts = (event: KeyboardEvent) => {
  const ctrlOrMeta = event.ctrlKey || event.metaKey
  const key = event.key.toLowerCase()
  if (key === '?' && !ctrlOrMeta) {
    event.preventDefault()
    showShortcuts.value = true
    return
  }
  if (ctrlOrMeta && key === 'k') {
    event.preventDefault()
    endpointCatalogRef.value?.focusSearch()
    return
  }
  if (ctrlOrMeta && key === 's') {
    event.preventDefault()
    if (canManageSwagger.value && selectedEndpoint.value) {
      workspaceRef.value?.triggerPrimarySave()
    }
    return
  }
  if (ctrlOrMeta && event.shiftKey && key === 'p') {
    event.preventDefault()
    if (project.value && canPublish.value) {
      onUpdateProxy({
        proxy_enabled: !project.value.proxy_enabled,
        proxy_base_url: project.value.proxy_base_url || '',
      })
    }
  }
}
watch(selectedTaskId, async (next, prev) => {
  if (next === prev) return
  showSideTaskPicker.value = false
  endpointKeyword.value = ''
  closeSocket()
  resetTaskContext()
  if (!next) return
  const version = contextVersion.value
  await refreshProjectContext()
  if (version === contextVersion.value) connectCollab()
})
async function loadWorkspace() {
  const workspaceId = wsId.value
  try {
    await loadPermissions()
    if (workspaceId !== wsId.value) return
    if (!canView.value) { pageError.value = t('api_mock.no_view_permission'); return }
    await Promise.all([loadWorkspaceMembers(), loadTasks()])
  } catch (error) {
    if (workspaceId !== wsId.value) return
    pageError.value = formatApiError(error, t('api_mock.load_failed'), t)
    notifyError(error, t('api_mock.load_failed'))
  }
}
watch(wsId, () => { selectedTaskId.value = ''; void loadWorkspace() })
onMounted(async () => {
  window.addEventListener('keydown', onShortcuts)
  if (!authStore.user) await authStore.fetchCurrentUser()
  await loadWorkspace()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onShortcuts))
</script>

<template>
  <div class="api-mock-page">
    <ApiMockTaskBar
      v-if="selectedTaskId"
      :selected-task-name="selectedTask?.name || ''"
      :current-source-label="currentSourceLabel"
      :can-view="canView"
      :active-job="activeJob"
      :swagger-mutation-locked="isProjectSwaggerMutationLocked"
      :collab-connected="collabConnected"
      :online-users="onlineUsers"
      @open-config="(mode: string) => { configDrawerMode = mode as 'sync' | 'versions' | 'proxy' | 'import'; showConfigDrawer = true }"
    />

    <section v-if="permissionsReady && !canView" class="state-panel glass-panel">
      <h2>{{ $t('api_mock.no_view_permission') }}</h2>
      <p>{{ pageError || $t('api_mock.load_failed') }}</p>
    </section>

    <section v-else-if="!selectedTaskId" class="workbench-grid empty-workbench-grid">
      <div class="workbench-sidebar">
        <section class="task-side-panel glass-panel">
          <ApiMockTaskPickerPanel
            :tasks="tasks"
            :model-value="selectedTaskId"
            @update:model-value="handleTaskPicked"
          />
        </section>
      </div>

      <section class="state-panel glass-panel empty-canvas-panel">
        <span class="state-kicker">API MOCK</span>
        <h2>{{ $t('api_mock.task_empty') }}</h2>
        <p>{{ $t('api_mock.task_canvas_hint') }}</p>
      </section>
    </section>

    <section v-else class="workbench-grid">
      <div class="workbench-sidebar">
        <section class="task-side-panel glass-panel current-task-panel">
          <div class="task-side-head">
            <div>
              <span class="state-kicker">{{ $t('api_mock.task_ready') }}</span>
              <strong>{{ selectedTask?.name }}</strong>
              <p>{{ selectedTask?.id }}</p>
            </div>

            <button type="button" class="btn-secondary task-side-toggle" @click="showSideTaskPicker = !showSideTaskPicker">
              {{ showSideTaskPicker ? $t('api_mock.collapse_task_picker') : $t('api_mock.change_task') }}
            </button>
          </div>

          <div v-if="showSideTaskPicker" class="task-side-picker">
            <ApiMockTaskPickerPanel
              :tasks="tasks"
              :model-value="selectedTaskId"
              compact
              @update:model-value="handleTaskPicked"
            />
          </div>
        </section>

        <ApiMockEndpointCatalog
          ref="endpointCatalogRef"
          class="catalog-shell"
          :endpoints="endpoints"
          :selected-endpoint-id="selectedEndpointId"
          :keyword="endpointKeyword"
          :can-view="canView"
          @update:keyword="endpointKeyword = $event"
          @select="handleSelectEndpoint"
          @create-global-entity="openGlobalEntityDrawer"
        />
      </div>

      <ApiMockEndpointWorkspace
        ref="workspaceRef"
        :endpoint="selectedEndpoint"
        :entities="entities"
        :document="documentData"
        :document-loading="documentLoading"
        :can-manage="canManageSwagger"
        :can-manage-mock="canManage"
        :swagger-mutation-locked="isProjectSwaggerMutationLocked"
        :project-auto-mock-locked="isAutoMockRunning"
        :current-endpoint-auto-mock-locked="isCurrentEndpointAutoMockLocked"
        :auto-mock-busy="autoMockStartBusy"
        :auto-mock-job="activeAutoMockJob"
        :saving-endpoint="savingEndpoint"
        :saving-document="savingDocument"
        :cases="mockCases"
        :selected-case-id="selectedMockCaseId"
        :saving-case="savingCase"
        :deleting-case="deletingCase"
        :ws-id="wsId"
        :task-id="selectedTaskId"
        @save-endpoint="onSaveEndpoint"
        @save-document="onSaveDocument"
        @select-case="selectedMockCaseId = $event"
        @create-case="onCreateCase"
        @save-case="onSaveCase"
        @delete-case="onDeleteCase"
        @start-auto-mock="onStartAutoMock"
        @create-entity="onCreateEntity"
        @update-entity="onUpdateEntity"
        @delete-entity="onDeleteEntity"
      />
    </section>

    <ApiMockConfigDrawer
      :open="showConfigDrawer"
      :drawer-mode="configDrawerMode"
      :task-name="selectedTask?.name || ''"
      :project="project"
      :source-versions="sourceVersions"
      :can-manage="canManage"
      :can-publish="canPublish"
      :sync-busy="syncBusy"
      :import-busy="importBusy"
      :cancel-busy="cancelJobBusy"
      :active-job="activeJob"
      :swagger-mutation-locked="isProjectSwaggerMutationLocked"
      @close="showConfigDrawer = false"
      @sync="onSync"
      @cancel-job="onCancelActiveJob"
      @activate-source="onActivateSource"
      @update-proxy="onUpdateProxy"
      @import-swagger="onImportSwagger"
    />

    <ApiMockGlobalEntityDrawer
      ref="globalEntityDrawerRef"
      :open="showGlobalEntityDrawer"
      :entities="entities"
      :can-manage="canManageSwagger"
      @close="showGlobalEntityDrawer = false"
      @create-entity="onCreateEntity"
      @update-entity="onUpdateEntity"
      @delete-entity="onDeleteEntity"
    />

    <ShortcutHelpModal :show="showShortcuts" @close="showShortcuts = false" />
  </div>
</template>

<style scoped>
.api-mock-page {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.15rem;
  min-height: 100%;
}

.workbench-grid {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 1rem;
  min-height: calc(100vh - 240px);
}

.empty-workbench-grid {
  min-height: calc(100vh - 160px);
}

.workbench-sidebar {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 0;
}

.catalog-shell {
  flex: 1;
  min-height: 0;
}

.state-panel {
  min-height: 22rem;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 0.8rem;
  padding: 1.4rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
}

.state-kicker {
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.state-panel h2 {
  margin: 0.5rem 0 0;
  font-size: 1.8rem;
}

.state-panel p {
  margin: 0;
  max-width: 30rem;
  color: #64748b;
  line-height: 1.7;
}

.task-side-panel {
  padding: 1rem;
  border: 1px solid #e2e8f0;
  background: #ffffff;
}

.current-task-panel {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.task-side-head {
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  align-items: flex-start;
}

.task-side-head strong {
  display: block;
  margin-top: 0.32rem;
  color: #0f172a;
  font-size: 1rem;
}

.task-side-head p {
  margin: 0.24rem 0 0;
  color: #64748b;
  font-size: 0.8rem;
  line-height: 1.5;
  word-break: break-all;
}

.task-side-toggle {
  flex-shrink: 0;
  min-height: 2.8rem;
  border-radius: 16px;
  font-weight: 700;
}

.task-side-picker {
  padding-top: 0.2rem;
}

.empty-canvas-panel {
  min-height: 0;
}

.empty-canvas-panel h2 {
  margin-top: 0.1rem;
}

.w-5 {
  width: 1.25rem;
  height: 1.25rem;
}

@media (max-width: 1200px) {
  .workbench-grid {
    grid-template-columns: 1fr;
    min-height: auto;
  }
}

@media (max-width: 900px) {
  .api-mock-page {
    padding: 0.85rem;
  }

  .task-side-head {
    flex-direction: column;
  }
}
</style>
