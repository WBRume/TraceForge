import { changedFiles, collaborationFileKey, localFiles, manifestFiles } from './compare'
import type { CollaborationContext } from './useCollaborationPresentation'
import type { CollaborationReviewDiff, CollaborationReviewScope } from '@/types/collaboration'

const byPath = (a: { repo_slug: string; path: string }, b: { repo_slug: string; path: string }) =>
  a.repo_slug.localeCompare(b.repo_slug) || a.path.localeCompare(b.path)

/** Both scopes arrive as a server-computed change set; only changed files travel. */
function diffFiles(
  diff: CollaborationReviewDiff | null | undefined,
  local: ReturnType<typeof manifestFiles>,
  localAvailable: boolean,
  statusLabel: string,
) {
  if (!diff) return null
  const files = diff.files.map(entry => {
    const key = collaborationFileKey(entry.task_repository_id, entry.path)
    const current = local.get(key)
    const delivered = localAvailable && Boolean(entry.right) && current?.content_sha256 === entry.right?.content_sha256
      && current?.mode === entry.right?.mode
    return {
      path: entry.path, key, repo_slug: entry.repo_slug, task_repository_id: entry.task_repository_id,
      sha256: (entry.right || entry.left)!.sha256, content_sha256: (entry.right || entry.left)!.content_sha256,
      size: (entry.right || entry.left)!.size, mode: (entry.right || entry.left)!.mode,
      kind: 'cloud' as const, left: entry.left, right: entry.right, delivered, statusLabel,
      change: entry.change, cloudChanged: true, localChanged: false,
    }
  }).sort(byPath)
  // Only listed files can be selected, so per-file maps need just these entries.
  const cloud = new Map<string, NonNullable<(typeof files)[number]['right']>>()
  const base = new Map<string, NonNullable<(typeof files)[number]['left']>>()
  for (const file of diff.files) {
    const key = collaborationFileKey(file.task_repository_id, file.path)
    if (file.right) cloud.set(key, file.right)
    if (file.left) base.set(key, file.left)
  }
  return { files, cloud, base }
}

function receivedDiff(c: CollaborationContext): CollaborationReviewDiff | null {
  if (!c.cloud) return null
  const base = manifestFiles(c.input)
  const cloud = manifestFiles(c.cloud)
  return {
    scope: 'round', baseline_snapshot_id: c.input?.snapshot_id || null, cloud_snapshot_id: c.cloud.snapshot_id,
    protocol_version: c.cloud.protocol_version, repositories: c.cloud.repositories, running: false,
    files: changedFiles(base, cloud).map(file => ({ ...file,
      change: !cloud.has(file.key) ? 'D' : !base.has(file.key) ? 'A' : 'M',
      left: base.get(file.key) ?? null, right: cloud.get(file.key) ?? null,
    })),
  }
}

export function collaborationReview(c: CollaborationContext, localAvailable: boolean, scope: CollaborationReviewScope, cloudDiff: CollaborationReviewDiff | null) {
  const local = localAvailable ? localFiles(c.local) : manifestFiles(null)
  const received = manifestFiles(localAvailable ? c.local?.received || c.local?.baseline : null)
  const conflicts = localAvailable && scope === 'round' ? c.conflicts : []
  const conflictKeys = new Set(conflicts.map(file => collaborationFileKey(file.task_repository_id, file.path)))
  const diff = scope === 'round' && c.receivedOnce && !c.participating ? receivedDiff(c) : cloudDiff
  const changes = diffFiles(diff, local, localAvailable, scope === 'cumulative' ? '任务修改' : '本轮修改')

  const localChanges = (localAvailable && scope === 'round' ? changedFiles(received, local) : []).map(file => ({
    ...file, left: received.get(file.key) ?? null, right: local.get(file.key) ?? null, statusLabel: undefined as string | undefined,
  }))
  const localKeys = new Set(localChanges.map(file => file.key))
  const all = new Map([...(changes?.files || []), ...localChanges].map(file => [file.key, file]))
  for (const file of conflicts) {
    const key = collaborationFileKey(file.task_repository_id, file.path)
    const content = file.cloud || file.local || file.base
    if (!all.has(key) && content) all.set(key, { ...content, path: file.path, key, task_repository_id: file.task_repository_id,
      repo_slug: c.state?.repositories.find(repo => repo.task_repository_id === file.task_repository_id)?.repo_slug || file.task_repository_id,
      left: null, right: null, statusLabel: undefined as string | undefined })
  }
  const files = [...all.values()].map(file => {
    const kind = conflictKeys.has(file.key) ? 'conflicts' : localKeys.has(file.key) ? 'local' : 'cloud'
    const left = kind === 'local' ? received.get(file.key) : kind === 'conflicts' && localAvailable ? local.get(file.key) : file.left
    const right = kind === 'local' ? local.get(file.key) : file.right
    const current = local.get(file.key)
    const delivered = localAvailable && current?.content_sha256 === right?.content_sha256 && current?.mode === right?.mode
    return { ...file, kind, left, right, delivered, statusLabel: kind === 'cloud' ? file.statusLabel : undefined,
      change: !right ? 'D' : !left ? 'A' : left.mode !== right.mode && left.content_sha256 === right.content_sha256 ? 'T' : 'M',
      cloudChanged: kind === 'cloud', localChanged: localKeys.has(file.key) }
  }).sort(byPath)
  return { files, local, cloud: changes?.cloud || manifestFiles(null), input: changes?.base || manifestFiles(null),
    received, conflictFiles: conflicts, conflictKeys, cloudKnown: Boolean(diff) }
}
export type CollaborationReviewFile = ReturnType<typeof collaborationReview>['files'][number]
