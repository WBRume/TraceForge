import type { EChartsCoreOption } from 'echarts/core'

export interface DashboardSuccessRateItem {
  status: string
  count: number
}

export interface DashboardPhaseDurationItem {
  phase: string
  avg_minutes: number
}

export interface DashboardRetryHeatmapItem {
  date: string
  retry_count: number
  failure_count: number
  task_count: number
}

type TranslateFn = (key: string) => string

export function buildSuccessChartOption(
  data: DashboardSuccessRateItem[],
  t: TranslateFn
): EChartsCoreOption {
  return {
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
          scaleSize: 10
        },
        data: data.map(item => ({
          value: item.count,
          name: t(`dashboard.status.${item.status}`)
        }))
      }
    ]
  }
}

export function buildDurationChartOption(
  data: DashboardPhaseDurationItem[],
  t: TranslateFn
): EChartsCoreOption {
  const phaseOrder = ['REQUIREMENT_DURATION', 'DURATION']
  const normalized = phaseOrder.map(phase => {
    const found = data.find(item => item.phase === phase)
    return {
      phase,
      avg_minutes: found ? found.avg_minutes : 0
    }
  })

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const p = params[0]
        return `${p.name}<br/>${p.seriesName}: <b>${p.value}</b> ${t('dashboard.phases.UNIT_MIN')}`
      }
    },
    grid: {
      left: 56,
      right: 24,
      bottom: 36,
      top: 40
    },
    xAxis: {
      type: 'category',
      data: normalized.map(item => t(`dashboard.phases.${item.phase}`)),
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#64748b' }
    },
    yAxis: {
      type: 'value',
      name: t('dashboard.phases.UNIT_MIN'),
      nameGap: 12,
      axisLine: { show: false },
      splitLine: { lineStyle: { type: 'dashed', color: '#f1f5f9' } },
      nameTextStyle: { color: '#64748b', align: 'left' }
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
        data: normalized.map(item => item.avg_minutes)
      }
    ]
  }
}

export function buildHeatmapOption(
  data: DashboardRetryHeatmapItem[],
  locale: string
): EChartsCoreOption {
  const isZh = locale === 'zh'
  const yCategories = isZh ? ['失败', '重试'] : ['Failures', 'Retries']
  const seriesData: [number, number, number][] = []

  data.forEach((day, xIdx) => {
    // yIdx 0: Failure, yIdx 1: Retry
    seriesData.push([xIdx, 0, day.failure_count])
    seriesData.push([xIdx, 1, day.retry_count])
  })

  return {
    tooltip: {
      position: 'top',
      formatter: (params: any) => {
        const xIdx = params.data[0]
        const yIdx = params.data[1]
        const val = params.data[2]
        const date = data[xIdx]?.date?.split('-').slice(1).join('/') ?? ''
        return `${date}<br/>${yCategories[yIdx]}: <b>${val}</b>`
      }
    },
    grid: { top: 20, bottom: 40, left: 60, right: 20 },
    xAxis: {
      type: 'category',
      data: data.map(day => day.date.split('-').slice(1).join('/')),
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
      max: Math.max(...seriesData.map(item => item[2]), 5),
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      inRange: { color: ['#eff6ff', '#60a5fa', '#1e40af'] },
      text: [isZh ? '高' : 'High', isZh ? '低' : 'Low'],
      textStyle: { color: '#64748b' }
    },
    series: [{
      name: isZh ? '波动统计' : 'Activity',
      type: 'heatmap',
      data: seriesData,
      label: { show: true, color: '#1e293b' },
      emphasis: {
        itemStyle: {
          shadowBlur: 10,
          shadowColor: 'rgba(0, 0, 0, 0.5)'
        }
      }
    }]
  }
}
