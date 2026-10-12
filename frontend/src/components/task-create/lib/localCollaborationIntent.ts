const key = (workspaceId: string, taskId: string) => `traceforge.collaboration.intent:${workspaceId}:${taskId}`
export function rememberCollaborationIntent(workspaceId: string, taskId: string) {
  localStorage.setItem(key(workspaceId, taskId), 'review')
}
export function consumeCollaborationIntent(workspaceId: string, taskId: string): boolean {
  if (localStorage.getItem(key(workspaceId, taskId)) !== 'review') return false
  localStorage.removeItem(key(workspaceId, taskId))
  return true
}
