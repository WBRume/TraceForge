import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { createInterface } from 'node:readline'
import { createServer } from 'node:net'
import { createServer as createHttpServer } from 'node:http'

const target = process.env.TAURI_ENV_TARGET_TRIPLE || execFileSync('rustc', ['--print', 'host-tuple'], { encoding: 'utf8' }).trim()
const executable = resolve(`src-tauri/binaries/traceforge-desktop-host-${target}${process.platform === 'win32' ? '.exe' : ''}`)

test('compiled desktop host preserves config, Git, binary downloads, process events and native cancellation', { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), 'traceforge-desktop-test-'))
  const repo = join(root, 'repo')
  mkdirSync(repo)
  const git = (...args) => execFileSync('git', args, { cwd: repo, encoding: 'utf8', windowsHide: true })
  git('init', '-b', 'main')
  git('remote', 'add', 'origin', 'https://example.com/team/repo.git')
  const portProbe = createServer()
  await new Promise(resolve => portProbe.listen(0, '127.0.0.1', resolve))
  const loopbackPort = portProbe.address().port
  await new Promise(resolve => portProbe.close(resolve))
  const backend = createHttpServer((request, response) => {
    if (request.url.includes('/authorize?')) {
      response.writeHead(200, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify({ authorize_url: 'https://example.com/oauth' }))
    } else {
      response.writeHead(302, { Location: `http://127.0.0.1:${loopbackPort}/callback?ticket=test-ticket&status=LOGIN_OK` })
      response.end()
    }
  })
  await new Promise(resolve => backend.listen(0, '127.0.0.1', resolve))
  const child = spawn(executable, [join(root, 'config'), root], {
    windowsHide: true, stdio: 'pipe', env: { ...process.env, SDD_OAUTH_LOOPBACK_PORT: String(loopbackPort) },
  })
  const pending = new Map()
  const events = []
  let sequence = 0
  let cancelDialog = false
  let stderr = ''
  child.stderr.on('data', data => { stderr += data })
  const input = createInterface({ input: child.stdout })
  input.on('line', line => {
    const message = JSON.parse(line)
    if (message.kind === 'result') {
      const reply = pending.get(message.id)
      pending.delete(message.id)
      if (message.error) reply?.reject(new Error(message.error))
      else reply?.resolve(message.result)
    } else if (message.kind === 'event') events.push(message)
    else if (message.kind === 'native') {
      const result = message.method === 'open-external' ? null : message.method === 'save-file'
        ? { canceled: cancelDialog, filePath: cancelDialog ? null : join(root, 'saved.bin') }
        : { canceled: cancelDialog, filePaths: cancelDialog ? [] : [repo] }
      child.stdin.write(JSON.stringify({ kind: 'native-result', id: message.id, result }) + '\n')
      if (message.method === 'open-external') {
        void fetch(`http://127.0.0.1:${loopbackPort}/callback?code=test-code&state=test-state`).catch(() => {})
      }
    }
  })
  child.on('exit', code => {
    for (const reply of pending.values()) reply.reject(new Error(`Host exited: ${code}: ${stderr}`))
    pending.clear()
  })
  const invoke = (channel, payload = {}) => new Promise((resolve, reject) => {
    const id = String(++sequence)
    pending.set(id, { resolve, reject })
    child.stdin.write(JSON.stringify({ id, channel: `sdd:${channel}`, payload }) + '\n')
  })
  try {
    assert.equal((await invoke('config:get')).serverUrl, 'http://localhost:8000')
    assert.equal((await invoke('config:set', { serverUrl: 'https://server.example///', token: 'test' })).serverUrl, 'https://server.example')
    const mapping = { workspaceId: 'ws', remoteUrl: 'git@example.com:team/repo.git', localPath: repo }
    await invoke('config:set-repo-mapping', mapping)
    assert.equal((await invoke('config:get-repo-mapping', { ...mapping, remoteUrl: 'https://example.com/team/repo' })).localPath, repo)
    assert.equal((await invoke('git:validate-repo', { repoPath: repo })).ok, true)
    assert.deepEqual(await invoke('git:get-remotes', { repoPath: repo }), [{ name: 'origin', fetchUrl: 'https://example.com/team/repo.git' }])
    assert.equal((await invoke('git:get-status', { repoPath: repo })).isClean, true)
    assert.equal((await invoke('git:select-directory')).path, repo)
    const bytes = [0, 1, 127, 128, 255]
    const save = await invoke('download:save', { suggestedName: 'file.bin', data: bytes })
    assert.equal(save.saved, true)
    assert.deepEqual([...readFileSync(save.savedPath)], bytes)
    cancelDialog = true
    assert.equal((await invoke('download:save', { suggestedName: 'file.bin', data: bytes })).canceled, true)
    assert.equal((await invoke('git:select-directory')).canceled, true)
    await assert.rejects(invoke('unknown'), /Unknown desktop command/)
    await assert.rejects(invoke('system:open-external', { url: 'file:///tmp/file' }), /Only http/)
    await assert.rejects(invoke('process:run-command', { cwd: repo, command: 'git push' }), /not allowed/)
    const command = await invoke('process:run-command', { cwd: repo, command: 'git', args: ['--version'] })
    const deadline = Date.now() + 10000
    while (!events.some(event => event.channel === 'sdd:process:exit' && event.payload.runId === command.runId) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 25))
    assert.ok(events.some(event => event.channel === 'sdd:process:output' && event.payload.runId === command.runId && /git version/.test(event.payload.text)))
    assert.equal(events.find(event => event.channel === 'sdd:process:exit' && event.payload.runId === command.runId)?.payload.code, 0)
    const longCommand = await invoke('process:run-command', { cwd: repo, command: process.execPath, args: ['-e', 'setInterval(() => {}, 1000)'] })
    assert.equal((await invoke('process:cancel-command', { runId: longCommand.runId })).ok, true)
    assert.equal((await invoke('process:cancel-command', { runId: longCommand.runId })).ok, false)
    await invoke('config:set', { serverUrl: `http://127.0.0.1:${backend.address().port}` })
    const oauth = await invoke('oauth:start', { provider: 'github', intent: 'login', clientType: 'desktop' })
    assert.equal(oauth.ticket, 'test-ticket')
    assert.ok(events.some(event => event.channel === 'sdd:oauth:ticket' && event.payload.ticket === 'test-ticket'))
    assert.equal(stderr, '')
  } finally {
    child.stdin.end()
    await new Promise(resolve => child.once('exit', resolve))
    input.close()
    await new Promise(resolve => backend.close(resolve))
    // Only this test's freshly created directory is removed.
    assert.ok(root.startsWith(join(tmpdir(), 'traceforge-desktop-test-')))
    rmSync(root, { recursive: true, force: true })
  }
})

