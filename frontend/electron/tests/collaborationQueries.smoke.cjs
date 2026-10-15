// Run after npm run build:electron:main: node electron/tests/collaborationQueries.smoke.cjs
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const assert = require('node:assert/strict')
const { createHash } = require('node:crypto')
const { pathToFileURL } = require('node:url')

if (!process.versions.electron) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'tf-electron-queries-'))
  try {
    const env = { ...process.env, TF_QUERY_TEST_ROOT: root }
    delete env.ELECTRON_RUN_AS_NODE
    const result = require('node:child_process').spawnSync(require('electron'), [__filename], {
      env, windowsHide: true, encoding: 'utf8', timeout: 120_000,
    })
    if (result.error) throw result.error
    assert.equal(result.status, 0, result.stdout + result.stderr)
    assert.doesNotMatch(result.stderr, /Error occurred in handler for 'sdd:collaboration:execute'/)
    process.stdout.write(result.stdout)
  } finally {
    const target = path.resolve(root)
    if (path.dirname(target) !== path.resolve(os.tmpdir()) || !path.basename(target).startsWith('tf-electron-queries-')) throw new Error('Invalid test root')
    fs.rmSync(target, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
  }
} else {
  const { app, BrowserWindow, ipcMain } = require('electron')
  const root = process.env.TF_QUERY_TEST_ROOT
  app.setPath('userData', path.join(root, 'profile'))
  app.disableHardwareAcceleration()
  app.whenReady().then(async () => {
    let host, window
    const channel = 'sdd:collaboration:execute'
    try {
      const { startLocalResourceService } = await import(pathToFileURL(path.resolve(__dirname, '../../dist-electron/localResourceService.js')).href)
      host = await startLocalResourceService({ state_root: path.join(root, 'state'), allowed_roots: [root], token: 'x'.repeat(32), port: 0, listen_host: '127.0.0.1' })
      ipcMain.handle(channel, (_event, command) => host.dispatch('collaboration', command))
      window = new BrowserWindow({ show: false, webPreferences: { nodeIntegration: true, contextIsolation: false, sandbox: false } })
      await window.loadURL('about:blank')
      const invoke = (kind, payload) => window.webContents.executeJavaScript(`require('electron').ipcRenderer.invoke(${JSON.stringify(channel)}, ${JSON.stringify({ kind, payload: { ...payload, delta_transport: true } })})`)
      const task_id = 'f4ab3689-7562-4da0-94fc-562a7ff1f416'
      assert.equal(await invoke('binding', { task_id, optional: true }), null)
      const sha256 = createHash('sha256').update('cloud preview').digest('hex')
      assert.equal(await invoke('read_object', { sha256, optional: true }), null)
      assert.equal(fs.existsSync(path.join(root, 'state', 'collaboration', 'bindings')), false)
      await assert.rejects(host.dispatch('collaboration', { kind: 'status', payload: { task_id } }), /COLLABORATION_BINDING_MISSING/)
      await assert.rejects(host.dispatch('collaboration', { kind: 'read_object', payload: { sha256 } }), /LOCAL_CONTENT_OBJECT_MISSING/)
      for (const text of ['cloud preview', '']) {
        const digest = createHash('sha256').update(text).digest('hex'), content = Buffer.from(text).toString('base64')
        await invoke('cache_objects', { objects: [{ sha256: digest, content }] })
        assert.deepEqual(await invoke('read_object', { sha256: digest, optional: true }), { sha256: digest, content })
      }
      console.log(JSON.stringify({ ok: true, electron: process.versions.electron, node: process.versions.node,
        renderer_ipc_worker: true, missing_binding: null, missing_object: null, cached_and_empty_files: true, required_reads_reject: true }))
    } catch (error) {
      console.error(error)
      process.exitCode = 1
    } finally {
      window?.destroy()
      ipcMain.removeHandler(channel)
      await host?.close()
      app.exit(process.exitCode || 0)
    }
  })
}
