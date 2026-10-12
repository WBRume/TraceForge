import type { CollaborationFile, CollaborationManifest, LocalCollaborationStatus } from '@/types/collaboration'

export const collaborationFileKey = (repository: string, path: string) => JSON.stringify([repository, path])
export function manifestFiles(manifest?: CollaborationManifest | null) {
  const result = new Map<string, CollaborationFile & { task_repository_id: string; repo_slug: string }>()
  for (const repo of manifest?.repositories || []) {
    for (const file of repo.files) result.set(collaborationFileKey(repo.task_repository_id, file.path), { ...file, task_repository_id: repo.task_repository_id, repo_slug: repo.repo_slug })
  }
  return result
}
export function localFiles(status: LocalCollaborationStatus | null) {
  const result = manifestFiles(status?.manifest || status?.baseline)
  for (const change of status?.local_changes || []) {
    const key = collaborationFileKey(change.task_repository_id, change.path)
    if (!change.local) result.delete(key)
    else result.set(key, { ...change.local, task_repository_id: change.task_repository_id, repo_slug: status?.repositories?.find(repo => repo.task_repository_id === change.task_repository_id)?.repo_slug || change.task_repository_id })
  }
  return result
}
export function changedFiles(left: ReturnType<typeof manifestFiles>, right: ReturnType<typeof manifestFiles>) {
  return [...new Set([...left.keys(), ...right.keys()])].filter(key => {
    const a = left.get(key), b = right.get(key)
    return a?.sha256 !== b?.sha256 || a?.mode !== b?.mode
  }).map(key => ({ key, ...(right.get(key) || left.get(key))! }))
}
