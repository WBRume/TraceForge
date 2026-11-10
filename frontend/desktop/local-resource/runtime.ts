import * as fs from 'node:fs'
import * as path from 'node:path'
import { platform, type JournalDatabase } from './platform'
import { child, checkoutProvision, fail, git, hash, inside, inspectRepo, provision, readCommitInfo, readJson, writeFiles, type Receipt } from './filesystem'
import { applyPatches, generatePatches } from './patches'
import { skills } from './content'
import { documents } from './plan-documents'
import { snapshot } from './snapshots'
import { cleanupSession, forkSession, sessionRoot } from './provider'
import { CollaborationRuntime } from './collaboration'
import { rejectManagedWrite } from './collaboration-guard'
import { initialize } from './initialize'
import { parseContract, validateResourceResult } from '../../shared/contracts/validate'
import type { ResourceCommand } from '../../shared/contracts/generated/resourceCommand'
import type { OperationReceipt } from '../../shared/contracts/generated/operationReceipt'

export interface Config { roots_config_path?: string; state_root: string; allowed_roots: string[]; token: string; listen_host?: string; port?: number; dsh_session_root?: string; collaboration_registry_path?: string }
export type Operation = ResourceCommand
const JOURNAL_SCHEMA_VERSION = 2

function initializeJournal(db: JournalDatabase) {
  db.exec('PRAGMA busy_timeout=5000; PRAGMA journal_mode=WAL')
  db.exec('BEGIN IMMEDIATE')
  try {
    const { user_version: version } = db.query('PRAGMA user_version').get() as { user_version: number }
    if (version === 0) {
      // Replace both unversioned receipt layouts. Task bindings are independent of receipts.
      db.exec(`
        DROP TABLE IF EXISTS operations;
        DROP TABLE IF EXISTS operations_v2;
        CREATE TABLE operations (id TEXT PRIMARY KEY, hash TEXT NOT NULL, state TEXT NOT NULL, result TEXT, request TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, resource TEXT NOT NULL, root TEXT NOT NULL);
        PRAGMA user_version=${JOURNAL_SCHEMA_VERSION};
      `)
    } else if (version !== JOURNAL_SCHEMA_VERSION) {
      throw new Error(`Unsupported local resource journal schema: ${version}`)
    }
    db.exec('COMMIT')
  } catch (error) {
    db.exec('ROLLBACK')
    throw error
  }
}

