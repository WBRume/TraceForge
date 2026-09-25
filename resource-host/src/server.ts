import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { randomUUID, timingSafeEqual } from 'node:crypto'
import { Database } from 'bun:sqlite'
import { hash, readJson, writeJson } from './filesystem'
import type { Config } from './runtime'
import { renderDashboardHtml } from './dashboard'

export async function startServer(config: Config) {
  if (!config.token || config.token.length < 32 || !Array.isArray(config.allowed_roots) || !path.isAbsolute(config.state_root) || config.allowed_roots.some(root => !path.isAbsolute(root))) throw new Error('Config requires absolute state_root / allowed_roots and a token of at least 32 characters')
  fs.mkdirSync(config.state_root, { recursive: true })
  const identityFile = path.join(config.state_root, 'identity.json')
  if (!fs.existsSync(identityFile)) writeJson(identityFile, { host_id: randomUUID(), protocol_version: 1 })
  const identity = readJson(identityFile)
  const worker = new Worker(new URL('./worker.ts', import.meta.url).href)
  const pending = new Map<string, { resolve: (value: any) => void; reject: (error: Error) => void }>()
  worker.onmessage = event => {
    const item = pending.get(event.data.id)
    pending.delete(event.data.id)
    if (event.data.error) item?.reject(new Error(event.data.error)); else item?.resolve(event.data.result)
  }
  worker.onerror = error => { for (const item of pending.values()) item.reject(new Error(error.message)); pending.clear() }
  function dispatch(kind: string, payload: unknown) {
    return new Promise<any>((resolve, reject) => { const id = randomUUID(); pending.set(id, { resolve, reject }); worker.postMessage({ id, kind, payload }) })
  }
  await dispatch('configure', config)
  const db = new Database(path.join(config.state_root, 'journal.sqlite3'), { readonly: true })
  const startTime = Date.now()

  interface ActivityItem {
    id: string
    time: string
    method: string
    path: string
    status: number
    kind?: string
    duration_ms: number
  }
  const recentActivities: ActivityItem[] = []
  function recordActivity(method: string, reqPath: string, status: number, duration_ms: number, kind?: string) {
    const now = new Date()
    const time = now.toTimeString().split(' ')[0]
    recentActivities.unshift({ id: randomUUID(), time, method, path: reqPath, status, duration_ms, kind })
    if (recentActivities.length > 50) recentActivities.pop()
  }

  const listenHost = config.listen_host || '0.0.0.0'
  const targetPort = config.port ?? 4098
  const localIps: string[] = []
  try {
    const interfaces = os.networkInterfaces()
    for (const name of Object.keys(interfaces)) {
      for (const net of interfaces[name] || []) {
        if (net.family === 'IPv4' && !net.internal) {
          localIps.push(net.address)
        }
      }
    }
  } catch { }

  let server: ReturnType<typeof Bun.serve>
  server = Bun.serve({
    hostname: listenHost, port: targetPort, idleTimeout: 255, maxRequestBodySize: 64 * 1024 * 1024,
    async fetch(request: Request): Promise<Response> {
      const start = performance.now()
      const url = new URL(request.url)

      // Dashboard & public status routes (no auth required for local browser/panel)
      if (request.method === 'GET' && (url.pathname === '/' || url.pathname === '/dashboard')) {
        const html = renderDashboardHtml({
          url: url.origin,
          port: targetPort,
          listenHost,
          localIps,
          token: config.token,
          stateRoot: config.state_root,
          allowedRoots: config.allowed_roots,
          hostId: identity.host_id,
          protocolVersion: identity.protocol_version || 1,
          platform: process.platform === 'win32' ? 'Windows' : process.platform
        })
        return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })
      }

      if (request.method === 'GET' && url.pathname === '/favicon.ico') {
        const iconPaths = [
          path.join(path.dirname(import.meta.dir), 'assets/icon.ico'),
          path.join(path.dirname(process.execPath), 'icon.ico'),
          path.join(path.dirname(process.execPath), 'assets/icon.ico')
        ]
        for (const p of iconPaths) {
          if (fs.existsSync(p)) return new Response(Bun.file(p), { headers: { 'Content-Type': 'image/x-icon' } })
        }
        return new Response(null, { status: 204 })
      }

      if (request.method === 'GET' && url.pathname === '/v1/status') {
        const mem = process.memoryUsage()
        const uptime = Math.floor((Date.now() - startTime) / 1000)
        return Response.json({
          status: 'running',
          uptime,
          memory_mb: (mem.rss / (1024 * 1024)).toFixed(1),
          port: server?.port ?? targetPort,
          listen_host: listenHost,
          host_id: identity.host_id,
          allowed_roots: config.allowed_roots,
          state_root: config.state_root,
          recent_activities: recentActivities
        })
      }

      if (request.method === 'POST' && url.pathname === '/v1/system/open-folder') {
        try {
          const body = (await request.json().catch(() => ({}))) as { folder?: string }
          const target = body?.folder || config.state_root
          if (process.platform === 'win32') {
            Bun.spawn(['explorer.exe', target])
          }
          return Response.json({ ok: true })
        } catch (err) {
          return Response.json({ error: String(err) }, { status: 400 })
        }
      }

      if (request.method === 'POST' && url.pathname === '/v1/system/shutdown') {
        setTimeout(async () => {
          await close()
          process.exit(0)
        }, 200)
        return Response.json({ ok: true, message: 'Shutting down' })
      }

      // TraceForge Protocol routes - require Bearer Token authentication
      const expected = Buffer.from(hash('Bearer ' + config.token)), supplied = Buffer.from(hash(request.headers.get('authorization') || ''))
      if (!timingSafeEqual(expected, supplied)) {
        recordActivity(request.method, url.pathname, 401, Math.round(performance.now() - start))
        return Response.json({ detail: 'Resource credential required' }, { status: 401 })
      }

      try {
        if (request.method === 'GET' && url.pathname === '/v1/identity') {
          const res = { ...identity, platform: process.platform === 'win32' ? 'nt' : 'posix', implementation: 'typescript', capabilities: ['provision', 'checkpoint', 'materialize', 'generate_patch', 'apply_patch', 'restore', 'release', 'skills', 'documents', 'roots_grant'] }
          recordActivity('GET', url.pathname, 200, Math.round(performance.now() - start), 'identity')
          return Response.json(res)
        }
        if (request.method === 'POST' && url.pathname === '/v1/roots/grant') {
          const body = (await request.json().catch(() => ({}))) as {
            roots?: string[]
            workspace_root?: string
            repo_roots?: string[]
          }
          const candidateList = [
            ...(Array.isArray(body.roots) ? body.roots : []),
            body.workspace_root,
            ...(Array.isArray(body.repo_roots) ? body.repo_roots : [])
          ].filter((p): p is string => typeof p === 'string' && !!p.trim())

          const normalizedList: string[] = []
          for (const raw of candidateList) {
            const abs = path.resolve(raw.trim())
            const rootDir = path.parse(abs).root
            if (abs === rootDir) {
              return Response.json({ detail: `不允许直接授权文件系统根目录: ${abs}` }, { status: 400 })
            }
            if (!fs.existsSync(abs)) {
              try { fs.mkdirSync(abs, { recursive: true }) } catch { }
            }
            try {
              normalizedList.push(fs.existsSync(abs) ? fs.realpathSync(abs) : abs)
            } catch {
              normalizedList.push(abs)
            }
          }

          let currentRoots = config.allowed_roots || []
          if (config.roots_config_path && fs.existsSync(config.roots_config_path)) {
            try {
              const fileCfg = readJson(config.roots_config_path)
              if (Array.isArray(fileCfg.allowed_roots)) currentRoots = fileCfg.allowed_roots
            } catch { }
          }

          const merged = Array.from(new Set([...currentRoots.map(r => path.resolve(r)), ...normalizedList]))
          config.allowed_roots = merged

          if (config.roots_config_path && fs.existsSync(config.roots_config_path)) {
            try {
              const fileCfg = readJson(config.roots_config_path)
              fileCfg.allowed_roots = merged
              writeJson(config.roots_config_path, fileCfg)
            } catch (err) {
              console.warn('[ResourceHost] Failed to persist granted roots to config file', err)
            }
          }

          recordActivity('POST', url.pathname, 200, Math.round(performance.now() - start), 'grant-roots')
          return Response.json({ ok: true, allowed_roots: merged })
        }
        if (request.method === 'POST' && url.pathname === '/v1/repositories/inspect') {
          const body = await request.json()
          const result = await dispatch('inspect', body)
          recordActivity('POST', url.pathname, 200, Math.round(performance.now() - start), 'inspect')
          return Response.json(result)
        }
        if (request.method === 'POST' && url.pathname === '/v1/operations') {
          const body = await request.json()
          const result = await dispatch('operation', body)
          recordActivity('POST', url.pathname, 200, Math.round(performance.now() - start), body?.kind || 'operation')
          return Response.json(result)
        }
        if (request.method === 'GET' && url.pathname.startsWith('/v1/operations/')) {
          const row = db.query('SELECT state,result FROM operations WHERE id=?').get(url.pathname.slice('/v1/operations/'.length)) as { state: string; result: string | null } | null
          const status = row ? 200 : 404
          recordActivity('GET', url.pathname, status, Math.round(performance.now() - start), 'operation-query')
          return row ? Response.json({ state: row.state, result: row.result ? JSON.parse(row.result) : null }) : Response.json({ detail: 'Operation not found' }, { status: 404 })
        }
        recordActivity(request.method, url.pathname, 404, Math.round(performance.now() - start))
        return Response.json({ detail: 'Not found' }, { status: 404 })
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        recordActivity(request.method, url.pathname, 409, Math.round(performance.now() - start))
        return Response.json({ detail: { code: message.startsWith('EXECUTION_UNKNOWN') ? 'EXECUTION_UNKNOWN' : 'RESOURCE_OPERATION_FAILED', message } }, { status: 409 })
      }
    },
  })
  const close = async () => { server.stop(true); await dispatch('shutdown', null); db.close(); worker.terminate() }
  return { server, close }
}
