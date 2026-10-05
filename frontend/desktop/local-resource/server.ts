// Private resource protocol used by the Tauri desktop sidecar.
import * as fs from 'node:fs'
import * as path from 'node:path'
import { randomUUID, timingSafeEqual } from 'node:crypto'
import { Database } from 'bun:sqlite'
import { hash, readJson, writeJson } from './filesystem'
import type { Config } from './runtime'

export async function startServer(config: Config, options: { workerUrl?: string } = {}) {
  if (!config.token || config.token.length < 32 || !Array.isArray(config.allowed_roots)
    || !path.isAbsolute(config.state_root) || config.allowed_roots.some(root => !path.isAbsolute(root))) {
    throw new Error('Config requires absolute state_root / allowed_roots and a token of at least 32 characters')
  }
  fs.mkdirSync(config.state_root, { recursive: true })
  const identityFile = path.join(config.state_root, 'identity.json')
  if (!fs.existsSync(identityFile)) writeJson(identityFile, { host_id: randomUUID(), protocol_version: 1 })
  const identity = readJson(identityFile)
  const worker = new Worker(options.workerUrl ?? new URL('./worker.ts', import.meta.url).href)
  const pending = new Map<string, { resolve: (value: any) => void; reject: (error: Error) => void }>()
  worker.onmessage = event => {
    const item = pending.get(event.data.id)
    pending.delete(event.data.id)
    if (event.data.error) item?.reject(new Error(event.data.error))
    else item?.resolve(event.data.result)
  }
  worker.onerror = error => {
    for (const item of pending.values()) item.reject(new Error(error.message))
    pending.clear()
  }
  function dispatch(kind: string, payload: unknown) {
    return new Promise<any>((resolve, reject) => {
      const id = randomUUID()
      pending.set(id, { resolve, reject })
      worker.postMessage({ id, kind, payload })
    })
  }
  await dispatch('configure', config)
  const db = new Database(path.join(config.state_root, 'journal.sqlite3'), { readonly: true })
  const server = Bun.serve({
    hostname: config.listen_host || '127.0.0.1', port: config.port ?? 4098,
    idleTimeout: 255, maxRequestBodySize: 64 * 1024 * 1024,
    async fetch(request: Request): Promise<Response> {
      const expected = Buffer.from(hash('Bearer ' + config.token))
      const supplied = Buffer.from(hash(request.headers.get('authorization') || ''))
      if (!timingSafeEqual(expected, supplied)) {
        return Response.json({ detail: 'Resource credential required' }, { status: 401 })
      }
      const url = new URL(request.url)
      try {
        if (request.method === 'GET' && url.pathname === '/v1/identity') {
          return Response.json({ ...identity, platform: process.platform === 'win32' ? 'nt' : 'posix',
            implementation: 'typescript', capabilities: ['provision', 'checkpoint', 'materialize',
              'generate_patch', 'apply_patch', 'restore', 'release', 'skills', 'documents', 'roots_grant'] })
        }
        if (request.method === 'POST' && url.pathname === '/v1/roots/grant') {
          const body = await request.json() as { roots?: string[]; workspace_root?: string; repo_roots?: string[] }
          const candidates = [...(Array.isArray(body.roots) ? body.roots : []), body.workspace_root,
            ...(Array.isArray(body.repo_roots) ? body.repo_roots : [])]
            .filter((root): root is string => typeof root === 'string' && !!root.trim())
          const roots: string[] = []
          for (const candidate of candidates) {
            const absolute = path.resolve(candidate.trim())
            if (absolute === path.parse(absolute).root) {
              return Response.json({ detail: `不允许直接授权文件系统根目录: ${absolute}` }, { status: 400 })
            }
            fs.mkdirSync(absolute, { recursive: true })
            roots.push(fs.realpathSync(absolute))
          }
          const persisted = config.roots_config_path ? readJson(config.roots_config_path) : null
          const current = persisted?.allowed_roots ?? config.allowed_roots
          config.allowed_roots = Array.from(new Set([...current.map((root: string) => path.resolve(root)), ...roots]))
          if (persisted) writeJson(config.roots_config_path!, { ...persisted, allowed_roots: config.allowed_roots })
          return Response.json({ ok: true, allowed_roots: config.allowed_roots })
        }
        if (request.method === 'POST' && url.pathname === '/v1/repositories/inspect') {
          return Response.json(await dispatch('inspect', await request.json()))
        }
        if (request.method === 'POST' && url.pathname === '/v1/operations') {
          return Response.json(await dispatch('operation', await request.json()))
        }
        if (request.method === 'GET' && url.pathname.startsWith('/v1/operations/')) {
          const row = db.query('SELECT state,result FROM operations WHERE id=?')
            .get(url.pathname.slice('/v1/operations/'.length)) as { state: string; result: string | null } | null
          return row ? Response.json({ state: row.state, result: row.result ? JSON.parse(row.result) : null })
            : Response.json({ detail: 'Operation not found' }, { status: 404 })
        }
        return Response.json({ detail: 'Not found' }, { status: 404 })
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        return Response.json({ detail: {
          code: message.startsWith('EXECUTION_UNKNOWN') ? 'EXECUTION_UNKNOWN' : 'RESOURCE_OPERATION_FAILED', message,
        } }, { status: 409 })
      }
    },
  })
  const close = async () => {
    server.stop(true)
    await dispatch('shutdown', null)
    db.close()
    worker.terminate()
  }
  return { server, close }
}
