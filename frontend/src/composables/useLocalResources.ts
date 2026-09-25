import { ref } from 'vue'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'

export type TaskExecution = { location: 'SERVER' | 'LOCAL'; resource_id?: string; profile_revision?: number }
export type RepositoryMapping = { repository_id: string; local_path: string; configured_git_url: string }
export type ResourceDraft = {
  name: string; backend: 'opencode' | 'dsh'; service_url: string; resource_service_url: string
  workspace_root: string; repositories: RepositoryMapping[]
  host_token?: string; agent_token?: string; agent_username?: string
}
export type LocalResource = Omit<ResourceDraft, 'repositories' | 'host_token' | 'agent_token'> & {
  id: string; profile_revision: number; repositories_json: RepositoryMapping[]
}

export function useLocalResources(workspaceId: () => string) {
  const items = ref<LocalResource[]>([])
  const enabled = ref(false)
  const busy = ref(false)
  const error = ref('')
  let sequence = 0
  const base = () => `/workspaces/${workspaceId()}/local-resources`
  async function load() {
    const current = ++sequence
    if (!workspaceId()) return
    try {
      const { data } = await api.get(base())
      if (current !== sequence) return
      items.value = data.items
      enabled.value = data.enabled
    } catch (e) { if (current === sequence) error.value = formatApiError(e, '本地资源请求失败') }
  }
  async function save(draft: ResourceDraft, id?: string): Promise<LocalResource | undefined> {
    busy.value = true
    error.value = ''
    try {
      const { data } = id ? await api.put(`${base()}/${id}`, draft) : await api.post(base(), draft)
      await load()
      return data
    } catch (e) { error.value = formatApiError(e, '本地资源请求失败') }
    finally { busy.value = false }
  }
  return { items, enabled, busy, error, load, save }
}
