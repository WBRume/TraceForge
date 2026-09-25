import { app, ipcMain, utilityProcess } from 'electron'
import spawn from 'cross-spawn'
import { createHash, randomBytes } from 'node:crypto'
import { closeSync, createWriteStream, existsSync, openSync } from 'node:fs'
import { mkdir, readFile, realpath, rename, writeFile } from 'node:fs/promises'
import { networkInterfaces } from 'node:os'
import { join } from 'node:path'
import { createServer } from 'node:net'
import type { AddressInfo } from 'node:net'

const starts = new Map<string, Promise<unknown>>()
const resourceChildren = new Set<ReturnType<typeof utilityProcess.fork>>()
const children = new Set<ReturnType<typeof spawn>>()
const freePort = async () => {
  const server = createServer()
  await new Promise<void>((ok, fail) => { server.once('error', fail); server.listen(0, '0.0.0.0', ok) })
  const port = (server.address() as AddressInfo).port
  await new Promise<void>((ok, fail) => server.close(error => error ? fail(error) : ok()))
  return port
}
const launch = (file: string, args: string[], cwd: string, logFile: string, env = process.env) => {
  const output = openSync(logFile, 'a', 0o600)
  try {
    const child = spawn(file, args, { cwd, env, detached: true, windowsHide: true, stdio: ['ignore', output, output] })
    child.unref()
    children.add(child)
    child.once('exit', () => children.delete(child))
    child.once('error', () => children.delete(child))
    return child
  } finally { closeSync(output) }
}

const serviceStateRoot = (backend: string) => {
  if (!['opencode', 'dsh'].includes(backend)) throw new Error('Only OpenCode serve and DSH web are supported')
  const key = createHash('sha256').update(JSON.stringify(['service', backend])).digest('hex').slice(0, 24)
  return join(app.getPath('userData'), 'local-resources', key)
}

export const registerLocalResourcesIpc = () => {
  ipcMain.handle('sdd:resources:configure-roots', async (_event, payload: { backend: string; resourceServiceUrl: string; workspaceRoot: string; repoRoots: string[] }) => {
    const configFile = join(serviceStateRoot(payload.backend), 'host.json')
    if (!existsSync(configFile)) return { managed: false }
    const config = JSON.parse(await readFile(configFile, 'utf8'))
    if (payload.resourceServiceUrl.replace(/\/$/, '') !== `http://${config.advertised_host}:${config.port}`) return { managed: false }
    if (!payload.workspaceRoot || !Array.isArray(payload.repoRoots)) throw new Error('保存执行资源前，请填写本地工作区根目录')
    await mkdir(payload.workspaceRoot, { recursive: true })
    const roots = await Promise.all([payload.workspaceRoot, ...payload.repoRoots].map(root => realpath(root)))
    // Retain grants used by running tasks; publish atomically for the Host worker.
    config.allowed_roots = [...new Set([...(config.allowed_roots || []), ...roots])]
    const temporary = `${configFile}.${randomBytes(8).toString('hex')}.tmp`
    await writeFile(temporary, JSON.stringify(config), { mode: 0o600 })
    await rename(temporary, configFile)
    return { managed: true }
  })
  ipcMain.handle('sdd:resources:start', (_event, payload: { backend: string }) => {
    const pending = starts.get(payload.backend)
    if (pending) return pending
    const started = startServices(payload).finally(() => starts.delete(payload.backend))
    starts.set(payload.backend, started)
    return started
  })
}

