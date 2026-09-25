import type { RepositoryMapping } from './useLocalResources'
const key = (workspaceId: string, userId: string) => `local-repo-mappings:${location.origin}:${userId}:${workspaceId}`
export function readRepoPreferences(workspaceId: string, userId: string): RepositoryMapping[] {
  try { const value = JSON.parse(localStorage.getItem(key(workspaceId, userId)) || '[]'); return Array.isArray(value) ? value : [] }
  catch { return [] }
}
export function saveRepoPreferences(workspaceId: string, userId: string, mappings: RepositoryMapping[]) {
  localStorage.setItem(key(workspaceId, userId), JSON.stringify(mappings))
}
