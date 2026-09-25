import * as fs from 'node:fs'
import * as path from 'node:path'
import { platform, type JournalDatabase } from './platform'
import { child, fail, git, hash, inside, inspectRepo, provision, readJson, writeFiles, type Receipt } from './filesystem'
import { applyPatches, generatePatches } from './patches'
import { documents, skills } from './content'
import { snapshot } from './snapshots'
import { cleanupSession, forkSession, sessionRoot } from './provider'

export interface Config { roots_config_path?: string; state_root: string; allowed_roots: string[]; token: string; listen_host?: string; port?: number; dsh_session_root?: string; document_roots?: string[] }
export interface Operation { operation_id: string; resource_id: string; task_id: string; kind: string; payload_hash: string; payload: any }
// Compatible with Python json.dumps(sort_keys=True, ensure_ascii=False).
export function canonical(value: any): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(', ') + ']'
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ': ' + canonical(value[key])).join(', ') + '}'
  return JSON.stringify(value)
}
export class Runtime {
  readonly db: JournalDatabase
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
    fs.mkdirSync(this.state, { recursive: true })
    this.db = platform().database(path.join(this.state, 'journal.sqlite3'))
    this.db.exec('PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, hash TEXT NOT NULL, state TEXT NOT NULL, result TEXT); CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, resource TEXT NOT NULL, root TEXT NOT NULL)')
  }
  inspect(payload: any) {
    inside(payload.workspace_root, this.roots)
    return { repositories: (payload.repositories || []).map((repo: any) => ({ ...repo, ...inspectRepo(repo.local_path, repo.configured_git_url, this.roots) })) }
  }
  operation(command: Operation) {
    for (const value of [command.operation_id, command.task_id, command.resource_id]) if (typeof value !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(value)) fail('INVALID_OPERATION_ID')
    const { payload_hash, ...content } = command
    const digest = hash(canonical(content))
    if (payload_hash !== digest) fail('OPERATION_HASH_MISMATCH')
    const prior = this.db.query('SELECT hash,state,result FROM operations WHERE id=?').get(command.operation_id) as { hash: string; state: string; result: string } | null
    if (prior) {
      if (prior.hash !== digest) fail('OPERATION_ID_CONFLICT')
      if (prior.state === 'SUCCEEDED') return { state: 'SUCCEEDED', result: JSON.parse(prior.result) }
      if (!['provision', 'release'].includes(command.kind)) fail('EXECUTION_UNKNOWN: 操作结果未知，请对账后重试')
    } else this.db.query('INSERT INTO operations VALUES (?,?,?,NULL)').run(command.operation_id, digest, 'RUNNING')
    try {
      const result = this.execute(command)
      this.db.query("UPDATE operations SET state='SUCCEEDED',result=? WHERE id=?").run(JSON.stringify(result), command.operation_id)
      return { state: 'SUCCEEDED', result }
    } catch (error) {
      this.db.query("UPDATE operations SET state='FAILED',result=? WHERE id=?").run(JSON.stringify({ error: String(error) }), command.operation_id)
      throw error
    }
  }
  private execute(command: Operation): any {
    const payload = command.payload
    const task = this.db.query('SELECT resource,root FROM tasks WHERE id=?').get(command.task_id) as { resource: string; root: string } | null
    if (command.kind === 'apply_patch') return applyPatches(command.task_id, command.operation_id, payload, this.roots, this.state)
    if (command.kind === 'provision') {
      const root = child(inside(payload.workspace_root, this.roots), 'tasks/' + command.task_id)
      if (task && (task.resource !== command.resource_id || task.root !== root)) fail('TASK_BINDING_CONFLICT')
      this.db.query('INSERT OR IGNORE INTO tasks VALUES (?,?,?)').run(command.task_id, command.resource_id, root)
      return provision(root, command.task_id, payload.repositories, this.roots, path.join(this.state, 'tasks', command.task_id + '.json'))
    }
    if (command.kind === 'release' && !task) return { released: true }
    if (!task || task.resource !== command.resource_id) fail('TASK_RESOURCE_BINDING_REQUIRED')
    const root = inside(task!.root, this.roots)
    const receipt = readJson<Receipt>(path.join(this.state, 'tasks', command.task_id + '.json'))
    const dshRoot = sessionRoot(this.config.dsh_session_root)
    switch (command.kind) {
      case 'materialize': writeFiles(root, payload.files); return { written: payload.files.length, paths: payload.files.map((entry: any) => child(root, entry.path)) }
      case 'documents': return documents(root, command.task_id, payload, this.config.document_roots)
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
          if (git(target, 'status', '--porcelain')) fail('WORKTREE_HAS_CHANGES: 保留未提交修改，不能删除')
          git(repo.repo_root, 'worktree', 'remove', target)
        }
        return { released: true }
      default: fail('UNSUPPORTED_RESOURCE_OPERATION')
    }
  }
}
