const { app } = require('electron')
const { mkdtempSync, writeFileSync } = require('node:fs')
const { join, resolve } = require('node:path')
const { pathToFileURL } = require('node:url')
const { tmpdir } = require('node:os')
const { randomBytes, createHash } = require('node:crypto')
const { execFileSync } = require('node:child_process')
const assert = require('node:assert/strict')

app.disableHardwareAcceleration()
app.whenReady().then(async () => {
  let host
  try {
    const { startLocalResourceService } = await import(pathToFileURL(resolve('dist-electron/localResourceService.js')).href)
    const root = mkdtempSync(join(tmpdir(), 'traceforge-electron-host-'))
    const configFile = join(root, 'host.json')
    const token = randomBytes(32).toString('hex')
    const config = { state_root: root, allowed_roots: [], token, port: 0, listen_host: '127.0.0.1', roots_config_path: configFile }
    writeFileSync(configFile, JSON.stringify(config))
    const crashingWorker = join(root, 'crashing-worker.mjs')
    writeFileSync(crashingWorker, "throw new Error('worker crash fixture')")
    await assert.rejects(startLocalResourceService(config, { workerUrl: pathToFileURL(crashingWorker) }), /worker crash fixture/)

    host = await startLocalResourceService(config)
    assert.equal(host.isRunning(), true)
    const port = host.server.address().port
    const url = `http://127.0.0.1:${port}`
    if (process.platform === 'win32') {
      const owner = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
        `Get-NetTCPConnection -State Listen -LocalPort ${port} | Select-Object -ExpandProperty OwningProcess -Unique`],
      { encoding: 'utf8', windowsHide: true }).trim()
      assert.equal(Number(owner), process.pid)
      console.log(`Resource listener PID ${owner} equals Electron main PID ${process.pid}`)
    }
    await assert.rejects(startLocalResourceService({ ...config, state_root: join(root, 'conflict'), port }), /EADDRINUSE/)
    assert.equal((await fetch(url + '/v1/identity')).status, 401)
    const headers = { Authorization: `Bearer ${token}`, 'content-type': 'application/json' }
    const identity = await (await fetch(url + '/v1/identity', { headers })).json()
    assert.equal(identity.protocol_version, 1)
    const command = { operation_id: 'smoke', resource_id: 'resource', task_id: 'task', kind: 'provision', payload: { workspace_root: root, repositories: [] } }
    const canonical = value => Array.isArray(value) ? '[' + value.map(canonical).join(', ') + ']'
      : value && typeof value === 'object' ? '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ': ' + canonical(value[key])).join(', ') + '}' : JSON.stringify(value)
    const payload_hash = createHash('sha256').update(canonical(command)).digest('hex')
    const execute = async () => fetch(url + '/v1/operations', { method: 'POST', headers, body: JSON.stringify({ ...command, payload_hash }) })
    assert.equal((await execute()).status, 409)
    writeFileSync(configFile, JSON.stringify({ ...config, allowed_roots: [root] }))
    const provision = await (await execute()).json()
    assert.equal(provision.state, 'SUCCEEDED')
    assert.deepEqual(await (await execute()).json(), provision)
    const journal = await (await fetch(url + '/v1/operations/smoke', { headers })).json()
    assert.equal(journal.state, 'SUCCEEDED')
    await Promise.all([host.close(), host.close()])
    assert.equal(host.isRunning(), false)
    await assert.rejects(fetch(url + '/v1/identity', { headers, signal: AbortSignal.timeout(1000) }))
    host = await startLocalResourceService({ ...config, port })
    assert.deepEqual(await (await fetch(url + '/v1/identity', { headers })).json(), identity)
    console.log('Electron embedded resources: same PID, worker failure isolation, auth, grants, provision, replay and shutdown passed')
  } catch (error) {
    console.error(error)
    process.exitCode = 1
  } finally {
    await host?.close()
    app.exit(process.exitCode || 0)
  }
})
