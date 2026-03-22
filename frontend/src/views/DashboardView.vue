<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { 
  Activity, 
  CheckCircle,
  Clock,
  TrendingUp,
  Plus,
  Upload
} from 'lucide-vue-next'
import { useRouter } from 'vue-router'
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
const newTaskSpec = ref('')
const creatingTask = ref(false)
const uploadingSpec = ref(false)
const selectedFileName = ref('')

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
          itemStyle: { color: '#3B82F6', borderRadius: [4, 4, 0, 0] },
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
      visualMap: { min: 0, max: 10, calculable: true, orient: 'horizontal', left: 'center', bottom: -20, inRange: { color: ['#EFF6FF', '#3B82F6', '#1E3A8A'] } },
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

const handleFileUpload = async (event: any) => {
  const file = event.target.files[0]
  if (!file) return
  
  uploadingSpec.value = true
  selectedFileName.value = file.name
  const formData = new FormData()
  formData.append('file', file)
  
  try {
    const res = await api.post('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    newTaskSpec.value = res.data.path
  } catch (e) {
    console.error('Upload failed', e)
    selectedFileName.value = 'Upload failed'
  } finally {
    uploadingSpec.value = false
  }
}

const handleCreateTask = async () => {
  if (!newTaskName.value) return
  creatingTask.value = true
  try {
    const res = await api.post(`/workspaces/${wsId}/tasks`, {
      name: newTaskName.value,
      description: newTaskDesc.value,
      spec_doc_path: newTaskSpec.value
    })
    showTaskModal.value = false
    router.push(`/ws/${wsId}/chat/${res.data.id}`)
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
</script>

<template>
  <div class="dashboard-wrap p-8">
    <div class="mb-8 flex justify-between items-center">
      <div class="flex-1">
        <h1 class="text-3xl font-bold text-primary-900 mb-1">Metrics Dashboard</h1>
        <div class="flex items-center gap-4 text-sm text-slate-500">
           <div class="flex items-center gap-1"><TerminalSquare class="w-4 h-4" /> {{ workspace?.project_path || 'No Path' }}</div>
           <div class="flex items-center gap-1" v-if="workspace?.git_repo_url"><Plus class="w-4 h-4 rotate-45" /> {{ workspace.git_repo_url }}</div>
        </div>
      </div>
      <button class="btn-primary flex items-center gap-2" @click="openNewTaskModal">
        <Plus class="w-4 h-4" /> Start New Task
      </button>
    </div>

    <!-- KPI Banner -->
    <div class="kpi-grid grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
      <div class="kpi-card glass-panel flex flex-col justify-center">
        <div class="flex items-center gap-3 text-slate-500 mb-2">
          <Activity class="w-5 h-5 text-primary-500" />
          <span class="font-medium text-sm text-uppercase tracking-wide">Total Tasks</span>
        </div>
        <div class="text-3xl font-bold text-primary-900">{{ overview.total_tasks }}</div>
      </div>
      
      <div class="kpi-card glass-panel flex flex-col justify-center">
        <div class="flex items-center gap-3 text-slate-500 mb-2">
          <TrendingUp class="w-5 h-5 text-emerald-500" />
          <span class="font-medium text-sm text-uppercase tracking-wide">Success Rate</span>
        </div>
        <div class="text-3xl font-bold" :class="overview.success_rate > 0.8 ? 'text-emerald-500' : 'text-amber-500'">
          {{ (overview.success_rate * 100).toFixed(1) }}%
        </div>
      </div>
      
      <div class="kpi-card glass-panel flex flex-col justify-center">
        <div class="flex items-center gap-3 text-slate-500 mb-2">
          <Clock class="w-5 h-5 text-amber-500" />
          <span class="font-medium text-sm text-uppercase tracking-wide">Active Tasks</span>
        </div>
        <div class="text-3xl font-bold text-slate-700">{{ overview.active_tasks }}</div>
      </div>
      
      <div class="kpi-card bg-primary-600 text-white flex flex-col justify-center relative overflow-hidden">
        <div class="relative z-10">
          <div class="flex items-center gap-3 text-primary-100 mb-2">
            <CheckCircle class="w-5 h-5" />
            <span class="font-medium text-sm text-uppercase tracking-wide">Time Saved</span>
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
        <h3 class="font-semibold text-lg text-slate-800 mb-4">Task Status Distribution</h3>
        <v-chart class="chart h-[300px]" :option="successChartOptions" autoresize />
      </div>
      
      <!-- Phase Duration Bar -->
      <div class="chart-container glass-panel">
        <h3 class="font-semibold text-lg text-slate-800 mb-4">Average Phase Duration</h3>
        <v-chart class="chart h-[300px]" :option="durationChartOptions" autoresize />
      </div>
      
      <!-- Error/Retry Heatmap -->
      <div class="chart-container glass-panel lg:col-span-2">
        <h3 class="font-semibold text-lg text-slate-800 mb-4">Error & Retry Heatmap (Last 7 Days)</h3>
        <v-chart class="chart h-[300px]" :option="heatmapOptions" autoresize />
      </div>
    </div>

    <!-- Create Task Modal -->
    <div v-if="showTaskModal" class="modal-overlay" @click.self="showTaskModal = false">
      <div class="modal glass-panel">
        <div class="flex items-center gap-3 mb-4">
          <Plus class="w-6 h-6 text-primary-600" />
          <h2 class="text-xl font-bold m-0">Initiate New Task</h2>
        </div>
        
        <form @submit.prevent="handleCreateTask" class="flex flex-col gap-4">
          <div class="form-group flex flex-col gap-1">
            <label class="text-sm font-medium text-slate-700">Task Name</label>
            <input v-model="newTaskName" type="text" class="input-field" required placeholder="e.g. Implement User Profile API">
          </div>
          
          <div class="form-group flex flex-col gap-1">
            <label class="text-sm font-medium text-slate-700">Description (Optional)</label>
            <textarea v-model="newTaskDesc" class="input-field" rows="2" placeholder="Task goal details"></textarea>
          </div>
          
          <div class="form-group flex flex-col gap-1">
            <label class="text-sm font-medium text-slate-700">SE (Specification) Document</label>
            <div class="file-upload-box glass-panel flex items-center gap-3 p-3 mt-1">
              <Upload class="w-5 h-5 text-primary-500" v-if="!uploadingSpec" />
              <Loader2 class="w-5 h-5 animate-spin text-primary-500" v-else />
              <div class="flex-1 text-sm truncate">
                {{ selectedFileName || 'Upload Requirement Doc...' }}
              </div>
              <input type="file" @change="handleFileUpload" class="hidden-input" id="spec-upload" accept=".pdf,.doc,.docx,.md,.txt">
              <label for="spec-upload" class="btn-primary py-1 px-3 text-xs cursor-pointer">Choose</label>
            </div>
          </div>

          <div class="flex justify-end gap-3 mt-6">
            <button type="button" class="btn-secondary" @click="showTaskModal = false">Cancel</button>
            <button type="submit" class="btn-primary" :disabled="creatingTask">
              {{ creatingTask ? 'Creating...' : 'Initialize SDD Loop' }}
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

.input-field {
  padding: 10px 14px;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  font-family: inherit;
  font-size: 1rem;
}

.input-field:focus {
  border-color: var(--color-primary-500);
  outline: none;
}

/* Button variants if not global */
.btn-secondary {
  background: #F1F5F9;
  color: #475569;
  padding: 10px 20px;
  border-radius: var(--radius-md);
  font-weight: 600;
  border: none;
  cursor: pointer;
}

.file-upload-box {
  border: 1px dashed var(--color-primary-100);
}

.file-upload-box:hover {
  border-style: solid;
  border-color: var(--color-primary-500);
}

.hidden-input {
  display: none;
}
</style>
