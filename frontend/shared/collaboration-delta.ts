/** Delta manifests retain the full repository identity, but carry only changed paths. */
type File = { path: string; sha256: string; size: number; mode: string }
type Repository = { task_repository_id: string; files: File[]; deleted?: string[] }
type Manifest = { task_id: string; snapshot_id: string; repository_set_digest: string; repositories: Repository[]; delta?: { base_snapshot_id: string } }
const equal = (a?: File, b?: File) => a?.sha256 === b?.sha256 && a?.mode === b?.mode && a?.size === b?.size

export function manifestDelta<T extends Manifest>(base: T, target: T): T {
  if (base.task_id !== target.task_id || base.repository_set_digest !== target.repository_set_digest) return target
  return { ...target, delta: { base_snapshot_id: base.snapshot_id }, repositories: target.repositories.map(repo => {
    const before = new Map(base.repositories.find(item => item.task_repository_id === repo.task_repository_id)?.files.map(file => [file.path, file]))
    const now = new Set(repo.files.map(file => file.path))
    return { ...repo, files: repo.files.filter(file => !equal(file, before.get(file.path))), deleted: [...before.keys()].filter(name => !now.has(name)) }
  }) }
}

export function expandManifest<T extends Manifest>(base: T | null | undefined, incoming: T): T {
  if (!incoming.delta) return incoming
  if (!base || base.snapshot_id !== incoming.delta.base_snapshot_id || base.task_id !== incoming.task_id
    || base.repository_set_digest !== incoming.repository_set_digest || base.repositories.length !== incoming.repositories.length) throw new Error('COLLABORATION_DELTA_BASE_MISMATCH')
  const seen = new Set<string>()
  const repositories = incoming.repositories.map(repo => {
    const previous = base.repositories.find(item => item.task_repository_id === repo.task_repository_id)
    if (!previous || seen.has(repo.task_repository_id)) throw new Error('COLLABORATION_DELTA_REPOSITORY_MISMATCH')
    seen.add(repo.task_repository_id)
    const old = previous as unknown as Record<string, unknown>, next = repo as unknown as Record<string, unknown>
    for (const key of ['repository_id', 'repo_url', 'repo_slug', 'rel_path', 'branch_name', 'base_commit_sha']) {
      if (old[key] !== next[key]) throw new Error('COLLABORATION_DELTA_REPOSITORY_MISMATCH')
    }
    const files = new Map(previous.files.map(file => [file.path, file])), touched = new Set<string>()
    for (const name of repo.deleted || []) {
      if (touched.has(name) || !files.has(name)) throw new Error('COLLABORATION_DELTA_PATH_MISMATCH')
      touched.add(name); files.delete(name)
    }
    for (const file of repo.files) {
      if (touched.has(file.path)) throw new Error('COLLABORATION_DELTA_PATH_MISMATCH')
      touched.add(file.path); files.set(file.path, file)
    }
    const { deleted: _deleted, ...metadata } = repo
    return { ...metadata, files: [...files.values()] }
  })
  const { delta: _delta, ...metadata } = incoming
  return { ...metadata, repositories } as T
}

const fields = ['manifest', 'baseline', 'target', 'received', 'preview'] as const
export function statusDelta(previous: Record<string, any> | undefined, current: Record<string, any>, token: string, baseToken?: string) {
  const bases: Record<string, string> = {}
  const result: Record<string, any> = { ...current, transport: { token, base_token: previous ? baseToken : undefined, bases } }
  if (previous) for (const field of fields) if (current[field]) {
    const base = previous[field] ? field : previous.baseline ? 'baseline' : undefined
    if (base) { result[field] = manifestDelta(previous[base], current[field]); bases[field] = base }
  }
  return result
}
export function expandStatus<T extends Record<string, any>>(previous: T | null | undefined, incoming: T): T {
  if (incoming.transport?.base_token && incoming.transport.base_token !== previous?.transport?.token) throw new Error('COLLABORATION_STATUS_BASE_MISMATCH')
  const result = { ...incoming }
  for (const field of fields) if (incoming[field]) (result as Record<string, any>)[field] = expandManifest(previous?.[incoming.transport?.bases?.[field] || field], incoming[field])
  return result
}
