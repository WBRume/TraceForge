import type { RepositoryMapping } from './useLocalResources'
const key = (workspaceId: string, userId: string) => `local-repo-mappings:${location.origin}:${userId}:${workspaceId}`
const changedEvent = 'traceforge:repo-mappings-changed'
export function readRepoPreferences(workspaceId: string, userId: string): RepositoryMapping[] {
  try { const value = JSON.parse(localStorage.getItem(key(workspaceId, userId)) || '[]'); return Array.isArray(value) ? value : [] }
  catch { return [] }
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
