import * as fs from 'node:fs'
import * as path from 'node:path'
import { randomUUID } from 'node:crypto'
import { expandManifest, manifestDelta, statusDelta } from '../../shared/collaboration-delta'
import { child, fail, git, hash, inside, inspectRepo, readJson, resolved } from './filesystem'
import { applyFile, type BackupContext } from './collaboration-write'
import { CollaborationIndex } from './collaboration-index'
import { observeFile, updateObservation } from './collaboration-observation'
import { prepareTaskWorktree } from './collaboration-prepare'
import { inspectMappedRepositories, requireCleanMappings } from './collaboration-mapped'
import { initializeMapped } from './collaboration-initialize'
import {
  durableJson, fileKey, identifier, repositoryFileModes, sameFile, syncPath, SyncObjects, validateFileMode, validateRepositoryIdentity,
  type SyncBinding, type SyncConflict, type SyncFile, type SyncManifest, type LocalRepository,
} from './collaboration-store'

export class CollaborationRuntime {
  readonly objects: SyncObjects
  readonly index: CollaborationIndex
  readonly state: string
  readonly roots: () => string[]
  private readonly observations = new Map<string, SyncManifest>()
  private readonly transports = new Map<string, { token: string; status: Record<string, any> }>()
  constructor(state: string, roots: () => string[]) {
    this.state = state; this.roots = roots
    this.objects = new SyncObjects(state)
    this.index = new CollaborationIndex()
  }
  private bindingFile(task: string) { return path.join(this.state, 'bindings', identifier(task) + '.json') }
  private load(task: string, allowReleased = false): SyncBinding {
    const binding = this.findBinding(task)
    if (!binding) return fail('COLLABORATION_BINDING_MISSING')
    if (binding.released && !allowReleased) fail('COLLABORATION_BINDING_MISSING: binding released')
    return binding
  }
  private findBinding(task: string): SyncBinding | null {
    const file = this.bindingFile(task)
    let binding: SyncBinding
    try { binding = readJson<SyncBinding>(file) }
    catch (error: any) { if (error.code === 'ENOENT' && error.path === file) return null; throw error }
    if (inside(binding.task_root, binding.directory_mode === 'MAPPED' ? [this.state] : this.roots()) !== binding.task_root) fail('COLLABORATION_DIRECTORY_IDENTITY_CHANGED')
    for (const repo of binding.repositories) if (inside(repo.local_worktree_path, binding.directory_mode === 'MAPPED' ? this.roots() : [binding.task_root]) !== repo.local_worktree_path
      || (binding.directory_mode === 'MAPPED' && repo.local_worktree_path !== repo.mapped_repo_root)) fail('COLLABORATION_DIRECTORY_IDENTITY_CHANGED')
    return binding
  }
  private scratch(binding: SyncBinding, repo?: LocalRepository) {
    if (binding.directory_mode === 'MAPPED' && !repo?.git_dir) fail('COLLABORATION_REPOSITORY_IDENTITY_CHANGED')
    const root = binding.directory_mode === 'MAPPED' ? repo!.git_dir! : binding.task_root
    const directory = path.join(root, '.traceforge-sync')
    if (fs.existsSync(directory) && fs.lstatSync(directory).isSymbolicLink()) fail('COLLABORATION_BACKUP_DIRECTORY_LINKED')
    return child(root, '.traceforge-sync')
  }
  private save(binding: SyncBinding) { durableJson(this.bindingFile(binding.task_id), binding) }
  async executeAsync(kind: string, payload: any) {
    if (['status', 'capture', 'prepare', 'reconcile', 'accept_input'].includes(kind)) await this.index.flush(payload.task_id)
    return this.execute(kind, payload)
  }
  execute(kind: string, payload: any): any {
    if (payload.target?.delta) payload = { ...payload, target: expandManifest(this.load(payload.task_id).baseline, payload.target) }
    const result = this.dispatch(kind, payload)
    if (!payload.delta_transport) { if (kind === 'capture') delete result.transfer_manifest; return result }
    const status = kind === 'capture' ? result.status : result
    if (!status?.task_id || !status.state) return result
    const previous = this.transports.get(status.task_id), token = randomUUID()
    const wire = statusDelta(previous && previous.token === payload.status_token ? previous.status : undefined, status, token, previous?.token)
    this.transports.set(status.task_id, { token, status })
    if (kind === 'capture') { const { transfer_manifest, ...capture } = result; return { ...capture, manifest: payload.manifest_delta === false ? result.manifest : transfer_manifest || result.manifest, status: wire } }
    return wire
  }
  private dispatch(kind: string, payload: any): any {
    this.index.beginOperation()
    if (['prepare', 'capture', 'reconcile', 'restore', 'accept_input'].includes(kind)) {
      const binding = this.findBinding(payload.task_id)
      if (binding?.initialization && !binding.initialization.receipt) fail('COLLABORATION_INITIALIZATION_PENDING')
      if (binding && payload.target?.session_generation < binding.metadata.session_generation) fail('COLLABORATION_SESSION_CHANGED')
      if (binding && payload.session_generation !== undefined && payload.session_generation < binding.metadata.session_generation) fail('COLLABORATION_SESSION_CHANGED')
    }
    switch (kind) {
      case 'initialize': return this.initialize(payload)
      case 'inspect_mappings': { const { repositories: _bound, ...result } = inspectMappedRepositories(payload.repositories, this.roots()); return result }
      case 'prepare': return this.prepare(payload)
      case 'release': return this.release(payload)
      case 'suspend': return this.release({ ...payload, suspend: true })
      case 'binding': return payload.optional === true ? this.findBinding(payload.task_id) : this.load(payload.task_id, true)
      case 'cache_objects': return this.objects.receive(payload.objects)
      case 'read_object': {
        const data = payload.optional === true ? this.objects.git.find(payload.sha256) : this.objects.get(payload.sha256)
        return data === null ? null : { sha256: payload.sha256, content: data.toString('base64') }
      }
      case 'missing_objects': return { missing: this.objects.git.check((payload.sha256 as string[]).map(sha256 => ({ sha256 }))) }
      case 'status': return this.status(this.load(payload.task_id), undefined, payload.background !== true || payload.verify === true, payload.verify_raw === true)
      case 'capture': return this.capture(payload)
      case 'accept_input': return this.acceptInput(payload)
      case 'backups': return this.listBackups(payload.task_id)
      case 'reconcile': return this.reconcile(payload)
      case 'restore': return this.restore(payload)
      default: fail('UNSUPPORTED_COLLABORATION_OPERATION')
    }
  }
  private initialize(payload: any) {
    const binding = this.load(payload.task_id, true)
    const reused = initializeMapped(binding, payload, () => this.save(binding))
    if (reused) return reused
    this.index.close(binding.task_id)
    this.observations.delete(binding.task_id); this.transports.delete(binding.task_id)
    binding.baseline = this.scan(binding)
    binding.initialization!.receipt = { task_id: binding.task_id, operation_id: payload.operation_id,
      binding_id: binding.binding_id, repositories: binding.repositories.map(repo => ({
        task_repository_id: repo.task_repository_id, head: repo.base_commit_sha, clean: true,
      })) }
    this.save(binding)
    return binding.initialization!.receipt
  }
  private prepare(payload: any) {
    identifier(payload.task_id); identifier(payload.binding_id)
    if (payload.directory_mode === 'MAPPED') return this.prepareMapped(payload)
    if (!Array.isArray(payload.repositories) || !payload.repositories.length || payload.repositories.length > 100) fail('COLLABORATION_REPOSITORIES_REQUIRED')
    const taskRoot = child(inside(payload.workspace_root, this.roots()), payload.task_id)
    const inputs = payload.repositories as LocalRepository[]
    const ids = new Set<string>(), mounts: string[] = []
    for (const repo of inputs) {
      identifier(repo.task_repository_id)
      syncPath(repo.rel_path)
      const mount = repo.rel_path.toLowerCase()
      if (ids.has(repo.task_repository_id) || mounts.some(other => other === mount || other.startsWith(mount + '/') || mount.startsWith(other + '/'))) fail('COLLABORATION_REPOSITORY_OVERLAP')
      ids.add(repo.task_repository_id); mounts.push(mount)
      if (!/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(repo.base_commit_sha)) fail('COLLABORATION_BASE_COMMIT_REQUIRED')
    }
    let binding: SyncBinding
    if (fs.existsSync(this.bindingFile(payload.task_id))) {
      binding = this.load(payload.task_id)
      if (binding.task_root !== taskRoot) fail('COLLABORATION_BINDING_CONFLICT')
      const rebinding = binding.binding_id !== payload.binding_id
      if (rebinding && (payload.previous_binding_id !== binding.binding_id || binding.target || binding.conflicts.length || binding.errors.length)) fail('COLLABORATION_BINDING_CONFLICT')
      if (JSON.stringify([...binding.expected_repository_ids].sort()) !== JSON.stringify(inputs.map(repo => repo.task_repository_id).sort())) fail('COLLABORATION_REPOSITORY_SET_MISMATCH')
      if (binding.repositories.length && binding.repositories.some(repo => !inputs.some(input => input.task_repository_id === repo.task_repository_id
        && input.base_commit_sha === repo.base_commit_sha && input.rel_path === repo.rel_path
        && resolved(input.local_path) === repo.mapped_repo_root))) fail('COLLABORATION_BINDING_CONFLICT')
      if (rebinding) { binding.binding_id = payload.binding_id; this.save(binding) }
    } else {
      if (fs.existsSync(taskRoot) && fs.readdirSync(taskRoot).length) fail('COLLABORATION_DIRECTORY_ALREADY_EXISTS')
      fs.mkdirSync(taskRoot, { recursive: true })
      binding = { task_id: payload.task_id, binding_id: payload.binding_id, task_root: taskRoot,
        expected_repository_ids: inputs.map(repo => repo.task_repository_id),
        repositories: [], baseline: null, target: null, conflicts: [], conflict_set_id: null, applied: {}, errors: [],
        metadata: { protocol_version: 1, task_id: payload.task_id, snapshot_id: '', workspace_revision: payload.workspace_revision ?? 0,
          session_generation: payload.session_generation, session_revision: payload.session_revision,
          repository_set_digest: payload.repository_set_digest, source: 'INITIAL' } }
      this.save(binding)
    }
    for (const input of inputs) {
      if (binding.repositories.some(repo => repo.task_repository_id === input.task_repository_id)) continue
      const info = inspectRepo(input.local_path, input.configured_git_url || input.repo_url, this.roots())
      try { git(info.repo_root, 'cat-file', '-e', input.base_commit_sha + '^{commit}') }
      catch {
        git(info.repo_root, 'fetch', '--no-tags', info.matched_remote, input.base_commit_sha)
        git(info.repo_root, 'cat-file', '-e', input.base_commit_sha + '^{commit}')
      }
      const target = child(taskRoot, input.rel_path), branch = `traceforge/sync/${payload.task_id}/${input.task_repository_id}`
      prepareTaskWorktree({ state: this.state, task_id: payload.task_id, task_repository_id: input.task_repository_id,
        target, branch, base_commit_sha: input.base_commit_sha, repo_root: info.repo_root, common_git_dir: info.common_git_dir })
      binding.repositories.push({ ...input, files: [], mapped_repo_root: info.repo_root, local_worktree_path: target,
        common_git_dir: info.common_git_dir, task_branch: branch })
      this.save(binding)
    }
    if (!binding.baseline) {
      binding.baseline = this.scan(binding)
      this.save(binding)
      return this.status(binding, binding.baseline)
    }
    return this.status(binding)
  }
  private prepareMapped(payload: any) {
    const file = this.bindingFile(payload.task_id)
    const previous = fs.existsSync(file) ? readJson<SyncBinding>(file) : null
    if (previous?.directory_mode === 'MAPPED' && (!previous.released || previous.suspended) && previous.baseline
      && (previous.binding_id === payload.binding_id || (previous.suspended && payload.previous_binding_id === previous.binding_id))) {
      if (previous.repositories.length !== payload.repositories.length || previous.repositories.some(repo => !payload.repositories.some((input: LocalRepository) =>
        input.task_repository_id === repo.task_repository_id && resolved(input.local_path) === repo.mapped_repo_root
        && input.base_commit_sha === repo.base_commit_sha && input.rel_path === repo.rel_path && input.branch_name === repo.branch_name))) fail('COLLABORATION_BINDING_CONFLICT')
      this.requireUnoccupied(payload.task_id, previous.repositories)
      // The Git cut validates each repository before the binding is reactivated.
      const local = this.scan(this.load(payload.task_id, true))
      previous.released = false; previous.suspended = false; previous.binding_id = payload.binding_id
      this.save(previous)
      return this.status(previous, local)
    }
    const repositories = requireCleanMappings(payload.repositories, this.roots())
    this.requireUnoccupied(payload.task_id, repositories)
    if (previous && (previous.target || previous.conflicts.length || Object.keys(previous.applied).length)) fail('COLLABORATION_DELIVERY_REQUIRED')
    if (previous && !previous.released && previous.binding_id !== payload.binding_id && payload.previous_binding_id !== previous.binding_id) fail('COLLABORATION_BINDING_CONFLICT')
    const binding: SyncBinding = { task_id: payload.task_id, binding_id: payload.binding_id, directory_mode: 'MAPPED',
      task_root: path.join(this.state, 'mapped-tasks', payload.task_id), repositories,
      expected_repository_ids: repositories.map(repo => repo.task_repository_id), baseline: null, target: null,
      conflicts: [], conflict_set_id: null, applied: {}, errors: [],
      metadata: { protocol_version: 1, task_id: payload.task_id, snapshot_id: '', workspace_revision: payload.workspace_revision ?? 0,
        session_generation: payload.session_generation, session_revision: payload.session_revision,
        repository_set_digest: payload.repository_set_digest, source: 'INITIAL' } }
    const baseline = this.scan(binding)
    // Refuse edits or branch changes arriving during first capture; no source files have been written.
    requireCleanMappings(payload.repositories, this.roots())
    repositories.forEach(validateRepositoryIdentity)
    binding.baseline = baseline
    if (previous) durableJson(path.join(this.state, 'previous-bindings', payload.task_id + '-' + randomUUID() + '.json'), previous)
    this.save(binding)
    return this.status(binding, baseline)
  }
  close() { this.index.close() }
  private requireUnoccupied(taskId: string, repositories: LocalRepository[]) {
    for (const other of this.bindings()) if (!other.released && other.task_id !== taskId) {
      for (const repo of repositories) for (const occupied of other.repositories) {
        const overlaps = (a: string, b: string) => { const relative = path.relative(a, b); return !relative || (relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative)) }
        if (overlaps(repo.local_worktree_path, occupied.local_worktree_path) || overlaps(occupied.local_worktree_path, repo.local_worktree_path)) fail('COLLABORATION_DIRECTORY_IN_USE: ' + repo.local_worktree_path)
      }
    }
  }
  private bindings(): SyncBinding[] {
    const directory = path.join(this.state, 'bindings')
    return fs.existsSync(directory) ? fs.readdirSync(directory).filter(file => file.endsWith('.json')).map(file => readJson<SyncBinding>(path.join(directory, file))) : []
  }
  private release(payload: any) {
    const binding = this.load(payload.task_id, true)
    if (binding.binding_id !== payload.binding_id) fail('COLLABORATION_BINDING_CONFLICT')
    if (!payload.suspend && (binding.target || binding.conflicts.length || binding.errors.length)) fail('COLLABORATION_DELIVERY_REQUIRED')
    binding.released = true; binding.suspended = payload.suspend === true; this.save(binding)
    if (payload.suspend) this.index.suspend(binding.task_id); else this.index.close(binding.task_id)
    this.observations.delete(binding.task_id); this.transports.delete(binding.task_id)
    return { managed_roots: this.bindings().filter(row => !row.released).flatMap(row => row.directory_mode === 'MAPPED'
      ? row.repositories.map(repo => repo.local_worktree_path) : [row.task_root]) }
  }
  private received(binding: SyncBinding): SyncManifest | null {
    if (!binding.baseline) return null
    const received = structuredClone(binding.baseline)
    for (const repo of received.repositories) {
      const entries = new Map(repo.files.map(file => [file.path, file]))
      for (const [key, file] of Object.entries(binding.applied)) if (key.startsWith(repo.task_repository_id + ':')) {
        const name = key.slice(repo.task_repository_id.length + 1)
        if (file) entries.set(name, file); else entries.delete(name)
      }
      repo.files = [...entries.values()]
    }
    return received
  }
  // Git's private index reads changed contents; a full raw audit is opt-in only.
  private scan(binding: SyncBinding, verify = true, verifyRaw = false): SyncManifest {
    const repositories = binding.repositories.map(repo => structuredClone(this.index.scan(repo, this.objects, verify, verifyRaw, binding)))
    if (repositories.reduce((total, repo) => total + repo.files.reduce((sum, file) => sum + file.size, 0), 0) > 512 * 1024 * 1024) fail('COLLABORATION_SNAPSHOT_LIMIT')
    if (process.platform === 'win32') {
      const received = this.received(binding)
      for (const repo of repositories) {
        const metadata = new Map(received?.repositories.find(item => item.task_repository_id === repo.task_repository_id)?.files.map(file => [file.path, file.mode]) ?? [])
        for (const file of repo.files) {
          const mode = metadata.get(file.path)
          if (mode && (mode === '120000') !== (file.mode === '120000')) fail('COLLABORATION_PLACEHOLDER_TYPE_CHANGED')
          file.mode = mode ?? file.mode
        }
      }
    }
    return { ...(binding.target ?? binding.baseline ?? binding.metadata), repositories, source: 'HUMAN_HANDOFF' }
  }
  private scanSequence(binding: SyncBinding, manifest: SyncManifest) {
    const file = path.join(this.state, 'indexes', binding.task_id + '-sequence.json')
    const previous = fs.existsSync(file) ? readJson<{ digest: string; sequence: number }>(file) : { digest: '', sequence: 0 }
    const digest = hash(JSON.stringify(manifest.repositories.map(repo => [repo.task_repository_id, repo.files])))
    if (digest !== previous.digest) durableJson(file, { digest, sequence: previous.sequence + 1 })
    return previous.sequence + Number(digest !== previous.digest)
  }
  private changes(base: SyncManifest | null, local: SyncManifest) {
    const changes: { task_repository_id: string; path: string; base: SyncFile | null; local: SyncFile | null }[] = []
    for (const repo of local.repositories) {
      const old = new Map(base?.repositories.find(item => item.task_repository_id === repo.task_repository_id)?.files.map(file => [file.path, file]) ?? [])
      const now = new Map(repo.files.map(file => [file.path, file]))
      for (const name of new Set([...old.keys(), ...now.keys()])) if (!sameFile(old.get(name), now.get(name))) changes.push({
        task_repository_id: repo.task_repository_id, path: name, base: old.get(name) ?? null, local: now.get(name) ?? null,
      })
    }
    return changes
  }
  private status(binding: SyncBinding, local?: SyncManifest, verify = true, verifyRaw = false) {
    try { local ??= this.scan(binding, verify, verifyRaw) } catch (error) { return { ...binding, state: 'RECOVERY_REQUIRED', local_changes: [], errors: [String(error)] } }
    this.observations.set(binding.task_id, structuredClone(local))
    const received = this.received(binding)
    return { ...binding, state: binding.errors.length ? 'RECOVERY_REQUIRED' : binding.conflicts.length ? 'CONFLICT_PENDING'
      : binding.baseline?.snapshot_id ? 'READY' : 'PREPARED', local_changes: this.changes(received, local), manifest: local, received,
      local_scan_seq: this.scanSequence(binding, local), ...this.backupDirectories(binding), scan_metrics: this.index.measurements() }
  }
  private capture(payload: any) {
    const binding = this.load(payload.task_id)
    if (binding.target || binding.errors.length || binding.conflicts.length) fail('COLLABORATION_DELIVERY_REQUIRED')
    if (payload.operation_id && (typeof payload.operation_id !== 'string' || payload.operation_id.length > 256)) fail('INVALID_COLLABORATION_ID')
    const capturedFile = payload.operation_id ? path.join(this.state, 'captures', binding.task_id, hash(payload.operation_id) + '.json') : null
    const reused = capturedFile && fs.existsSync(capturedFile)
    const saved = reused ? readJson(capturedFile!) : null
    const manifest: SyncManifest = saved ? saved.manifest ?? saved : this.scan(binding)
    if (manifest.session_generation < binding.metadata.session_generation) fail('COLLABORATION_CAPTURE_IDENTITY_CHANGED')
    const inputCutSeq = saved?.input_cut_seq ?? this.scanSequence(binding, manifest)
    if (reused && ((payload.session_generation !== undefined && payload.session_generation !== manifest.session_generation)
      || (payload.session_revision !== undefined && payload.session_revision !== manifest.session_revision))) fail('COLLABORATION_CAPTURE_IDENTITY_CHANGED')
    if (payload.session_generation !== undefined) manifest.session_generation = payload.session_generation
    if (payload.session_revision !== undefined) manifest.session_revision = payload.session_revision
    const transfer_manifest = saved?.transfer_manifest || (binding.baseline?.snapshot_id ? manifestDelta(binding.baseline, manifest) : manifest)
    if (capturedFile && !fs.existsSync(capturedFile)) durableJson(capturedFile, { manifest, input_cut_seq: inputCutSeq, transfer_manifest })
    const digests = new Set(manifest.repositories.flatMap(repo => repo.files.map(file => file.sha256)))
    return { manifest, transfer_manifest, input_cut_seq: inputCutSeq, objects: payload.include_objects === false ? [] : [...digests].map(sha256 => ({ sha256, content: this.objects.get(sha256).toString('base64') })), status: this.status(binding, reused ? undefined : manifest) }
  }
  private acceptInput(payload: any) {
    const binding = this.load(payload.task_id), target = payload.target as SyncManifest
    if (binding.target || binding.conflicts.length || binding.errors.length) fail('COLLABORATION_DELIVERY_REQUIRED')
    const saved = readJson(path.join(this.state, 'captures', binding.task_id, hash(String(payload.operation_id)) + '.json'))
    const captured: SyncManifest = saved.manifest ?? saved
    this.validateTarget(binding, target, captured)
    if (captured.repositories.length !== target.repositories.length || captured.repositories.some(repo => {
      const accepted = target.repositories.find(item => item.task_repository_id === repo.task_repository_id)
      const files = new Map(accepted?.files.map(file => [file.path, file]) ?? [])
      return !accepted || accepted.files.length !== repo.files.length || repo.files.some(file => !sameFile(file, files.get(file.path)))
    })) fail('COLLABORATION_INPUT_RECEIPT_MISMATCH')
    // No disk writes: edits made after this immutable capture remain relative to accepted H.
    binding.baseline = target; binding.metadata = this.metadata(target); this.save(binding)
    return this.status(binding, undefined, false)
  }
  private validateTarget(binding: SyncBinding, target: SyncManifest, captured?: SyncManifest) {
    if (target.protocol_version !== 1 || target.task_id !== binding.task_id || target.repositories.length !== binding.repositories.length) fail('COLLABORATION_TARGET_IDENTITY_MISMATCH')
    if (binding.baseline?.snapshot_id && (target.session_generation < binding.baseline.session_generation
      || target.workspace_revision < binding.baseline.workspace_revision)) fail('COLLABORATION_STALE_TARGET')
    const seen = new Set<string>()
    const changedObjects: SyncFile[] = []
    let totalBytes = 0
    for (const repo of target.repositories) {
      const bound = binding.repositories.find(item => item.task_repository_id === repo.task_repository_id)
      if (!bound || seen.has(repo.task_repository_id) || ['repository_id', 'rel_path', 'base_commit_sha', 'branch_name'].some(key => repo[key as keyof typeof repo] !== bound[key as keyof typeof bound])) fail('COLLABORATION_REPOSITORY_SET_MISMATCH')
      seen.add(repo.task_repository_id)
      const files = new Set<string>()
      const previous = new Map((captured ?? binding.baseline)?.repositories.find(item => item.task_repository_id === repo.task_repository_id)?.files.map(file => [file.path, file]))
      const changed = repo.files.filter(file => !sameFile(file, previous.get(file.path)))
      for (const file of changed) syncPath(file.path)
      const indexed = changed.length ? repositoryFileModes(bound!.local_worktree_path, changed.length < 500 ? changed.map(file => file.path) : undefined) : null
      changedObjects.push(...changed)
      if (repo.files.length > 100_000) fail('COLLABORATION_SNAPSHOT_LIMIT')
      for (const file of repo.files) {
        syncPath(file.path)
        if (!sameFile(file, previous.get(file.path))) {
          if (file.path.split('/').some(part => /^\.env(?:\.|$)/.test(part)) && !indexed!.modes.has(file.path)) fail('COLLABORATION_PRIVATE_FILE')
          validateFileMode(file.path, file.mode, indexed!)
        }
        const key = process.platform === 'win32' ? file.path.toLowerCase() : file.path
        if (files.has(key) || !['100644', '100755', '120000'].includes(file.mode)) fail('INVALID_COLLABORATION_FILE')
        files.add(key)
        totalBytes += file.size
        if (totalBytes > 512 * 1024 * 1024) fail('COLLABORATION_SNAPSHOT_LIMIT')
      }
      for (const name of files) {
        const parts = name.split('/')
        for (let index = 1; index < parts.length; index++) if (files.has(parts.slice(0, index).join('/'))) fail('COLLABORATION_MANIFEST_PATH_COLLISION')
      }
    }
    if (this.objects.git.check(changedObjects).length) fail('LOCAL_CONTENT_OBJECT_MISSING')
  }
  private metadata(target: SyncManifest) {
    const { repositories: _repositories, ...metadata } = target
    return metadata
  }
  private equivalentTarget(previous: SyncManifest, target: SyncManifest) {
    const canonical = (manifest: SyncManifest) => ({
      ...this.metadata(manifest), snapshot_id: '',
      repositories: manifest.repositories.map(repo => ({ ...repo, files: [...repo.files].sort((a, b) => a.path.localeCompare(b.path)) }))
        .sort((a, b) => a.task_repository_id.localeCompare(b.task_repository_id)),
    })
    const stable = (value: any): any => Array.isArray(value) ? value.map(stable) : value && typeof value === 'object'
      ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value
    return JSON.stringify(stable(canonical(previous))) === JSON.stringify(stable(canonical(target)))
  }
  private reconcile(payload: any) {
    const binding = this.load(payload.task_id), target = payload.target as SyncManifest
    this.validateTarget(binding, target)
    if (!payload.preview) {
      identifier(payload.operation_id)
      if (binding.target && binding.target.snapshot_id !== target.snapshot_id) {
        if (!this.equivalentTarget(binding.target, target)) fail('COLLABORATION_PENDING_TARGET_REQUIRED')
        // Equivalent duplicate FINALs can be rebound, but prior confirmations must expire.
        binding.conflict_set_id = null
      }
      binding.target = target; binding.errors = []; this.save(binding)
    }
    const local = this.scan(binding), conflicts: SyncConflict[] = []
    const newlyApplied: Record<string, SyncFile | null> = {}
    for (const repo of target.repositories) {
      const bound = binding.repositories.find(item => item.task_repository_id === repo.task_repository_id)!
      const base = new Map(binding.baseline?.repositories.find(item => item.task_repository_id === repo.task_repository_id)?.files.map(file => [file.path, file]) ?? [])
      const current = new Map(local.repositories.find(item => item.task_repository_id === repo.task_repository_id)!.files.map(file => [file.path, file]))
      const cloud = new Map(repo.files.map(file => [file.path, file]))
      for (const name of new Set([...base.keys(), ...cloud.keys()])) {
        const key = fileKey(repo.task_repository_id, name)
        const before = Object.hasOwn(binding.applied, key) ? binding.applied[key] : base.get(name)
        if (sameFile(before, cloud.get(name))) continue
        const actual = observeFile(bound, name, this.objects, current.get(name)?.mode ?? before?.mode ?? cloud.get(name)?.mode)
        if (actual) current.set(name, actual); else current.delete(name)
      }
      local.repositories.find(item => item.task_repository_id === repo.task_repository_id)!.files = [...current.values()]
      const structure = new Map<string, Set<string>>()
      const relate = (left: string, right: string) => {
        const related = new Set([left, right, ...(structure.get(left) ?? []), ...(structure.get(right) ?? [])])
        for (const name of related) structure.set(name, related)
      }
      for (const [names, opposing] of [[current, cloud], [cloud, current]]) for (const name of names.keys()) {
        const parts = name.split('/')
        for (let index = 1; index < parts.length; index++) {
          const parent = parts.slice(0, index).join('/')
          if (opposing.has(parent)) relate(name, parent)
        }
      }
      if (process.platform === 'win32') {
        const cloudCase = new Map([...cloud.keys()].map(name => [name.toLowerCase(), name]))
        for (const name of current.keys()) {
          const candidate = cloudCase.get(name.toLowerCase())
          if (candidate && candidate !== name) relate(name, candidate)
        }
      }
      for (const name of new Set([...base.keys(), ...current.keys(), ...cloud.keys()])) {
        const key = fileKey(repo.task_repository_id, name)
        const before = Object.hasOwn(binding.applied, key) ? binding.applied[key] : base.get(name) ?? null
        const left = current.get(name) ?? null, right = cloud.get(name) ?? null
        if (structure.has(name)) {
          conflicts.push({ task_repository_id: repo.task_repository_id, path: name, expected_sha256: left?.sha256 ?? null,
            base: before, local: left, cloud: right, reason: 'PATH_STRUCTURE', related_paths: [...structure.get(name)!].sort() }); continue
        }
        if (sameFile(left, right) || sameFile(before, right)) continue
        if (!sameFile(before, left)) {
          conflicts.push({ task_repository_id: repo.task_repository_id, path: name, expected_sha256: left?.sha256 ?? null, base: before, local: left, cloud: right, reason: 'BOTH_CHANGED' }); continue
        }
        if (payload.preview && !payload.progressive) continue
        try {
          applyFile({ state: this.state, operation_id: payload.operation_id, task_repository_id: repo.task_repository_id,
            root: bound.local_worktree_path, expected: left, target: right, relative: name, objects: this.objects,
            scratch_root: this.scratch(binding, bound), context: { ...this.metadata(target), kind: 'receive', repo_slug: repo.repo_slug, branch_name: repo.branch_name } })
          binding.applied[key] = right; this.save(binding)
          newlyApplied[key] = right
          updateObservation(local, repo.task_repository_id, name, right)
        } catch (error) { binding.errors.push(repo.task_repository_id + '/' + name + ': ' + String(error)); this.save(binding) }
      }
    }
    if (payload.preview) {
      if (payload.progressive) { this.index.invalidate(newlyApplied); this.save(binding) }
      return { ...this.status(binding, local), preview_conflicts: conflicts, preview: target }
    }
    binding.conflicts = conflicts
    binding.conflict_set_id = conflicts.length ? hash(JSON.stringify([target.snapshot_id, conflicts])) : null
    if (!conflicts.length && !binding.errors.length) {
      this.verifyApplied(binding, local, newlyApplied)
      if (!binding.errors.length) {
        binding.baseline = target; binding.target = null; binding.applied = {}; binding.metadata = this.metadata(target)
      }
    }
    this.index.invalidate(newlyApplied)
    this.save(binding)
    return this.status(binding, local)
  }
  private verifyApplied(binding: SyncBinding, local: SyncManifest, applied: Record<string, SyncFile | null>) {
    for (const [key, expected] of Object.entries(applied)) {
      const separator = key.indexOf(':'), repoId = key.slice(0, separator), name = key.slice(separator + 1)
      const repo = binding.repositories.find(item => item.task_repository_id === repoId)!
      const actual = observeFile(repo, name, this.objects, expected?.mode)
      updateObservation(local, repoId, name, actual)
      if (!sameFile(actual, expected)) binding.errors.push('LOCAL_FILE_CHANGED_DURING_DELIVERY: ' + key)
    }
  }
  private restore(payload: any) {
    const binding = this.load(payload.task_id)
    identifier(payload.operation_id)
    const keepLocal = payload.decision === 'keep'
    if (payload.decision && !['keep', 'accept'].includes(payload.decision)) fail('COLLABORATION_INVALID_DECISION')
    if (!binding.target || !binding.conflict_set_id || payload.conflict_set_id !== binding.conflict_set_id) fail('COLLABORATION_CONFLICT_CONFIRMATION_EXPIRED')
    const target = binding.target!
    if (!Array.isArray(payload.selected) || !payload.selected.length) fail('COLLABORATION_SELECTED_FILES_REQUIRED')
    for (const selected of payload.selected) {
      const conflict = binding.conflicts.find(file => file.task_repository_id === selected.task_repository_id && file.path === selected.path)
      if (keepLocal && conflict?.reason === 'PATH_STRUCTURE') fail('COLLABORATION_RELATED_PATHS_REQUIRED')
      if (conflict?.related_paths?.some(name => !payload.selected.some((item: any) => item.task_repository_id === selected.task_repository_id && item.path === name))) fail('COLLABORATION_RELATED_PATHS_REQUIRED')
    }
    const selectedFiles = [...payload.selected].sort((a, b) => {
      const left = binding.conflicts.find(file => file.task_repository_id === a.task_repository_id && file.path === a.path)
      const right = binding.conflicts.find(file => file.task_repository_id === b.task_repository_id && file.path === b.path)
      return Number(!!left?.cloud) - Number(!!right?.cloud) || b.path.length - a.path.length
    })
    const local = structuredClone(this.observations.get(binding.task_id) ?? this.scan(binding))
    const restored: Record<string, SyncFile | null> = {}
    for (const repo of binding.repositories) if (selectedFiles.some(item => item.task_repository_id === repo.task_repository_id)) validateRepositoryIdentity(repo)
    for (const selected of selectedFiles) {
      const conflict = binding.conflicts.find(file => file.task_repository_id === selected.task_repository_id && file.path === selected.path)
      if (!conflict || selected.expected_sha256 !== conflict.expected_sha256) throw new Error('COLLABORATION_CONFLICT_CONFIRMATION_EXPIRED')
      const repo = binding.repositories.find(item => item.task_repository_id === selected.task_repository_id)!
      try {
        if (keepLocal) {
          const actual = observeFile(repo, selected.path, this.objects, conflict.local?.mode)
          if (!sameFile(actual, conflict.local)) fail('LOCAL_FILE_CHANGED_RECONFIRM')
          updateObservation(local, selected.task_repository_id, selected.path, actual)
        } else {
          applyFile({ state: this.state, operation_id: payload.operation_id, task_repository_id: selected.task_repository_id,
            root: repo.local_worktree_path, expected: conflict.local, target: conflict.cloud, relative: selected.path, objects: this.objects,
            scratch_root: this.scratch(binding, repo), context: { ...this.metadata(target), kind: 'restore', repo_slug: repo.repo_slug, branch_name: repo.branch_name } })
        }
        // A kept local version is a new local edit against the acknowledged cloud version.
        binding.applied[fileKey(selected.task_repository_id, selected.path)] = conflict.cloud
        restored[fileKey(selected.task_repository_id, selected.path)] = conflict.cloud
        this.save(binding)
      } catch (error) {
        binding.errors.push(String(error)); this.save(binding); return this.status(binding)
      }
    }
    if (!keepLocal) this.verifyApplied(binding, local, restored)
    binding.conflicts = binding.conflicts.filter(file => !Object.hasOwn(restored, fileKey(file.task_repository_id, file.path)))
    binding.conflict_set_id = binding.conflicts.length ? hash(JSON.stringify([target.snapshot_id, binding.conflicts])) : null
    if (!binding.conflicts.length && !binding.errors.length) {
      binding.baseline = target; binding.metadata = this.metadata(target); binding.target = null; binding.applied = {}
    }
    this.index.invalidate(restored); this.save(binding)
    return this.status(binding, local)
  }
  private backupDirectories(binding: SyncBinding) {
    const directories = [...new Set(binding.repositories.map(repo => this.scratch(binding, repo)))]
    return { backup_directory: directories.length === 1 ? directories[0] : '', backup_directories: directories }
  }
  private listBackups(taskId: string) {
    const binding = this.findBinding(taskId)
    if (!binding) return { backup_directory: '', backup_directories: [], backups: [] }
    return this.backups(binding)
  }
  private backups(binding: SyncBinding) {
    const directory = path.join(this.state, 'operations')
    const entries: { operation_id: string; task_repository_id: string; path: string; sha256: string; state: string; backup_path: string; created_at?: string; context?: BackupContext }[] = []
    if (fs.existsSync(directory)) for (const operation of fs.readdirSync(directory)) {
      const operationRoot = path.join(directory, operation)
      if (!fs.statSync(operationRoot).isDirectory()) continue
      for (const file of fs.readdirSync(operationRoot)) {
        if (!file.endsWith('.json')) continue
        const record = readJson(path.join(operationRoot, file))
        if (record.context?.task_id && record.context.task_id !== binding.task_id) continue
        if (!binding.repositories.some(repo => repo.local_worktree_path === record.root && repo.task_repository_id === record.task_repository_id) || !record.expected) continue
        entries.push({ operation_id: operation, task_repository_id: record.task_repository_id, path: record.relative,
          sha256: record.actual_backup_sha256 ?? record.expected.sha256, state: record.state, backup_path: record.displaced,
          created_at: record.created_at, context: record.context })
      }
    }
    return { ...this.backupDirectories(binding), backups: entries }
  }
}