async function startServices(payload: { backend: string }) {
  if (!['opencode', 'dsh'].includes(payload.backend)) throw new Error('Only OpenCode serve and DSH web are supported')
  const host = Object.values(networkInterfaces()).flat().find(address => address?.family === 'IPv4' && !address.internal)?.address || '127.0.0.1'
  const stateRoot = serviceStateRoot(payload.backend)
  await mkdir(stateRoot, { recursive: true })
  const configFile = join(stateRoot, 'host.json')
  const existing = existsSync(configFile) ? JSON.parse(await readFile(configFile, 'utf8')) : null
  const hostPort = existing?.port || await freePort()
  let agentPort = existing?.agent_port || await freePort()
  while (agentPort === hostPort) agentPort = await freePort()
  const token = existing?.token || randomBytes(32).toString('hex')
  let agentToken = existing?.agent_token || randomBytes(32).toString('hex')
  const config = { state_root: stateRoot, allowed_roots: existing?.allowed_roots || [], token, listen_host: '0.0.0.0', port: hostPort, agent_port: agentPort, agent_token: agentToken, advertised_host: existing?.advertised_host || host }
  const result = () => ({ service_url: `http://${config.advertised_host}:${agentPort}`, resource_service_url: `http://${config.advertised_host}:${hostPort}`, host_token: token, agent_token: agentToken })
  const agentReady = async () => {
    try {
      const response = await fetch(`http://127.0.0.1:${agentPort}${payload.backend === 'opencode' ? '/api/info' : `/?token=${encodeURIComponent(agentToken)}`}`, {
        headers: payload.backend === 'opencode' ? { Authorization: `Basic ${Buffer.from(`opencode:${agentToken}`).toString('base64')}` } : {},
        redirect: 'manual', signal: AbortSignal.timeout(1000),
      })
      if (payload.backend === 'opencode') {
        const body = await response.json() as { version?: string; pid?: number; urls?: unknown }
        return response.ok && /^2\./.test(body.version || '') && Number.isInteger(body.pid) && Array.isArray(body.urls)
      }
      return [200, 302, 303, 307].includes(response.status)
    } catch { return false }
  }
  let hostReady = false
  try {
    const identity = await fetch(`http://127.0.0.1:${hostPort}/v1/identity`, { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(1000) })
    hostReady = identity.ok && !!existing
    if (hostReady && await agentReady()) return result()
  } catch { /* A persisted profile can be restarted using the same endpoints. */ }
  const agentIsReady = await agentReady()
  for (const [port, ready, label] of [[hostPort, hostReady, '同机资源服务'], [agentPort, agentIsReady, payload.backend]] as const) {
    if (ready) continue
    const listener = createServer()
    try {
      await new Promise<void>((ok, fail) => { listener.once('error', fail); listener.listen(port, '0.0.0.0', ok) })
    } catch { throw new Error(`${label} 端口 ${port} 已被占用，但协议或凭据检测未通过。请检查服务版本、地址与访问凭据。`) }
    finally { if (listener.listening) await new Promise<void>(ok => listener.close(() => ok())) }
  }
  await writeFile(configFile, JSON.stringify(config), { mode: 0o600 })
  let failure: Error | undefined
  let resourceExit: number | null = null
  const resource = hostReady ? null : utilityProcess.fork(
    join(app.getAppPath(), 'dist-electron/resourceHost.js'), [configFile],
    { cwd: stateRoot, stdio: 'pipe', serviceName: 'TraceForge Resource Host' },
  )
  if (resource) {
    resourceChildren.add(resource)
    const log = createWriteStream(join(stateRoot, 'resource.log'), { flags: 'a', mode: 0o600 })
    resource.stdout?.pipe(log, { end: false })
    resource.stderr?.pipe(log, { end: false })
    resource.once('exit', code => { resourceExit = code; resourceChildren.delete(resource); log.end() })
  }
  const priorAgentLog = existsSync(join(stateRoot, 'agent.log')) ? (await readFile(join(stateRoot, 'agent.log'), 'utf8')).length : 0
  const agent = agentIsReady ? null : payload.backend === 'opencode'
    ? launch('opencode', ['serve', '--hostname', '0.0.0.0', '--port', String(agentPort)], stateRoot, join(stateRoot, 'agent.log'), { ...process.env, OPENCODE_SERVER_PASSWORD: agentToken, OPENCODE_SERVER_USERNAME: 'opencode' })
    : launch('dsh', ['web', '--host', '0.0.0.0', '--port', String(agentPort), '--no-open'], stateRoot, join(stateRoot, 'agent.log'))
  agent?.once('error', error => { failure = error })
  try {
    if (payload.backend === 'dsh' && agent) {
      const deadline = Date.now() + 90_000
      agentToken = ''
      while (!agentToken && Date.now() < deadline) {
        if (failure || agent.exitCode !== null) throw failure || new Error('DSH 启动失败')
        const output = await readFile(join(stateRoot, 'agent.log'), 'utf8')
        const match = /dsh web: (http:\/\/[^\s]+)/u.exec(output.slice(priorAgentLog))
        if (match?.[1]) agentToken = new URL(match[1]).searchParams.get('token') || ''
        if (!agentToken) await new Promise(ok => setTimeout(ok, 250))
      }
      if (!agentToken) throw new Error('DSH 未返回配对凭据')
      config.agent_token = agentToken
      await writeFile(configFile, JSON.stringify(config), { mode: 0o600 })
    }
    const deadline = Date.now() + 30_000
    while (Date.now() < deadline) {
      if (failure) throw failure
      if (resourceExit !== null) throw new Error(`同机资源服务启动失败（退出码 ${resourceExit}），日志：${join(stateRoot, 'resource.log')}`)
      if (agent && agent.exitCode !== null) throw new Error(`${payload.backend} 启动失败（退出码 ${agent.exitCode}），请检查端口 ${agentPort} 是否被占用及日志：${join(stateRoot, 'agent.log')}`)
      try {
        const response = await fetch(`http://127.0.0.1:${hostPort}/v1/identity`, { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(1000) })
        if (response.ok && await agentReady()) return result()
      } catch { /* Startup readiness only; task synchronization uses WebSockets. */ }
      await new Promise(ok => setTimeout(ok, 250))
    }
    throw new Error('同机资源服务启动超时')
  } catch (error) { resource?.kill(); agent?.kill(); throw error }
}
