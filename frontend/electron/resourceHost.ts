// Runs in Electron's utility process; no standalone Node or Bun installation.
import { createServer } from 'node:http'
import { Worker } from 'node:worker_threads'
import { DatabaseSync } from 'node:sqlite'
import { createHash, randomUUID, timingSafeEqual } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { isAbsolute, join, resolve } from 'node:path'
import type { Config } from '../../resource-host/src/runtime'

const configPath = resolve(process.argv[2]!)
const config: Config = { ...JSON.parse(readFileSync(configPath, 'utf8')), roots_config_path: configPath }
if (!config.token || config.token.length < 32 || !isAbsolute(config.state_root)
  || !Array.isArray(config.allowed_roots) || config.allowed_roots.some(root => !isAbsolute(root))) {
  throw new Error('Invalid Resource Host configuration')
}
mkdirSync(config.state_root, { recursive: true })
const identityFile = join(config.state_root, 'identity.json')
if (!existsSync(identityFile)) writeFileSync(identityFile, JSON.stringify({ host_id: randomUUID(), protocol_version: 1 }))
const identity = JSON.parse(readFileSync(identityFile, 'utf8'))
const workerFile = './resourceWorker.js'
const worker = new Worker(new URL(workerFile, import.meta.url))
const pending = new Map<string, { resolve: (value: unknown) => void; reject: (error: Error) => void }>()
worker.on('message', ({ id, result, error }) => {
  const item = pending.get(id)
  pending.delete(id)
  if (error) item?.reject(new Error(error)); else item?.resolve(result)
})
worker.on('error', error => { for (const item of pending.values()) item.reject(error); pending.clear(); process.exitCode = 1; server.close() })
worker.on('exit', code => { if (code) process.exit(1) })
function dispatch(kind: string, payload: unknown) {
  return new Promise((resolve, reject) => {
    const id = randomUUID(); pending.set(id, { resolve, reject }); worker.postMessage({ id, kind, payload })
  })
}
const digest = (value: string) => createHash('sha256').update(value).digest()
let db: DatabaseSync
const server = createServer(async (request, response) => {
  const send = (status: number, body: unknown) => {
    response.writeHead(status, { 'content-type': 'application/json' }); response.end(JSON.stringify(body))
  }
  if (!timingSafeEqual(digest(request.headers.authorization || ''), digest(`Bearer ${config.token}`))) {
    send(401, { detail: 'Resource credential required' }); return
  }
  try {
    const url = new URL(request.url || '/', 'http://localhost')
    if (request.method === 'GET' && url.pathname === '/v1/identity') {
      send(200, { ...identity, platform: process.platform === 'win32' ? 'nt' : 'posix', implementation: 'typescript', capabilities: ['provision', 'checkpoint', 'materialize', 'generate_patch', 'apply_patch', 'restore', 'release', 'skills', 'documents'] }); return
    }
    if (request.method === 'GET' && url.pathname.startsWith('/v1/operations/')) {
      const row = db.prepare('SELECT state,result FROM operations WHERE id=?').get(url.pathname.slice('/v1/operations/'.length))
      send(row ? 200 : 404, row ? { state: row.state, result: row.result ? JSON.parse(String(row.result)) : null } : { detail: 'Operation not found' }); return
    }
    if (request.method === 'POST' && ['/v1/repositories/inspect', '/v1/operations'].includes(url.pathname)) {
      const chunks: Buffer[] = []; let size = 0
      for await (const chunk of request) {
        size += chunk.length
        if (size > 64 * 1024 * 1024) { send(413, { detail: 'Request too large' }); return }
        chunks.push(chunk)
      }
      send(200, await dispatch(url.pathname.endsWith('/inspect') ? 'inspect' : 'operation', JSON.parse(Buffer.concat(chunks).toString('utf8')))); return
    }
    send(404, { detail: 'Not found' })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    send(409, { detail: { code: message.startsWith('EXECUTION_UNKNOWN') ? 'EXECUTION_UNKNOWN' : 'RESOURCE_OPERATION_FAILED', message } })
  }
})
server.requestTimeout = 0
await dispatch('configure', config)
db = new DatabaseSync(join(config.state_root, 'journal.sqlite3'), { readOnly: true })
server.listen(config.port ?? 4098, config.listen_host || '127.0.0.1', () => console.log('TraceForge Resource Host ready'))
