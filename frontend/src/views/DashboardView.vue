<script setup lang="ts">
import { computed, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Activity,
  CheckCircle,
  Clock,
  GitBranch,
  Plus,
  TerminalSquare,
  TrendingUp,
} from '@/components/icons'
import api from '@/utils/api'
import NewTaskModal from '@/components/task-create/NewTaskModal.vue'
import DioramaWorkbench from '@/components/dashboard/DioramaWorkbench.vue'

const route = useRoute()
const router = useRouter()
const wsId = computed(() => String(route.params.wsId || ''))

const overview = ref({
  total_tasks: 0,
  success_rate: 0,
  active_tasks: 0,
  time_saved_hours: 0,
  total_cost_usd: 0,
})
const loadError = shallowRef(false)
const workspace = ref<Record<string, any> | null>(null)
const workspacePermissions = ref<Record<string, any> | null>(null)
const canCreateTask = computed(() => Boolean(workspacePermissions.value?.create_task))

const showTaskModal = shallowRef(false)

const loadDashboardOverview = async () => {
  const id = wsId.value
  if (!id) return
  try {
    const resOverview = await api.get(`/workspaces/${id}/dashboard/overview`)
    overview.value = resOverview.data
    loadError.value = false
  } catch (e) {
    console.error('Failed to load dashboard overview', e)
    loadError.value = true
  }
}

const loadWorkspace = async () => {
  const id = wsId.value
  if (!id) return
  try {
    const [wsRes, permissionRes] = await Promise.all([
      api.get(`/workspaces/${id}`),
      api.get(`/workspaces/${id}/permissions/me`),
    ])
    workspace.value = wsRes.data
    workspacePermissions.value = permissionRes.data?.permissions || null
  } catch (e) {
    console.error('Failed to load workspace info', e)
  }
}

const openNewTaskModal = () => {
  if (!canCreateTask.value) return
  showTaskModal.value = true
}

const onTaskCreated = (payload: { jobId: string; taskId: string; workspaceId: string; expectSpecUpload: boolean }) => {
  const jobId = String(payload?.jobId || '').trim()
  showTaskModal.value = false
  if (!jobId) return
  const expectSpec = payload.expectSpecUpload ? '?expectSpec=1' : ''
  router.push(`/ops/queue/provision/${jobId}${expectSpec}`)
}

onMounted(() => {
  loadDashboardOverview()
  loadWorkspace()
})

watch(wsId, (next, prev) => {
  if (next && next !== prev) {
    loadDashboardOverview()
    loadWorkspace()
  }
})
</script>