test('compiled desktop host embeds the resource listener and shuts it down with the client', { timeout: 30000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), 'traceforge-desktop-resource-'))
  const workspace = join(root, 'workspace')
  mkdirSync(workspace)
  const child = spawn(executable, [join(root, 'config'), root], { windowsHide: true, stdio: 'pipe' })
  const pending = new Map()
  let sequence = 0
  let stderr = ''
  let resourceUrl
  child.stderr.on('data', data => { stderr += data })
  const input = createInterface({ input: child.stdout })
  input.on('line', line => {
    const message = JSON.parse(line)
    const reply = pending.get(message.id)
    pending.delete(message.id)
    if (message.error) reply?.reject(new Error(message.error))
    else reply?.resolve(message.result)
  })
  const exited = new Promise(resolve => child.once('exit', code => {
    for (const reply of pending.values()) reply.reject(new Error(`Desktop host exited ${code}: ${stderr}`))
    pending.clear()
    resolve(code)
  }))
  const invoke = (command, payload) => new Promise((resolve, reject) => {
    const id = String(++sequence)
    pending.set(id, { resolve, reject })
    child.stdin.write(JSON.stringify({ id, channel: `sdd:resources:${command}`, payload }) + '\n')
  })
  try {
    const paired = await invoke('ensure', { backend: 'opencode' })
    assert.deepEqual(await invoke('ensure', { backend: 'opencode' }), paired)
    const port = Number(new URL(paired.resource_service_url).port)
    resourceUrl = `http://127.0.0.1:${port}`
    if (process.platform === 'win32') {
      const owner = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
        `Get-NetTCPConnection -State Listen -LocalPort ${port} | Select-Object -ExpandProperty OwningProcess -Unique`],
      { encoding: 'utf8', windowsHide: true }).trim()
      assert.equal(Number(owner), child.pid)
      console.log(`Resource listener PID ${owner} equals desktop host PID ${child.pid}`)
    }
    const headers = { Authorization: `Bearer ${paired.host_token}`, 'Content-Type': 'application/json' }
    assert.equal((await fetch(`${resourceUrl}/v1/identity`)).status, 401)
    const identity = await fetch(`${resourceUrl}/v1/identity`, { headers }).then(response => response.json())
    assert.ok(identity.capabilities.includes('checkpoint'))
    assert.deepEqual(await invoke('configure-roots', {
      backend: 'opencode', resourceServiceUrl: paired.resource_service_url, workspaceRoot: workspace, repoRoots: [],
    }), { managed: true })
    const inspection = await fetch(`${resourceUrl}/v1/repositories/inspect`, { method: 'POST', headers, body: JSON.stringify({ workspace_root: workspace, repositories: [] }) })
    assert.equal(inspection.status, 200, await inspection.text())
    const escape = await fetch(`${resourceUrl}/v1/repositories/inspect`, { method: 'POST', headers, body: JSON.stringify({ workspace_root: root, repositories: [] }) })
    assert.equal(escape.status, 409)
    assert.equal(stderr, '')
  } finally {
    child.stdin.end()
    assert.equal(await exited, 0, stderr)
    input.close()
    if (resourceUrl) await assert.rejects(fetch(`${resourceUrl}/v1/identity`, { signal: AbortSignal.timeout(1000) }))
    assert.ok(root.startsWith(join(tmpdir(), 'traceforge-desktop-resource-')))
    rmSync(root, { recursive: true, force: true })
  }
})
