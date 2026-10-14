import { shallowRef } from 'vue'
import type { TaskCreateMode } from '../types'

export const TASK_CREATE_MODE_KEY = 'traceforge.task-create-mode'

export function useTaskCreateMode() {
  const mode = shallowRef<TaskCreateMode>('guided')
  try {
    if (localStorage.getItem(TASK_CREATE_MODE_KEY) === 'quick') mode.value = 'quick'
  } catch { /* Storage may be unavailable; creation still works. */ }

  function setMode(value: TaskCreateMode) {
    mode.value = value
    try { localStorage.setItem(TASK_CREATE_MODE_KEY, value) } catch { /* Keep the in-memory choice. */ }
  }
  return { mode, setMode }
}