<template>
  <div class="dashboard-wrap">
    <header class="dashboard-header">
      <div class="header-title-group">
        <h1 class="dashboard-title">{{ $t('dashboard.title') }}</h1>
        <div class="workspace-meta">
          <span v-if="workspace?.project_path" class="meta-item" :title="workspace.project_path">
            <TerminalSquare class="meta-icon" />
            <span class="meta-text">{{ workspace.project_path }}</span>
          </span>
          <span v-if="workspace?.git_repo_url" class="meta-item" :title="workspace.git_repo_url">
            <GitBranch class="meta-icon" />
            <span class="meta-text">{{ workspace.git_repo_url }}</span>
          </span>
        </div>
      </div>

      <div class="header-actions">
        <button class="btn-primary new-task-btn" :disabled="!canCreateTask" @click="openNewTaskModal">
          <Plus class="btn-icon" />
          <span>{{ $t('dashboard.new_task') }}</span>
        </button>
      </div>
    </header>

    <div v-if="loadError" class="error-banner">
      <span>{{ $t('dashboard.load_error') }}</span>
      <button class="btn-secondary" @click="loadDashboardOverview">{{ $t('dashboard.retry') }}</button>
    </div>

    <!-- Compact 5-KPI Overview Strip -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-head">
          <Activity class="kpi-icon text-primary-500" />
          <span class="kpi-label">{{ $t('dashboard.total_tasks') }}</span>
        </div>
        <div class="kpi-value text-primary-900">{{ overview.total_tasks }}</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-head">
          <TrendingUp class="kpi-icon text-emerald-500" />
          <span class="kpi-label">{{ $t('dashboard.success_rate') }}</span>
        </div>
        <div class="kpi-value" :class="overview.success_rate > 0.8 ? 'text-emerald-500' : 'text-amber-500'">
          {{ (overview.success_rate * 100).toFixed(1) }}%
        </div>
      </div>

      <div class="kpi-card">
        <div class="kpi-head">
          <Clock class="kpi-icon text-amber-500" />
          <span class="kpi-label">{{ $t('dashboard.active_tasks') }}</span>
        </div>
        <div class="kpi-value text-slate-700">{{ overview.active_tasks }}</div>
      </div>

      <div class="kpi-card kpi-card-cost">
        <div class="kpi-head">
          <TerminalSquare class="kpi-icon text-indigo-500" />
          <span class="kpi-label">{{ $t('dashboard.total_cost') }}</span>
        </div>
        <div class="kpi-value text-indigo-600">${{ overview.total_cost_usd?.toFixed(4) || '0.0000' }}</div>
      </div>

      <div class="kpi-card kpi-card-accent">
        <div class="kpi-accent-content">
          <div class="kpi-head">
            <CheckCircle class="kpi-icon text-primary-100" />
            <span class="kpi-label text-primary-100">{{ $t('dashboard.time_saved') }}</span>
          </div>
          <div class="kpi-value text-white">{{ overview.time_saved_hours?.toFixed(1) || '0.0' }}h</div>
        </div>
        <div class="kpi-accent-bg" aria-hidden="true">
          <Activity class="kpi-bg-icon" />
        </div>
      </div>
    </div>

    <!-- 2.5D Multi-Repository Architectural Diorama -->
    <DioramaWorkbench :workspace-id="wsId" />

    <NewTaskModal
      :show="showTaskModal"
      :wsId="wsId"
      @close="showTaskModal = false"
      @created="onTaskCreated"
    />
  </div>
</template>

<style scoped>
.dashboard-wrap {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 100%;
  padding: clamp(16px, 2vw, 24px);
}

.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.header-title-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.dashboard-title {
  margin: 0;
  font-size: 1.5rem;
  line-height: 1.9rem;
  font-weight: 700;
  color: var(--color-primary-900);
}

.workspace-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 12.5px;
  color: var(--color-text-muted);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  max-width: 420px;
}

.meta-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: #94a3b8;
}

.meta-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn-icon {
  width: 15px;
  height: 15px;
}

.new-task-btn {
  height: 36px;
  padding: 0 16px;
  border-radius: var(--radius-md);
  font-size: 13px;
}

.error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border: 1px solid #fecaca;
  border-radius: var(--radius-md);
  background: #fef2f2;
  color: #b91c1c;
  font-size: 13px;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.kpi-card {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  min-height: 80px;
  padding: 12px 16px;
  border-radius: var(--radius-xl);
  background: var(--color-surface-white);
  border: 1px solid #e2e8f0;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
}

.kpi-card:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.kpi-card-cost {
  border-left: 3px solid #6366f1;
}

.kpi-card-accent {
  background: var(--color-primary-600);
  border-color: var(--color-primary-600);
  color: #ffffff;
}

.kpi-accent-content {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kpi-accent-bg {
  position: absolute;
  right: -10px;
  bottom: -14px;
  opacity: 0.18;
  pointer-events: none;
}

.kpi-bg-icon {
  width: 72px;
  height: 72px;
}

.kpi-head {
  display: flex;
  align-items: center;
  gap: 7px;
}

.kpi-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.kpi-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
}

.kpi-value {
  font-size: 1.5rem;
  line-height: 1.8rem;
  font-weight: 700;
  font-family: var(--font-heading);
}

.text-primary-900 { color: var(--color-primary-900); }
.text-primary-500 { color: var(--color-primary-500); }
.text-primary-100 { color: var(--color-primary-100); }
.text-emerald-500 { color: #10b981; }
.text-amber-500 { color: #f59e0b; }
.text-indigo-500 { color: #6366f1; }
.text-indigo-600 { color: #4f46e5; }
.text-slate-700 { color: #334155; }
.text-white { color: #ffffff; }

@media (max-width: 1120px) {
  .kpi-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
