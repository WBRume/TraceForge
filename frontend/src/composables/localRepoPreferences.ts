import type { RepositoryMapping } from './useLocalResources'
import type { SddDesktopApi } from '@/types/sddDesktop'
import { remoteUrlsMatch } from './local-agent/localAgentUtils'
const key = (workspaceId: string, userId: string) => `local-repo-mappings:${location.origin}:${userId}:${workspaceId}`
const changedEvent = 'traceforge:repo-mappings-changed'
export function readRepoPreferences(workspaceId: string, userId: string): RepositoryMapping[] {
  try { const value = JSON.parse(localStorage.getItem(key(workspaceId, userId)) || '[]'); return Array.isArray(value) ? value : [] }
  catch { return [] }
}

export async function loadLocalRepoMapping(
  config: SddDesktopApi['config'] | undefined,
  workspaceId: string,
  repo: { repository_id: string; repo_url: string },
  preferences: RepositoryMapping[],
) {
  const stored = await config?.getRepoMapping?.({ workspaceId, remoteUrl: repo.repo_url })
  const preference = preferences.find(row => (repo.repository_id && row.repository_id === repo.repository_id)
    || remoteUrlsMatch(row.configured_git_url, repo.repo_url))
  if (stored?.localPath?.trim()) {
    return { local_path: stored.localPath, configured_git_url: stored.gitRemoteUrl || preference?.configured_git_url || repo.repo_url }
  }
  if (preference?.local_path?.trim()) {
    return { local_path: preference.local_path, configured_git_url: stored?.gitRemoteUrl || preference.configured_git_url || repo.repo_url }
  }
}

export function saveRepoPreferences(workspaceId: string, userId: string, mappings: RepositoryMapping[]) {
  const storageKey = key(workspaceId, userId), value = JSON.stringify(mappings)
  if (localStorage.getItem(storageKey) === value) return
  localStorage.setItem(storageKey, value)
  window.dispatchEvent(new CustomEvent(changedEvent, { detail: storageKey }))
}

/** Observe settings saved in this renderer or another window, scoped to the owner/workspace. */
export function onRepoPreferencesChanged(workspaceId: string, userId: string, listener: () => void) {
  const storageKey = key(workspaceId, userId)
  const changed = (event: Event) => { if ((event as CustomEvent<string>).detail === storageKey) listener() }
  const stored = (event: StorageEvent) => { if (event.storageArea === localStorage && (event.key === storageKey || event.key === null)) listener() }
  window.addEventListener(changedEvent, changed)
  window.addEventListener('storage', stored)
  return () => { window.removeEventListener(changedEvent, changed); window.removeEventListener('storage', stored) }
}
