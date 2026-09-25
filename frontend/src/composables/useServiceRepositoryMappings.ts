import { ref } from 'vue'
import { useLocalAgentStore } from '@/stores/localAgent'
import { getSddDesktop } from '@/utils/runtime'
import { readRepoPreferences, saveRepoPreferences } from './localRepoPreferences'
import { remoteUrlsMatch } from './local-agent/localAgentUtils'
import type { RepositoryMapping } from './useLocalResources'

type WorkspaceRepo = { id: string; repository_id?: string; repo_url: string }

// Shared mappings are patch destinations; a service can keep its own directory.
export function useServiceRepositoryMappings(workspaceId: () => string, userId: () => string) {
  const localAgent = useLocalAgentStore()
  const repositories = ref<WorkspaceRepo[]>([])
  const preferences = ref<RepositoryMapping[]>([])
  const independent = ref<Record<string, boolean>>({})
  const desktopMappings = Boolean(getSddDesktop()?.config?.setRepoMapping)
  const remoteFor = (id: string) => repositories.value.find(r => (r.repository_id || r.id) === id)?.repo_url || ''
  function shared(id: string): RepositoryMapping | undefined {
    const remote = remoteFor(id)
    const local = localAgent.mappingFor(remote)
    if (local?.localPath) return { repository_id: id, configured_git_url: local.gitRemoteUrl || remote, local_path: local.localPath }
    if (!desktopMappings) return preferences.value.find(r => r.repository_id === id && r.local_path)
  }
  function initialize(repos: WorkspaceRepo[]) {
    repositories.value = repos
    preferences.value = readRepoPreferences(workspaceId(), userId())
    independent.value = {}
    return repos.map(r => {
      const id = r.repository_id || r.id
      return { ...(shared(id) || { repository_id: id, configured_git_url: r.repo_url, local_path: '' }) }
    })
  }
  function restore(mappings: RepositoryMapping[]) {
    independent.value = Object.fromEntries(mappings.map(r => {
      const sharedMapping = shared(r.repository_id)
      const usesSharedMapping = Boolean(sharedMapping && r.local_path === sharedMapping.local_path)
      if (usesSharedMapping && sharedMapping) r.configured_git_url = sharedMapping.configured_git_url
      else if (remoteUrlsMatch(r.configured_git_url, remoteFor(r.repository_id))) r.configured_git_url = ''
      return [r.repository_id, !usesSharedMapping]
    }))
  }
  function reuse(mapping: RepositoryMapping) {
    const source = shared(mapping.repository_id)
    if (!source) return
    mapping.configured_git_url = source.configured_git_url
    mapping.local_path = source.local_path
    independent.value[mapping.repository_id] = false
  }
  function setLocalPath(mapping: RepositoryMapping, path: string) {
    if (path !== mapping.local_path && remoteUrlsMatch(mapping.configured_git_url, remoteFor(mapping.repository_id))) {
      mapping.configured_git_url = ''
    }
    mapping.local_path = path
  }
  async function synchronize(mapping: RepositoryMapping) {
    if (!mapping.local_path.trim() || !mapping.configured_git_url.trim()) throw new Error('请先填写仓库 Git 地址和本机目录')
    if (shared(mapping.repository_id)) throw new Error('已有本地仓库映射，请在本地仓库映射设置中修改')
    if (desktopMappings) {
      if (!await localAgent.saveMappingFor(remoteFor(mapping.repository_id), mapping.local_path, null, mapping.configured_git_url)) throw new Error('同步本地仓库映射失败，请检查目录')
    } else {
      const next = preferences.value.filter(r => r.repository_id !== mapping.repository_id)
      next.push({ ...mapping })
      saveRepoPreferences(workspaceId(), userId(), next)
      preferences.value = next
    }
    independent.value[mapping.repository_id] = false
  }
  return { shared, independent, initialize, restore, reuse, setLocalPath, synchronize, workspaceRemoteFor: remoteFor, defaults: () => initialize(repositories.value) }
}
