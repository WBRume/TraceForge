const { app, utilityProcess } = require('electron')
const { mkdtempSync, writeFileSync } = require('node:fs')
const { join, resolve } = require('node:path')
const { tmpdir } = require('node:os')
const { randomBytes, createHash } = require('node:crypto')
const { createServer } = require('node:net')
const assert = require('node:assert/strict')

app.disableHardwareAcceleration()
app.whenReady().then(async () => {
  let host
  try {
    const listener = createServer()
    await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve))
    const port = listener.address().port
    await new Promise(resolve => listener.close(resolve))
    const root = mkdtempSync(join(tmpdir(), 'traceforge-electron-host-'))
    const config = join(root, 'host.json')
    const token = randomBytes(32).toString('hex')
    writeFileSync(config, JSON.stringify({ state_root: root, allowed_roots: [], token, port, listen_host: '127.0.0.1' }))
    host = utilityProcess.fork(resolve('dist-electron/resourceHost.js'), [config], { stdio: 'pipe' })
    host.stderr.on('data', data => process.stderr.write(data))
    await Promise.race([
      new Promise((resolve, reject) => {
        host.stdout.on('data', data => { if (data.toString().includes('Resource Host ready')) resolve() })
        host.once('exit', code => reject(new Error(`Host exited: ${code}`)))
      }),
      new Promise((_, reject) => setTimeout(() => reject(new Error('Host startup timed out')), 15000)),
    ])
    const url = `http://127.0.0.1:${port}`
    assert.equal((await fetch(url + '/v1/identity')).status, 401)
    const headers = { Authorization: `Bearer ${token}`, 'content-type': 'application/json' }
    const identity = await (await fetch(url + '/v1/identity', { headers })).json()
    assert.equal(identity.protocol_version, 1)
    const command = { operation_id: 'smoke', resource_id: 'resource', task_id: 'task', kind: 'provision', payload: { workspace_root: root, repositories: [] } }
    const canonical = value => Array.isArray(value) ? '[' + value.map(canonical).join(', ') + ']'
      : value && typeof value === 'object' ? '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ': ' + canonical(value[key])).join(', ') + '}' : JSON.stringify(value)
    const payload_hash = createHash('sha256').update(canonical(command)).digest('hex')
    const execute = async () => fetch(url + '/v1/operations', { method: 'POST', headers, body: JSON.stringify({ ...command, payload_hash }) })
    assert.equal((await execute()).status, 409) // No directory grant at startup.
    writeFileSync(config, JSON.stringify({ state_root: root, allowed_roots: [root], token, port, listen_host: '127.0.0.1' }))
    const provision = await (await execute()).json()
    assert.equal(provision.state, 'SUCCEEDED')
    assert.deepEqual(await (await execute()).json(), provision)
    const journal = await (await fetch(url + '/v1/operations/smoke', { headers })).json()
    assert.equal(journal.state, 'SUCCEEDED')
    console.log('Electron Resource Host: identity, auth, dynamic grants, provision, journal and replay passed')
  } catch (error) {
    console.error(error)
    process.exitCode = 1
  } finally {
    host?.kill()
    app.exit(process.exitCode || 0)
  }
})
