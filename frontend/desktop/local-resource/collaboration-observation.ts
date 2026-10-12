import { localFile, type LocalRepository, type SyncFile, type SyncManifest, type SyncObjects } from './collaboration-store'

/** Read only delivery candidates. Git's stat cache is never an overwrite precondition. */
export function observeFile(repo: LocalRepository, name: string, objects: SyncObjects, mode?: SyncFile['mode']) {
  let file: SyncFile | null
  try { file = localFile(repo.local_worktree_path, name, objects) }
  catch (error) {
    if (String(error).includes('COLLABORATION_PATH_STRUCTURE_CONFLICT')) return null
    throw error
  }
  if (file && mode && process.platform === 'win32') file.mode = mode
  return file
}

export function updateObservation(manifest: SyncManifest, repoId: string, name: string, file: SyncFile | null) {
  const repo = manifest.repositories.find(item => item.task_repository_id === repoId)!
  const files = new Map(repo.files.map(item => [item.path, item]))
  if (file) files.set(name, file); else files.delete(name)
  repo.files = [...files.values()]
}
