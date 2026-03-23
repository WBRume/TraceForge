<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { 
  Activity, 
  CheckCircle,
  Clock,
  TrendingUp,
  Plus,
  Upload,
  TerminalSquare
} from 'lucide-vue-next'
import api from '@/utils/api'

// ECharts imports
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart, HeatmapChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  VisualMapComponent
} from 'echarts/components'

use([
  CanvasRenderer,
  PieChart,
  BarChart,
  HeatmapChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  VisualMapComponent
])

const { locale } = useI18n()
const route = useRoute()
const router = useRouter()
const wsId = route.params.wsId

const overview = ref<any>({ total_tasks: 0, success_rate: 0, active_tasks: 0 })
const loading = ref(true)
const workspace = ref<any>(null)

// Task creation state
const showTaskModal = ref(false)
const newTaskName = ref('')
const newTaskDesc = ref('')
const creatingTask = ref(false)
const uploadingSpec = ref(false)
const selectedFileName = ref('')
const pendingSpecFile = ref<File | null>(null)
const useBrainstorm = ref(false)

// Chart Options
const successChartOptions = ref<any>({})
const durationChartOptions = ref<any>({})
const heatmapOptions = ref<any>({})

const loadDashboardData = async () => {
  loading.value = true
  try {
    const [resOverview, resSuccess, resDuration] = await Promise.all([
      api.get(`/workspaces/${wsId}/dashboard/overview`),
      api.get(`/workspaces/${wsId}/dashboard/success-rate`),
      api.get(`/workspaces/${wsId}/dashboard/phase-duration`),
      api.get(`/workspaces/${wsId}/dashboard/retry-heatmap`)
    ])
    
    overview.value = resOverview.data

    // Pie Chart: Success Rate
    successChartOptions.value = {
      tooltip: { trigger: 'item' },
      legend: { bottom: '0%', left: 'center' },
      color: ['#10B981', '#F59E0B', '#EF4444'],
      series: [
        {
          name: 'Task Status',
          type: 'pie',
          radius: ['40%', '70%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 10,
            borderColor: '#fff',
            borderWidth: 2
          },
          label: { show: false, position: 'center' },
          emphasis: {
            label: { show: true, fontSize: 18, fontWeight: 'bold' }
          },
          labelLine: { show: false },
          data: resSuccess.data.map((item: any) => ({
            value: item.count,
            name: item.status
          }))
        }
      ]
    }

    // Bar Chart: Phase Duration
    durationChartOptions.value = {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: resDuration.data.map((i: any) => i.phase) },
      yAxis: { type: 'value', name: 'Avg Duration (s)' },
      series: [
        {
          name: 'Duration',
          type: 'bar',
          barWidth: '60%',
          itemStyle: { color: '#0EA5E9', borderRadius: [4, 4, 0, 0] },
          data: resDuration.data.map((i: any) => i.avg_duration_ms / 1000)
        }
      ]
    }

    // Heatmap (Mocked heavily here since ECharts Heatmap config is complex)
    // In actual production, it requires coordinate systems [hour(0-23), day(0-6), value]
    heatmapOptions.value = {
      tooltip: { position: 'top' },
      grid: { top: 30, bottom: 20 },
      xAxis: { type: 'category', data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] },
      yAxis: { type: 'category', data: ['Errors', 'Retries'] },
      visualMap: { min: 0, max: 10, calculable: true, orient: 'horizontal', left: 'center', bottom: -20, inRange: { color: ['#F0F9FF', '#0EA5E9', '#0C4A6E'] } },
      series: [{
        name: 'Retry Frequency',
        type: 'heatmap',
        data: [
          [0, 0, 1], [1, 0, 4], [2, 0, 0], [3, 0, 2], [4, 0, 5], [5, 0, 1], [6, 0, 0],
          [0, 1, 2], [1, 1, 1], [2, 1, 3], [3, 1, 4], [4, 1, 2], [5, 1, 0], [6, 1, 0]
        ],
        label: { show: true }
      }]
    }

  } catch (e) {
    console.error('Failed to load dashboard metrics', e)
  } finally {
    loading.value = false
  }
}

