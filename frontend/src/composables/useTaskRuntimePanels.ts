export interface TaskRuntimeStatusCard {
  id: string
  type: 'status'
  status?: string | null
  message?: string | null
  model?: string | null
  created_at?: string | null
}

export interface TaskRuntimePanelSnapshot {
  statusCards: TaskRuntimeStatusCard[]
  thinkingContent: string
  showThinking: boolean
  thinkingExpanded: boolean
}

const cloneSnapshot = (snapshot: TaskRuntimePanelSnapshot): TaskRuntimePanelSnapshot => ({
  statusCards: snapshot.statusCards.map(card => ({ ...card })),
  thinkingContent: snapshot.thinkingContent,
  showThinking: snapshot.showThinking,
  thinkingExpanded: snapshot.thinkingExpanded,
})

/**
 * Keeps transient runtime panels isolated by task while the chat view stays mounted.
 * Server-side active-job state remains authoritative; callers clear stale snapshots
 * after an active-job refresh reports that execution has ended.
 */
export function useTaskRuntimePanels() {
  const snapshots = new Map<string, TaskRuntimePanelSnapshot>()

  const save = (taskId: string, snapshot: TaskRuntimePanelSnapshot) => {
    const normalizedTaskId = String(taskId || '').trim()
    if (!normalizedTaskId) return
    snapshots.set(normalizedTaskId, cloneSnapshot(snapshot))
  }

  const restore = (taskId: string): TaskRuntimePanelSnapshot | null => {
    const snapshot = snapshots.get(String(taskId || '').trim())
    return snapshot ? cloneSnapshot(snapshot) : null
  }

  const clear = (taskId: string) => {
    snapshots.delete(String(taskId || '').trim())
  }

  return { save, restore, clear }
}
