<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { 
  Activity, 
  CheckCircle,
  Clock,
  TrendingUp,
  Plus, 
  TerminalSquare
} from 'lucide-vue-next'
import api from '@/utils/api'
import NewTaskModal from '@/components/NewTaskModal.vue'

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

const { locale, t } = useI18n()
const route = useRoute()
const router = useRouter()
const wsId = route.params.wsId

const overview = ref<any>({ total_tasks: 0, success_rate: 0, active_tasks: 0 })
const loading = ref(true)
const workspace = ref<any>(null)
const workspacePermissions = ref<any>(null)
const canCreateTask = computed(() => Boolean(workspacePermissions.value?.create_task))

// Task creation state
const showTaskModal = ref(false)

// Chart Options
const successChartOptions = ref<any>({})
const durationChartOptions = ref<any>({})
const heatmapOptions = ref<any>({})

const loadDashboardData = async () => {
  loading.value = true
  try {
    const [resOverview, resSuccess, resDuration, resHeatmap] = await Promise.all([
      api.get(`/workspaces/${wsId}/dashboard/overview`),
      api.get(`/workspaces/${wsId}/dashboard/success-rate`),
      api.get(`/workspaces/${wsId}/dashboard/phase-duration`),
      api.get(`/workspaces/${wsId}/dashboard/retry-heatmap`)
    ])
    
    overview.value = resOverview.data

    // Pie Chart: Success Rate
    successChartOptions.value = {
      tooltip: { 
        trigger: 'item',
        backgroundColor: 'rgba(255, 255, 255, 0.9)',
        textStyle: { color: '#1e293b' },
        borderWidth: 0,
        boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)'
      },
      legend: { bottom: '0%', left: 'center', icon: 'circle', textStyle: { color: '#64748b' } },
      color: [
        {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: '#10B981' }, { offset: 1, color: '#059669' }]
        },
        {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: '#EF4444' }, { offset: 1, color: '#DC2626' }]
        },
        {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: '#60A5FA' }, { offset: 1, color: '#2563EB' }]
        },
        {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: '#FDBA74' }, { offset: 1, color: '#EA580C' }]
        }
      ],
      series: [
        {
          name: 'Task Status',
          type: 'pie',
          radius: ['50%', '75%'],
          center: ['50%', '45%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 8,
            borderColor: '#fff',
            borderWidth: 2
          },
          label: { show: false },
          emphasis: {
            scale: true,
            scaleSize: 10,
          },
          data: resSuccess.data.map((item: any) => ({
            value: item.count,
            name: t(`dashboard.status.${item.status}`)
          }))
        }
      ]
    }

    // Bar Chart: Phase Duration
    const phaseOrder = ['REQUIREMENT_DURATION', 'DURATION']
    const normalizedDuration = phaseOrder.map(phase => {
      const found = resDuration.data.find((i: any) => i.phase === phase)
      return {
        phase,
        avg_minutes: found ? found.avg_minutes : 0
      }
    })

    durationChartOptions.value = {
      tooltip: { 
        trigger: 'axis', 
        axisPointer: { type: 'shadow' },
        formatter: (params: any) => {
          const p = params[0]
          return `${p.name}<br/>${p.seriesName}: <b>${p.value}</b> ${t('dashboard.phases.UNIT_MIN')}`
        }
      },
      grid: { left: '3%', right: '4%', bottom: '8%', containLabel: true, top: '15%' },
      xAxis: { 
        type: 'category', 
        data: normalizedDuration.map((i: any) => t(`dashboard.phases.${i.phase}`)),
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#64748b' }
      },
      yAxis: { 
        type: 'value', 
        name: `${t('dashboard.avg_phase')} (${t('dashboard.phases.UNIT_MIN')})`,
        axisLine: { show: false },
        splitLine: { lineStyle: { type: 'dashed', color: '#f1f5f9' } },
        nameTextStyle: { color: '#64748b', padding: [0, 0, 0, 40] }
      },
      series: [
        {
          name: t('dashboard.avg_phase'),
          type: 'bar',
          barWidth: '40%',
          itemStyle: { 
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: '#3b82f6' },
                { offset: 1, color: '#1d4ed8' }
              ]
            },
            borderRadius: [6, 6, 0, 0]
          },
          data: normalizedDuration.map((i: any) => i.avg_minutes)
        }
      ]
    }

    // 4. Heatmap: 2D Data (Retries & Failures)
    const last7Days: string[] = []
    for (let i = 6; i >= 0; i--) {
      const d = new Date()
      d.setDate(d.getDate() - i)
      last7Days.push(d.toISOString().split('T')[0])
    }

    const yCategories = locale.value === 'zh' ? ['失败', '重试'] : ['Failures', 'Retries']
    const heatmapSeriesData: any[] = []

    last7Days.forEach((dateStr, xIdx) => {
      const dayData = resHeatmap.data.find((d: any) => d.date === dateStr)
      
      // yIdx 0: Failure, yIdx 1: Retry
      heatmapSeriesData.push([xIdx, 0, dayData ? dayData.failure_count : 0])
      heatmapSeriesData.push([xIdx, 1, dayData ? dayData.retry_count : 0])
    })

    heatmapOptions.value = {
      tooltip: {
        position: 'top',
        formatter: (params: any) => {
          const xIdx = params.data[0]
          const yIdx = params.data[1]
          const val = params.data[2]
          const date = last7Days[xIdx].split('-').slice(1).join('/')
          return `${date}<br/>${yCategories[yIdx]}: <b>${val}</b>`
        }
      },
      grid: { top: 20, bottom: 40, left: 60, right: 20 },
      xAxis: { 
        type: 'category', 
        data: last7Days.map(d => d.split('-').slice(1).join('/')),
        axisLine: { lineStyle: { color: '#e2e8f0' } }
      },
      yAxis: { 
        type: 'category', 
        data: yCategories,
        splitArea: { show: true },
        axisLine: { lineStyle: { color: '#e2e8f0' } }
      },
      visualMap: { 
        min: 0, 
        max: Math.max(...heatmapSeriesData.map(d => d[2]), 5), 
        calculable: true, 
        orient: 'horizontal', 
        left: 'center', 
        bottom: 0,
        inRange: { color: ['#eff6ff', '#60a5fa', '#1e40af'] },
        text: [locale.value === 'zh' ? '高' : 'High', locale.value === 'zh' ? '低' : 'Low'],
        textStyle: { color: '#64748b' }
      },
      series: [{
        name: '波动统计',
        type: 'heatmap',
        data: heatmapSeriesData,
        label: { show: true, color: '#1e293b' },
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: 'rgba(0, 0, 0, 0.5)'
          }
        }
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
    const [wsRes, permissionRes] = await Promise.all([
      api.get(`/workspaces/${wsId}`),
      api.get(`/workspaces/${wsId}/permissions/me`),
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
      <button class="btn-primary flex items-center gap-2" :disabled="!canCreateTask" @click="openNewTaskModal">
        <Plus class="w-4 h-4" /> {{ $t('dashboard.new_task') }}
      </button>
    </div>

    <!-- KPI Banner -->
    <div class="kpi-grid grid grid-cols-1 md:grid-cols-5 gap-6 mb-8">
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

      <div class="kpi-card glass-panel flex flex-col justify-center border-l-4 border-l-indigo-500">
        <div class="flex items-center gap-3 text-slate-500 mb-2">
          <TerminalSquare class="w-5 h-5 text-indigo-500" />
          <span class="font-medium text-sm text-uppercase tracking-wide">{{ $t('dashboard.total_cost') }}</span>
        </div>
        <div class="text-3xl font-bold text-indigo-600">${{ overview.total_cost_usd?.toFixed(4) || '0.0000' }}</div>
      </div>
      
      <div class="kpi-card bg-primary-600 text-white flex flex-col justify-center relative overflow-hidden">
        <div class="relative z-10">
          <div class="flex items-center gap-3 text-primary-100 mb-2">
            <CheckCircle class="w-5 h-5" />
            <span class="font-medium text-sm text-uppercase tracking-wide">{{ $t('dashboard.time_saved') }}</span>
          </div>
          <div class="text-3xl font-bold">{{ overview.avg_duration_minutes?.toFixed(1) || '0.0' }}h</div>
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

    <NewTaskModal 
      :show="showTaskModal" 
      :wsId="(wsId as string)" 
      @close="showTaskModal = false" 
      @created="onTaskCreated" 
    />
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
  .md\:grid-cols-5 { grid-template-columns: repeat(5, minmax(0, 1fr)); }
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

.btn-primary {
  background: var(--color-primary-500);
  color: white !important;
  border: none;
  padding: 8px 18px;
  border-radius: var(--radius-md);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 4px 6px -1px rgba(14, 165, 233, 0.2);
}

.btn-primary:hover {
  background: var(--color-primary-600);
  transform: translateY(-1px);
  box-shadow: 0 10px 15px -3px rgba(14, 165, 233, 0.3), 0 4px 6px -2px rgba(14, 165, 233, 0.1);
  text-shadow: 0 0 8px rgba(255, 255, 255, 0.5);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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
