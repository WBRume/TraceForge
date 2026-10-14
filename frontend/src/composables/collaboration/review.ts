import { changedFiles, collaborationFileKey, localFiles, manifestFiles } from './compare'
import type { CollaborationContext } from './useCollaborationPresentation'

export function collaborationReview(c: CollaborationContext, localAvailable: boolean, scope: 'cumulative' | 'round' = 'cumulative') {
  const cloudManifest = c.cloud || c.local?.target
  const inputManifest = c.input || (localAvailable ? c.local?.baseline : null)
  const baselineManifest = scope === 'cumulative' ? c.reviewBaseline : inputManifest
  const cloud = manifestFiles(cloudManifest), input = manifestFiles(inputManifest), baseline = manifestFiles(baselineManifest)
  const local = localAvailable ? localFiles(c.local) : manifestFiles(null)
  const received = manifestFiles(localAvailable ? c.local?.received || c.local?.baseline : null)
  const cloudChanges = cloudManifest && baselineManifest ? changedFiles(baseline, cloud) : []
  const localChanges = localAvailable && scope === 'round' ? changedFiles(received, local) : []
  const cloudKeys = new Set(cloudChanges.map(file => file.key)), localKeys = new Set(localChanges.map(file => file.key))
  const conflicts = localAvailable && scope === 'round' ? c.conflicts : []
  const conflictKeys = new Set(conflicts.map(file => collaborationFileKey(file.task_repository_id, file.path)))
  const all = new Map([...cloudChanges, ...localChanges].map(file => [file.key, file]))
  for (const file of conflicts) {
    const key = collaborationFileKey(file.task_repository_id, file.path)
    const content = file.cloud || file.local || file.base
    if (!all.has(key) && content) all.set(key, { ...content, path: file.path, key, task_repository_id: file.task_repository_id,
      repo_slug: c.state?.repositories.find(repo => repo.task_repository_id === file.task_repository_id)?.repo_slug || file.task_repository_id })
  }
  const files = [...all.values()].map(file => {
    const kind = conflictKeys.has(file.key) ? 'conflicts' : localKeys.has(file.key) ? 'local' : 'cloud'
    const left = kind === 'local' ? received.get(file.key) : kind === 'conflicts' && localAvailable ? local.get(file.key) : baseline.get(file.key)
    const right = kind === 'local' ? local.get(file.key) : cloud.get(file.key)
    const current = local.get(file.key)
    const delivered = localAvailable && current?.sha256 === right?.sha256 && current?.mode === right?.mode
    return { ...file, kind, left, right, delivered, statusLabel:scope === 'cumulative' && kind === 'cloud' ? '任务修改' : undefined,
      change: !right ? 'D' : !left ? 'A' : left.mode !== right.mode && left.sha256 === right.sha256 ? 'T' : 'M',
      cloudChanged: cloudKeys.has(file.key), localChanged: localKeys.has(file.key) }
  }).sort((a, b) => a.repo_slug.localeCompare(b.repo_slug) || a.path.localeCompare(b.path))
  return { files, local, cloud, input, received, cloudKnown: Boolean(cloudManifest && baselineManifest) }
}
export type CollaborationReviewFile = ReturnType<typeof collaborationReview>['files'][number]