// Compatible with Python json.dumps(sort_keys=True, ensure_ascii=False).
export function canonical(value: any): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(', ') + ']'
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ': ' + canonical(value[key])).join(', ') + '}'
  return JSON.stringify(value)
}
export class Runtime {
  readonly db: JournalDatabase
  readonly collaboration: CollaborationRuntime
  get roots(): string[] {
    const roots = this.config.roots_config_path ? readJson(this.config.roots_config_path).allowed_roots : this.config.allowed_roots
    if (!Array.isArray(roots) || roots.some(root => typeof root !== 'string' || !path.isAbsolute(root))) fail('INVALID_ALLOWED_ROOTS')
    return roots.map((root: string) => path.resolve(root))
  }
  readonly state: string
  readonly config: Config
  constructor(config: Config) {
    this.config = config
    this.state = path.resolve(config.state_root)
    this.collaboration = new CollaborationRuntime(path.join(this.state, 'collaboration'), () => this.roots)
    fs.mkdirSync(this.state, { recursive: true })
    this.db = platform().database(path.join(this.state, 'journal.sqlite3'))
    try {
      initializeJournal(this.db)
    } catch (error) {
      this.db.close()
      throw error
    }
  }
  inspect(payload: any) {
    inside(payload.workspace_root, this.roots)
    return { repositories: (payload.repositories || []).map((repo: any) => ({ ...repo, ...inspectRepo(repo.local_path, repo.configured_git_url, this.roots) })) }
  }
  operation(command: Operation, phase: 'all' | 'register' | 'checkout' = 'all') {
    parseContract('resourceCommand', command)
    for (const value of [command.operation_id, command.task_id, command.resource_id]) if (typeof value !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(value)) fail('INVALID_OPERATION_ID')
    const { payload_hash, ...content } = command
    const digest = hash(canonical(content))
    if (payload_hash !== digest) fail('OPERATION_HASH_MISMATCH')
    const { contract_version, operation_id, resource_id, task_id, kind, payload } = command
    const identity = { contract_version, operation_id, resource_id, task_id, kind }
    const action = 'action' in payload ? payload.action : undefined
    const receipt = (state: OperationReceipt['state'], result: unknown) =>
      parseContract<OperationReceipt>('operationReceipt', { ...identity, state, result })
    const prior = this.db.query('SELECT hash,state,result FROM operations WHERE id=?').get(command.operation_id) as { hash: string; state: string; result: string } | null
    if (prior) {
      if (prior.hash !== digest) fail('OPERATION_ID_CONFLICT')
      if (prior.state === 'SUCCEEDED') {
        const result = JSON.parse(prior.result)
        validateResourceResult(kind, action, result)
        return receipt('SUCCEEDED', result)
      }
      if (phase === 'register' && prior.state === 'FAILED') {
        // Registration has a pinned ownership manifest and can resume a known failure.
        this.db.query("UPDATE operations SET state='RUNNING' WHERE id=?").run(operation_id)
      } else if (phase !== 'checkout' || prior.state !== 'RUNNING') {
        fail('EXECUTION_UNKNOWN: 操作结果未知，请按原操作标识查询')
      }
    } else {
      this.db.query('INSERT INTO operations VALUES (?,?,?,NULL,?)')
        .run(operation_id, digest, 'RUNNING', JSON.stringify({ ...identity, action }))
    }
    try {
      const result = this.execute(command, phase)
      if (phase === 'register') return receipt('RUNNING', null)
      validateResourceResult(kind, action, result)
      this.db.query("UPDATE operations SET state='SUCCEEDED',result=? WHERE id=?").run(JSON.stringify(result), command.operation_id)
      return receipt('SUCCEEDED', result)
    } catch (error) {
      this.db.query('UPDATE operations SET state=?,result=NULL WHERE id=?')
        .run(phase === 'register' ? 'FAILED' : 'UNKNOWN', operation_id)
      throw error
    }
  }
  private execute(command: Operation, phase: 'all' | 'register' | 'checkout'): any {
    const payload: any = command.payload
    const task = this.db.query('SELECT resource,root FROM tasks WHERE id=?').get(command.task_id) as { resource: string; root: string } | null
    if (task && !['repository_details', 'generate_patch'].includes(command.kind)) rejectManagedWrite(this.config.collaboration_registry_path, task.root)
    if (command.kind === 'apply_patch' || command.kind === 'provision') {
      const target = child(inside(payload.workspace_root, this.roots), (command.kind === 'apply_patch' ? 'patches/' : 'tasks/') + command.task_id)
      rejectManagedWrite(this.config.collaboration_registry_path, target)
    }
    if (command.kind === 'apply_patch') return applyPatches(command.task_id, command.operation_id, payload, this.roots, this.state)
    if (command.kind === 'provision') {
      const root = child(inside(payload.workspace_root, this.roots), 'tasks/' + command.task_id)
      if (task && (task.resource !== command.resource_id || task.root !== root)) fail('TASK_BINDING_CONFLICT')
      this.db.query('INSERT OR IGNORE INTO tasks VALUES (?,?,?)').run(command.task_id, command.resource_id, root)
      const manifest = path.join(this.state, 'tasks', command.task_id + '.json')
      return phase === 'checkout' ? checkoutProvision(root, command.task_id, payload.repositories, this.roots, manifest)
        : provision(root, command.task_id, payload.repositories, this.roots, manifest, phase !== 'register')
    }
    if (command.kind === 'release' && !task) return { released: true }
    if (!task || task.resource !== command.resource_id) fail('TASK_RESOURCE_BINDING_REQUIRED')
    const root = inside(task!.root, this.roots)
    const receipt = readJson<Receipt>(path.join(this.state, 'tasks', command.task_id + '.json'))
    const dshRoot = sessionRoot(this.config.dsh_session_root)
    switch (command.kind) {
      case 'initialize': return initialize(receipt, payload)
      case 'repository_details': return { repositories: receipt.repositories.map(repo => ({
        repository_id: repo.repository_id,
        base_commit: repo.base_commit || readCommitInfo(child(root, repo.rel_path), repo.base_commit_sha),
      })) }
      case 'materialize': writeFiles(root, payload.files); return { written: payload.files.length, paths: payload.files.map((entry: any) => child(root, entry.path)) }
      case 'documents': return documents(root, command.task_id, payload, path.join(this.state, 'snapshots', command.resource_id + '_resource', command.task_id + '_task'))
      case 'skills': return skills(root, payload)
      case 'generate_patch': return generatePatches(receipt, this.state)
      case 'snapshot': return snapshot(this.state, command.resource_id, receipt, payload, dshRoot)
      case 'provider_fork': {
        const id = forkSession(dshRoot, payload.session_id, root)
        if (payload.drill) cleanupSession(dshRoot, id)
        return { session_id: id }
      }
      case 'release':
        for (const repo of receipt.repositories) {
          const target = child(root, repo.rel_path)
          if (!fs.existsSync(target)) continue
          if (repo.files_ready !== false && git(target, 'status', '--porcelain')) fail('WORKTREE_HAS_CHANGES: 保留未提交修改，不能删除')
          if (git(target, 'branch', '--show-current') !== repo.task_branch) fail('WORKTREE_OWNERSHIP_CONFLICT')
          if (repo.files_ready === false && git(target, 'rev-parse', 'HEAD') !== repo.base_commit_sha) fail('WORKTREE_OWNERSHIP_CONFLICT')
          git(repo.repo_root, 'worktree', 'remove', ...(repo.files_ready === false ? ['--force'] : []), target)
          git(repo.repo_root, 'branch', '-D', repo.task_branch)
        }
        return { released: true }
      default: fail('UNSUPPORTED_RESOURCE_OPERATION')
    }
  }
}
