import { ref } from 'vue'
import type { ResultSummaryStep, ResultsSummaryState } from '../types'

/**
 * 运行结果汇总卡：duration/cost 累计 + 阶段历史。
 * WS `result` 事件累积；切换会话/初始化/清空历史时重置。
 */
export function useResultsSummary() {
  const state = ref<ResultsSummaryState>({
    visible: false,
    totalDurationMs: 0,
    totalCostUsd: 0,
    history: [],
    expanded: false,
  })

  const reset = () => {
    state.value = { visible: false, totalDurationMs: 0, totalCostUsd: 0, history: [], expanded: false }
  }

  /** 从任务摘要初始化（进入会话时展示历史累计）。 */
  const resetFromTask = (task: any) => {
    state.value = {
      visible: (task.total_cost_usd || 0) > 0 || (task.total_duration_ms || 0) > 0,
      totalDurationMs: task.total_duration_ms || 0,
      totalCostUsd: task.total_cost_usd || 0,
      history: [],
      expanded: false,
    }
  }

  const appendResult = (payload: any) => {
    state.value.visible = true
    state.value.totalDurationMs += payload.duration_ms || 0
    state.value.totalCostUsd += (payload.cost_usd || 0)
    const step: ResultSummaryStep = {
      id: Date.now().toString() + Math.random().toString().slice(2, 6),
      duration_ms: payload.duration_ms,
      cost_usd: payload.cost_usd,
      success: payload.success,
      result: payload.result,
      created_at: new Date().toISOString(),
      timestamp: new Date().toLocaleTimeString(),
    }
    state.value.history.push(step)
  }

  return {
    state,
    reset,
    resetFromTask,
    appendResult,
  }
}
