import api from '@/utils/api'

export type UpdateState = 'PREPARING' | 'READY' | 'CONFLICTS' | 'ADAPTING' | 'ADAPT_FAILED' | 'APPLYING' | 'APPLIED' | 'FAILED' | 'RECOVERY_REQUIRED'
export type VersionName = 'base' | 'task' | 'remote' | 'result'
export interface CodeVersion { exists: boolean; text: string; binary: boolean; mode: string | null }
export interface UpdateFile { path: string; conflict: boolean; was_conflict: boolean; resolved: boolean }
export interface UpdateRepository {
  id: string; name: string; branch: string; baseline: string; base: string; target: string
  has_output: boolean; mode: 'MERGE' | 'ADAPTED'; files: UpdateFile[]
}
export interface UpdatePlan {
  id: string; version: number; state: UpdateState; repositories: UpdateRepository[]
  error?: string | null; job_id?: string; agent_summary?: string; storage_missing?: boolean
}
export interface UpdateSummary {
  can_update?: boolean
  repositories: { id: string; name: string; branch: string; baseline: string; creation_baseline: string }[]
  plan: UpdatePlan | null
}
export interface UpdateFileDetail extends UpdateFile { versions: Record<VersionName, CodeVersion>; version: number }

export function repositoryUpdatesApi(workspaceId: string, taskId: string) {
  const base = `/workspaces/${encodeURIComponent(workspaceId)}/tasks/${encodeURIComponent(taskId)}/repository-updates`
  return {
    get: async (): Promise<UpdateSummary> => (await api.get(base)).data,
    prepare: async (): Promise<UpdatePlan> => (await api.post(`${base}/prepare`, {}, { timeout: 600000 })).data,
    command: async (action: string, plan: UpdatePlan, extra: Record<string, unknown> = {}): Promise<UpdatePlan> => (
      await api.post(`${base}/${action}`, { operation_id: plan.id, version: plan.version, ...extra }, { timeout: 600000 })
    ).data,
    file: async (plan: UpdatePlan, repositoryId: string, path: string, signal: AbortSignal): Promise<UpdateFileDetail> => (
      await api.get(`${base}/file`, { params: { operation_id: plan.id, repository_id: repositoryId, path }, signal })
    ).data,
  }
}

type UpdateEvent = { id?: string; task_id?: string; state?: string; version?: number; job_status?: string }
const subscribers = new Set<(event: UpdateEvent) => void>()
export function notifyRepositoryUpdate(event: UpdateEvent) { subscribers.forEach(handler => handler(event)) }
export function subscribeRepositoryUpdates(handler: (event: UpdateEvent) => void) {
  subscribers.add(handler)
  return () => { subscribers.delete(handler) }
}