const loadWorkspace = async () => {
  try {
    const res = await api.get(`/workspaces/${wsId}`)
    workspace.value = res.data
  } catch (e) {
    console.error('Failed to load workspace info', e)
  }
}

const openNewTaskModal = () => {
  showTaskModal.value = true
}

const handleFileUpload = (event: any) => {
  const file = event.target.files[0]
  if (!file) return
  pendingSpecFile.value = file
  selectedFileName.value = file.name
}

const handleCreateTask = async () => {
  if (!newTaskName.value) return
  creatingTask.value = true
  try {
    // 1. 创建任务
    const res = await api.post(`/workspaces/${wsId}/tasks`, {
      name: newTaskName.value,
      description: newTaskDesc.value,
      use_brainstorm: useBrainstorm.value
    })
    
    const taskId = res.data.id

    // 2. 关联上传 Spec
    if (pendingSpecFile.value) {
      uploadingSpec.value = true
      const formData = new FormData()
      formData.append('file', pendingSpecFile.value)
      try {
        await api.post(`/workspaces/${wsId}/tasks/${taskId}/upload-spec`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        })
      } catch (uploadError) {
        console.error('Spec upload failed', uploadError)
      } finally {
        uploadingSpec.value = false
      }
    }

    showTaskModal.value = false
    newTaskName.value = ''
    newTaskDesc.value = ''
    pendingSpecFile.value = null
    useBrainstorm.value = false
    selectedFileName.value = ''
    
    router.push(`/ws/${wsId}/chat/${taskId}`)
  } catch (e) {
    console.error('Failed to create task', e)
  } finally {
    creatingTask.value = false
  }
}

onMounted(() => {
  loadDashboardData()
  loadWorkspace()
})

// 监听语言变化，重新生成图表配置（主要是 Title 和 Legend）
watch(locale, () => {
  loadDashboardData()
})
</script>

