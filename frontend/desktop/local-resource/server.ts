import { createServer } from 'node:http'
import { Worker } from 'node:worker_threads'
import { DatabaseSync } from 'node:sqlite'
import { createHash, randomUUID, timingSafeEqual } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, realpathSync } from 'node:fs'
import { isAbsolute, join, parse, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readJson, writeJson } from './filesystem'
import type { Config } from './runtime'
import { ResourceScheduler } from './scheduler'
import { guardClosedOutputPipes } from '../stdio'
import { parseContract, validateResourceResult } from '../../shared/contracts/validate'

export async function startLocalResourceService(config: Config, options: { http?: boolean; workerUrl?: URL; onCollaborationChanged?: (event: { task_id: string }) => void } = {}) {
  guardClosedOutputPipes()
  if (!config.token || config.token.length < 32 || !isAbsolute(config.state_root)
    || !Array.isArray(config.allowed_roots) || config.allowed_roots.some(root => !isAbsolute(root))) {
    throw new Error('Invalid desktop local resource configuration')
  }
  mkdirSync(config.state_root, { recursive: true })
  const identityFile = join(config.state_root, 'identity.json')
  if (!existsSync(identityFile)) writeJson(identityFile, { host_id: randomUUID() })
  const identity = JSON.parse(readFileSync(identityFile, 'utf8'))
  const workerFile = './localResourceWorker.js'
  const adjacentWorker = new URL(workerFile, import.meta.url)
  // Both builds retain this entry name; Rollup may place the service in chunks/.
  const workerUrl = options.workerUrl ?? (existsSync(fileURLToPath(adjacentWorker)) ? adjacentWorker : new URL('../' + workerFile, import.meta.url))
  const workers = Array.from({ length: 3 }, () => new Worker(workerUrl))
  const pending = new Map<string, { resolve: (value: any) => void; reject: (error: Error) => void }>()
  let failure: Error | undefined
  let stopped = false
  let closing: Promise<void> | undefined
  let db: DatabaseSync | undefined
  const rejectPending = (error: Error) => {
    for (const item of pending.values()) item.reject(error)
    pending.clear()
  }
  const fail = (error: Error) => {
    failure = error
    rejectPending(error)
    void close()
  }
  for (const worker of workers) {
    worker.on('message', ({ id, result, error, event, task_id }) => {
      if (event === 'collaboration_changed') { if (!stopped) options.onCollaborationChanged?.({ task_id }); return }
      const item = pending.get(id)
      pending.delete(id)
      if (error) item?.reject(new Error(error)); else item?.resolve(result)
    })
    worker.on('error', fail)
    worker.on('exit', code => {
      if (!stopped) fail(new Error(`Local resource worker exited (${code})`))
    })
  }
  function send(workerIndex: number, kind: string, payload: unknown) {
    if (failure) return Promise.reject(failure)
    return new Promise<any>((resolve, reject) => {
      const id = randomUUID()
      pending.set(id, { resolve, reject })
      try { workers[workerIndex].postMessage({ id, kind, payload }) }
      catch (error) { pending.delete(id); reject(error) }
    })
  }
  const scheduler = new ResourceScheduler(send)
  const dispatch = (kind: string, payload: unknown): Promise<any> => stopped
    ? Promise.reject(new Error('Local resource service closed')) : scheduler.dispatch(kind, payload)
  const digest = (value: string) => createHash('sha256').update(value).digest()
  const server = options.http === false ? undefined : createServer(async (request, response) => {
    const send = (status: number, body: unknown) => {
      response.writeHead(status, { 'content-type': 'application/json' }); response.end(JSON.stringify(body))
    }
    if (!timingSafeEqual(digest(request.headers.authorization || ''), digest(`Bearer ${config.token}`))) {
      send(401, { detail: 'Resource credential required' }); return
    }
    if (stopped) { send(503, { detail: 'Local resource service closed' }); return }
    try {
      const url = new URL(request.url || '/', 'http://localhost')
      if (request.method === 'GET' && url.pathname === '/v1/identity') {
        send(200, { ...identity, protocol_version: 2, platform: process.platform === 'win32' ? 'nt' : 'posix', implementation: 'typescript', capabilities: ['provision', 'checkpoint', 'materialize', 'generate_patch', 'apply_patch', 'restore', 'release', 'skills', 'documents', 'roots_grant', 'repository_details'] }); return
      }
      if (request.method === 'GET' && url.pathname.startsWith('/v1/operations/')) {
        const row = db!.prepare('SELECT state,result,request FROM operations_v2 WHERE id=?').get(url.pathname.slice('/v1/operations/'.length))
        const command = row ? JSON.parse(String(row.request)) : null
        if (!command || command.task_id !== url.searchParams.get('task_id') || command.resource_id !== url.searchParams.get('resource_id')) { send(404, { detail: 'Operation not found' }); return }
        const { action, ...identity } = command
        const result = row!.result ? JSON.parse(String(row!.result)) : null
        if (row!.state === 'SUCCEEDED') validateResourceResult(identity.kind, action, result)
        send(200, parseContract('operationReceipt', { ...identity, state: row!.state, result })); return
      }
      if (request.method === 'POST' && ['/v1/roots/grant', '/v1/repositories/inspect', '/v1/operations'].includes(url.pathname)) {
        const chunks: Buffer[] = []; let size = 0
        for await (const chunk of request) {
          size += chunk.length
          if (size > 64 * 1024 * 1024) { send(413, { detail: 'Request too large' }); return }
          chunks.push(chunk)
        }
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        if (url.pathname === '/v1/operations') parseContract('resourceCommand', body)
        if (url.pathname === '/v1/roots/grant') {
          const result = await grantRoots(body)
          send(result.status, result.body); return
        }
        send(200, await dispatch(url.pathname.endsWith('/inspect') ? 'inspect' : 'operation', body)); return
      }
      send(404, { detail: 'Not found' })
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      send(409, { detail: { code: message.startsWith('EXECUTION_UNKNOWN') ? 'EXECUTION_UNKNOWN' : 'RESOURCE_OPERATION_FAILED', message } })
    }
  })
  if (server) { server.requestTimeout = 0; server.on('error', fail) }
  async function grantRoots(body: { roots?: string[]; workspace_root?: string; repo_roots?: string[] }) {
    const candidates = [...(Array.isArray(body.roots) ? body.roots : []), body.workspace_root,
      ...(Array.isArray(body.repo_roots) ? body.repo_roots : [])]
      .filter((root): root is string => typeof root === 'string' && !!root.trim())
    const roots: string[] = []
    for (const candidate of candidates) {
      const absolute = resolve(candidate.trim())
      if (absolute === parse(absolute).root) return { status: 400, body: { detail: `不允许直接授权文件系统根目录: ${absolute}` } }
      mkdirSync(absolute, { recursive: true })
      const real = realpathSync(absolute)
      if (real === parse(real).root) return { status: 400, body: { detail: `不允许直接授权文件系统根目录: ${real}` } }
      roots.push(real)
    }
    const persisted = config.roots_config_path ? readJson(config.roots_config_path) : null
    config.allowed_roots = [...new Set([...(persisted?.allowed_roots ?? config.allowed_roots).map((root: string) => resolve(root)), ...roots])]
    if (persisted) writeJson(config.roots_config_path!, { ...persisted, allowed_roots: config.allowed_roots })
    await Promise.all(workers.map((_, index) => send(index, 'grant_roots', config.allowed_roots)))
    return { status: 200, body: { ok: true, allowed_roots: config.allowed_roots } }
  }
  function close(): Promise<void> {
    if (closing) return closing
    stopped = true
    const serverClosed = new Promise<void>(resolve => {
      if (!server) { resolve(); return }
      server.close(() => resolve())
      server.closeAllConnections()
    })
    closing = (async () => {
      let timer: ReturnType<typeof setTimeout> | undefined
      try {
        await Promise.race([
          (async () => {
            if (!failure) await scheduler.drain()
            await Promise.all(workers.map((_, index) => send(index, 'shutdown', null)))
          })(),
          new Promise(resolve => { timer = setTimeout(resolve, 3500) }),
        ])
      } catch { /* A failed worker is still terminated below. */ }
      finally {
        clearTimeout(timer)
        failure ??= new Error('Local resource service closed')
        rejectPending(failure)
        await Promise.all(workers.map(worker => worker.terminate()))
        db?.close()
        await serverClosed
      }
    })()
    return closing
  }
  try {
    for (let index = 0; index < workers.length; index++) await send(index, 'configure', config)
    db = new DatabaseSync(join(config.state_root, 'journal.sqlite3'), { readOnly: true })
    if (server) await new Promise<void>((resolve, reject) => {
      server.once('error', reject)
      server.listen(config.port ?? 4098, config.listen_host || '127.0.0.1', () => {
        server.removeListener('error', reject)
        resolve()
      })
    })
    if (failure) throw failure
    return { server, close, dispatch, isRunning: () => !stopped && (!server || server.listening) }
  } catch (error) {
    await close()
    throw error
  }
}
