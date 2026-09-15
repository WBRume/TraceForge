import { describe, expect, it } from 'vitest'
import {
  buildDurationChartOption,
  buildHeatmapOption,
  buildSuccessChartOption,
  type DashboardRetryHeatmapItem
} from '@/utils/dashboardCharts'

const t = (key: string) => key

describe('buildSuccessChartOption', () => {
  it('maps statuses through the translate function and keeps counts', () => {
    const option = buildSuccessChartOption(
      [
        { status: 'DONE', count: 3 },
        { status: 'FAILED', count: 1 }
      ],
      t
    ) as any

    expect(option.series[0].data).toEqual([
      { value: 3, name: 'dashboard.status.DONE' },
      { value: 1, name: 'dashboard.status.FAILED' }
    ])
  })

  it('handles empty data', () => {
    const option = buildSuccessChartOption([], t) as any
    expect(option.series[0].data).toEqual([])
  })
})

describe('buildDurationChartOption', () => {
  it('normalizes the fixed phase order and fills missing phases with zero', () => {
    const option = buildDurationChartOption(
      [{ phase: 'DURATION', avg_minutes: 12.5 }],
      t
    ) as any

    expect(option.xAxis.data).toEqual([
      'dashboard.phases.REQUIREMENT_DURATION',
      'dashboard.phases.DURATION'
    ])
    expect(option.series[0].data).toEqual([0, 12.5])
  })

  it('keeps provided values in order', () => {
    const option = buildDurationChartOption(
      [
        { phase: 'DURATION', avg_minutes: 20 },
        { phase: 'REQUIREMENT_DURATION', avg_minutes: 180 }
      ],
      t
    ) as any

    expect(option.series[0].data).toEqual([180, 20])
  })
})

describe('buildHeatmapOption', () => {
  const denseWeek: DashboardRetryHeatmapItem[] = Array.from({ length: 7 }, (_, index) => ({
    date: `2026-03-${String(index + 2).padStart(2, '0')}`,
    retry_count: index,
    failure_count: index * 2,
    task_count: 1
  }))

  it('renders one failure cell and one retry cell per day', () => {
    const option = buildHeatmapOption(denseWeek, 'en') as any

    expect(option.xAxis.data).toEqual([
      '03/02', '03/03', '03/04', '03/05', '03/06', '03/07', '03/08'
    ])
    expect(option.series[0].data).toHaveLength(14)
    expect(option.series[0].data[0]).toEqual([0, 0, 0])
    expect(option.series[0].data[1]).toEqual([0, 1, 0])
    expect(option.series[0].data[12]).toEqual([6, 0, 12])
    expect(option.series[0].data[13]).toEqual([6, 1, 6])
  })

  it('keeps the visual map minimum range at 5', () => {
    const option = buildHeatmapOption(
      [{ date: '2026-03-02', retry_count: 1, failure_count: 0, task_count: 1 }],
      'zh'
    ) as any

    expect(option.visualMap.max).toBe(5)
  })

  it('formats tooltips with the matching day and localized row label', () => {
    const zhOption = buildHeatmapOption(denseWeek, 'zh') as any
    const enOption = buildHeatmapOption(denseWeek, 'en') as any

    expect(zhOption.tooltip.formatter({ data: [2, 1, 4] })).toBe('03/04<br/>重试: <b>4</b>')
    expect(enOption.tooltip.formatter({ data: [2, 0, 4] })).toBe('03/04<br/>Failures: <b>4</b>')
  })

  it('handles empty data', () => {
    const option = buildHeatmapOption([], 'en') as any

    expect(option.xAxis.data).toEqual([])
    expect(option.series[0].data).toEqual([])
  })
})