<template>
  <div class="dashboard-wrap p-8">
    <div class="mb-8 flex justify-between items-center">
      <div class="flex-1">
        <h1 class="text-3xl font-bold text-primary-900 mb-1">{{ $t('dashboard.title') }}</h1>
        <div class="flex items-center gap-4 text-sm text-slate-500">
           <div class="flex items-center gap-1"><TerminalSquare class="w-4 h-4" /> {{ workspace?.project_path || 'No Path' }}</div>
           <div class="flex items-center gap-1" v-if="workspace?.git_repo_url"><Plus class="w-4 h-4 rotate-45" /> {{ workspace.git_repo_url }}</div>
        </div>
      </div>
      <button class="btn-primary flex items-center gap-2" @click="openNewTaskModal">
        <Plus class="w-4 h-4" /> {{ $t('dashboard.new_task') }}
      </button>
    </div>

    <!-- KPI Banner -->
    <div class="kpi-grid grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
      <div class="kpi-card glass-panel flex flex-col justify-center">
        <div class="flex items-center gap-3 text-slate-500 mb-2">
          <Activity class="w-5 h-5 text-primary-500" />
          <span class="font-medium text-sm text-uppercase tracking-wide">{{ $t('dashboard.total_tasks') }}</span>
        </div>
        <div class="text-3xl font-bold text-primary-900">{{ overview.total_tasks }}</div>
      </div>
      
      <div class="kpi-card glass-panel flex flex-col justify-center">
        <div class="flex items-center gap-3 text-slate-500 mb-2">
          <TrendingUp class="w-5 h-5 text-emerald-500" />
          <span class="font-medium text-sm text-uppercase tracking-wide">{{ $t('dashboard.success_rate') }}</span>
        </div>
        <div class="text-3xl font-bold" :class="overview.success_rate > 0.8 ? 'text-emerald-500' : 'text-amber-500'">
          {{ (overview.success_rate * 100).toFixed(1) }}%
        </div>
      </div>
      
      <div class="kpi-card glass-panel flex flex-col justify-center">
        <div class="flex items-center gap-3 text-slate-500 mb-2">
          <Clock class="w-5 h-5 text-amber-500" />
          <span class="font-medium text-sm text-uppercase tracking-wide">{{ $t('dashboard.active_tasks') }}</span>
        </div>
        <div class="text-3xl font-bold text-slate-700">{{ overview.active_tasks }}</div>
      </div>
      
      <div class="kpi-card bg-primary-600 text-white flex flex-col justify-center relative overflow-hidden">
        <div class="relative z-10">
          <div class="flex items-center gap-3 text-primary-100 mb-2">
            <CheckCircle class="w-5 h-5" />
            <span class="font-medium text-sm text-uppercase tracking-wide">{{ $t('dashboard.time_saved') }}</span>
          </div>
          <div class="text-3xl font-bold">~{{ Math.floor((overview.total_tasks * 2.5) / 24) || 2 }}d</div>
        </div>
        <!-- Abstract shape -->
        <div class="absolute right-0 bottom-0 opacity-20 transform translate-x-4 translate-y-4">
          <Activity class="w-24 h-24" />
        </div>
      </div>
    </div>

    <!-- Charts Grid -->
    <div v-if="loading" class="text-center py-12 text-slate-500">Loading metrics...</div>
    
    <div v-else class="charts-grid grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- Success Rate Pie -->
      <div class="chart-container glass-panel">
        <h3 class="font-semibold text-lg text-slate-800 mb-4">{{ $t('dashboard.status_dist') }}</h3>
        <v-chart class="chart h-[300px]" :option="successChartOptions" autoresize />
      </div>
      
      <!-- Phase Duration Bar -->
      <div class="chart-container glass-panel">
        <h3 class="font-semibold text-lg text-slate-800 mb-4">{{ $t('dashboard.avg_phase') }}</h3>
        <v-chart class="chart h-[300px]" :option="durationChartOptions" autoresize />
      </div>
      
      <!-- Error/Retry Heatmap -->
      <div class="chart-container glass-panel lg:col-span-2">
        <h3 class="font-semibold text-lg text-slate-800 mb-4">{{ $t('dashboard.retry_heatmap') }}</h3>
        <v-chart class="chart h-[300px]" :option="heatmapOptions" autoresize />
      </div>
    </div>

    <div v-if="showTaskModal" class="modal-overlay" @click.self="showTaskModal = false">
      <div class="modal glass-panel">
        <div class="modal-header">
          <Plus class="w-6 h-6 text-primary" />
          <h2>{{ $t('dashboard.new_task') }}</h2>
        </div>
        
        <form @submit.prevent="handleCreateTask" class="modal-form">
          <div class="form-group">
            <label>{{ $t('dashboard.task_name') }}</label>
            <input v-model="newTaskName" type="text" class="input-field" required :placeholder="$t('dashboard.task_name_placeholder')">
          </div>
          
          <div class="form-group">
            <label>{{ $t('dashboard.description') }}</label>
            <textarea v-model="newTaskDesc" class="input-field" rows="3" :placeholder="$t('dashboard.desc_placeholder')"></textarea>
          </div>
          
          <div class="form-group">
            <label>{{ $t('dashboard.spec_doc') }}</label>
            <div class="file-upload-box glass-panel">
              <Upload class="w-5 h-5 text-primary" v-if="!uploadingSpec" />
              <Loader2 class="w-5 h-5 spin text-primary" v-else />
              <div class="file-name">{{ selectedFileName || $t('dashboard.spec_placeholder') }}</div>
              <input type="file" @change="handleFileUpload" class="hidden-input" id="spec-upload-dashboard" accept=".pdf,.doc,.docx,.md,.txt">
              <label for="spec-upload-dashboard" class="btn-primary file-choose-btn">{{ $t('common.confirm') }}</label>
            </div>
          </div>

          <div class="form-group checkbox-group py-1">
            <label class="flex items-center gap-2 cursor-pointer text-sm text-slate-700 select-none">
              <input v-model="useBrainstorm" type="checkbox" class="w-4 h-4 accent-primary-600 rounded">
              {{ $t('dashboard.brainstorm_hint') }}
            </label>
          </div>
          
          <div class="modal-actions">
            <button type="button" class="btn-secondary" @click="showTaskModal = false">{{ $t('common.cancel') }}</button>
            <button type="submit" class="btn-primary" :disabled="creatingTask">
              {{ creatingTask ? $t('common.loading') : $t('chat.initialize') }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Resets and utilities */
.p-8 { padding: 2rem; }
.mb-8 { margin-bottom: 2rem; }
.mb-4 { margin-bottom: 1rem; }
.mb-2 { margin-bottom: 0.5rem; }
.py-12 { padding-top: 3rem; padding-bottom: 3rem; }
.text-3xl { font-size: 1.875rem; line-height: 2.25rem; }
.text-lg { font-size: 1.125rem; line-height: 1.75rem; }
.text-sm { font-size: 0.875rem; line-height: 1.25rem; }
.font-bold { font-weight: 700; }
.font-semibold { font-weight: 600; }
.font-medium { font-weight: 500; }
.uppercase { text-transform: uppercase; }
.tracking-wide { letter-spacing: 0.025em; }
.text-slate-500 { color: #64748b; }
.text-slate-700 { color: #334155; }
.text-slate-800 { color: #1e293b; }
.text-primary-900 { color: var(--color-primary-900); }
.text-primary-600 { color: var(--color-primary-600); }
.text-primary-500 { color: var(--color-primary-500); }
.text-primary-100 { color: var(--color-primary-100); }
.text-emerald-500 { color: #10B981; }
.text-amber-500 { color: #F59E0B; }
.text-white { color: #fff; }
.bg-primary-600 { background-color: var(--color-primary-600); }
.flex { display: flex; }
.flex-col { flex-direction: column; }
.items-center { align-items: center; }
.justify-center { justify-content: center; }
.gap-3 { gap: 0.75rem; }
.gap-6 { gap: 1.5rem; }
.grid { display: grid; }
.grid-cols-1 { grid-template-columns: repeat(1, minmax(0, 1fr)); }
.relative { position: relative; }
.absolute { position: absolute; }
.overflow-hidden { overflow: hidden; }
.z-10 { z-index: 10; }
.top-0 { top: 0; }
.right-0 { right: 0; }
.bottom-0 { bottom: 0; }
.transform { transform: translate(var(--tw-translate-x), var(--tw-translate-y)) rotate(var(--tw-rotate)) skewX(var(--tw-skew-x)) skewY(var(--tw-skew-y)) scaleX(var(--tw-scale-x)) scaleY(var(--tw-scale-y)); }
.translate-x-4 { --tw-translate-x: 1rem; }
.translate-y-4 { --tw-translate-y: 1rem; }
.opacity-20 { opacity: 0.2; }
.h-\[300px\] { height: 300px; }
.text-center { text-align: center; }

@media (min-width: 768px) {
  .md\:grid-cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
@media (min-width: 1024px) {
  .lg\:grid-cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .lg\:col-span-2 { grid-column: span 2 / span 2; }
}

/* Custom Component Styles */
.kpi-card {
  height: 120px;
  padding: 0 var(--space-6);
  border-radius: var(--radius-xl);
  border: 1px solid rgba(255, 255, 255, 0.4);
  box-shadow: var(--shadow-md);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.kpi-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

.chart-container {
  padding: var(--space-6);
  border-radius: var(--radius-xl);
  background: white;
  border: 1px solid rgba(0,0,0,0.05);
  box-shadow: var(--shadow-sm);
}

.chart {
  width: 100%;
}

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.modal {
  width: 90%;
  max-width: 500px;
  padding: var(--space-8);
  background-color: white;
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-2xl);
}

.modal-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.modal-header h2 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 700;
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #475569;
}

.input-field {
  padding: 10px 14px;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  font-family: inherit;
  font-size: 1rem;
  width: 100%;
  box-sizing: border-box;
}
.input-field:focus {
  border-color: var(--color-primary-500);
  outline: none;
}

.file-upload-box {
  border: 1px dashed var(--color-primary-100);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  margin-top: 4px;
}
.file-upload-box:hover { border-style: solid; border-color: var(--color-primary-500); }
.file-name {
  flex: 1;
  font-size: 0.875rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.file-choose-btn { padding: 4px 12px; font-size: 0.75rem; cursor: pointer; }

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

/* Button variants if not global */
.btn-secondary {
  background: white;
  color: #475569;
  border: 1px solid #E2E8F0;
  padding: 8px 18px;
  border-radius: var(--radius-md);
  font-weight: 500;
  cursor: pointer;
}

.hidden-input {
  display: none;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
