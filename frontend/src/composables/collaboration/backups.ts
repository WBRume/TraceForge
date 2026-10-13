import type { CollaborationBackup } from '@/types/collaboration'

type BackupRepository = { id: string; name: string; entries: CollaborationBackup[]; repeatedPaths: Set<string> }
type BackupRound = {
  id: string; context?: CollaborationBackup['context']; createdAt?: string; repositories: BackupRepository[]
}

const timestamp = (value?: string) => value ? Date.parse(value) || 0 : 0
const latest = (left?: string, right?: string) => timestamp(right) > timestamp(left) ? right : left

/** Legacy receipts stay separate; current task state cannot identify a historical backup's round. */
export function groupCollaborationBackups(entries: CollaborationBackup[], repositoryName: (id: string) => string): BackupRound[] {
  const rounds = new Map<string, BackupRound>()
  for (const entry of entries) {
    const context = entry.context
    const id = context?.session_turn_id ? `turn:${context.session_turn_id}`
      : context?.snapshot_id ? `snapshot:${context.snapshot_id}` : `operation:${entry.operation_id}`
    let round = rounds.get(id)
    if (!round) { round = { id, context, createdAt: entry.created_at, repositories: [] }; rounds.set(id, round) }
    round.createdAt = latest(round.createdAt, entry.created_at)
    let repo = round.repositories.find(item => item.id === entry.task_repository_id)
    if (!repo) {
      repo = { id: entry.task_repository_id, name: context?.repo_slug || repositoryName(entry.task_repository_id), entries: [], repeatedPaths: new Set() }
      round.repositories.push(repo)
    }
    if (repo.entries.some(item => item.path === entry.path)) repo.repeatedPaths.add(entry.path)
    repo.entries.push(entry)
  }
  const result = [...rounds.values()]
  for (const round of result) for (const repo of round.repositories) repo.entries.sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at))
  return result.sort((a, b) => timestamp(b.context?.turn_created_at || b.createdAt) - timestamp(a.context?.turn_created_at || a.createdAt)
    || (b.context?.workspace_revision ?? -1) - (a.context?.workspace_revision ?? -1))
}
