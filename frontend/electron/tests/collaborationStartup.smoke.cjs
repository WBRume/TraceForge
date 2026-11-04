// npm run build:electron:main && node electron/tests/collaborationStartup.smoke.cjs
// TF_COLLAB_TEST_ROOT retains fixtures; TF_COLLAB_TEST_PORT exercises a specific legacy port.
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const assert = require('node:assert/strict')
const { createHash } = require('node:crypto')
const { createServer, Server } = require('node:net')
const { execFileSync, spawnSync } = require('node:child_process')
const { pathToFileURL } = require('node:url')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
const key = createHash('sha256').update(JSON.stringify(['service', 'collaboration'])).digest('hex').slice(0, 24)
const git = (cwd, ...args) => execFileSync('git', args, { cwd, windowsHide: true, encoding: 'utf8' }).trim()

if (!process.versions.electron) {
  ;(async () => {
    const root = process.env.TF_COLLAB_TEST_ROOT || fs.mkdtempSync(path.join(os.tmpdir(), 'tf-collab-startup-'))
    const state = path.join(root, 'profile', 'local-resources', key)
    assert.equal(fs.existsSync(state), false, 'Use a new test directory; never overwrite an existing profile')
    const blocker = createServer()
    await new Promise((resolve, reject) => { blocker.once('error', reject); blocker.listen(0, '0.0.0.0', resolve) })
    try {
      const port = Number(process.env.TF_COLLAB_TEST_PORT || blocker.address().port)
      fs.mkdirSync(state, { recursive: true })
      fs.writeFileSync(path.join(state, 'host.json'), JSON.stringify({ state_root: state, allowed_roots: [root],
        token: 'x'.repeat(32), agent_token: 'y'.repeat(32), port, agent_port: port + 1, advertised_host: '127.0.0.1' }))
      const repositories = ['api', 'web'].map(slug => {
        const directory = path.join(root, slug); fs.mkdirSync(directory)
        const branch = slug === 'api' ? 'main' : 'release', repo_url = `https://example.invalid/${slug}.git`
        git(directory, 'init', '-b', branch)
        git(directory, 'config', 'user.name', 'Test'); git(directory, 'config', 'user.email', 'test@example.com')
        git(directory, 'config', 'core.autocrlf', 'false'); git(directory, 'remote', 'add', 'origin', repo_url)
        fs.writeFileSync(path.join(directory, 'shared.txt'), 'before\n'); git(directory, 'add', '.'); git(directory, 'commit', '-m', 'base')
        return { task_repository_id: slug, repository_id: slug, repo_slug: slug, rel_path: slug, repo_url,
          branch_name: branch, base_commit_sha: git(directory, 'rev-parse', 'HEAD'), local_path: fs.realpathSync(directory) }
      })
      fs.writeFileSync(path.join(root, 'repositories.json'), JSON.stringify(repositories))
      for (const phase of ['initial', 'restart']) {
        const env = { ...process.env, TF_COLLAB_TEST_ROOT: root, TF_COLLAB_TEST_PHASE: phase }
        delete env.ELECTRON_RUN_AS_NODE; delete env.VITE_DEV_SERVER_URL
        const result = spawnSync(require('electron'), [__filename], { env, windowsHide: true, encoding: 'utf8', timeout: 120_000 })
        fs.writeFileSync(path.join(root, `${phase}.log`), result.stdout + result.stderr)
        if (result.error) throw result.error
        assert.equal(result.status, 0, result.stdout + result.stderr)
        assert.match(result.stdout, /"production_ipc":true/)
        assert.doesNotMatch(result.stderr, /Error occurred in handler for 'sdd:collaboration:execute'/)
        process.stdout.write(result.stdout)
      }
      console.log(JSON.stringify({ ok: true, legacy_port: port, retained: !!process.env.TF_COLLAB_TEST_ROOT, root }))
    } finally {
      await new Promise(resolve => blocker.close(resolve))
      if (!process.env.TF_COLLAB_TEST_ROOT) {
        const target = path.resolve(root)
        if (path.dirname(target) !== path.resolve(os.tmpdir()) || !path.basename(target).startsWith('tf-collab-startup-')) throw new Error('Invalid test root')
        fs.rmSync(target, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
      }
    }
  })().catch(error => { console.error(error); process.exitCode = 1 })
} else {
  const { app, BrowserWindow } = require('electron')
  const root = process.env.TF_COLLAB_TEST_ROOT, phase = process.env.TF_COLLAB_TEST_PHASE
  app.setPath('userData', path.join(root, 'profile'))
  app.disableHardwareAcceleration()
  ;(async () => {
    // Load the shipped main entry, registration, window and isolated preload unchanged.
    await import(pathToFileURL(path.resolve(__dirname, '../../dist-electron/main.js')).href)
    await app.whenReady()
    let window
    const deadline = Date.now() + 30_000
    while (Date.now() < deadline) {
      window = BrowserWindow.getAllWindows()[0]
      if (window && await window.webContents.executeJavaScript('Boolean(window.sddDesktop)').catch(() => false)) break
      await sleep(100)
    }
    assert.ok(window)
    const invoke = (kind, payload = {}) => window.webContents.executeJavaScript(`window.sddDesktop.collaboration.execute(${JSON.stringify({ kind, payload: { task_id: 'dual', binding_id: 'binding', ...payload } })})`)
    const repositories = JSON.parse(fs.readFileSync(path.join(root, 'repositories.json'), 'utf8'))
    const identity = await invoke('describe')
    const receiptFile = path.join(root, 'receipt.json')
    if (phase === 'initial') {
      assert.equal(await invoke('binding', { optional: true }), null)
      await invoke('prepare', { directory_mode: 'MAPPED', repositories, workspace_revision: 1,
        session_generation: 1, session_revision: 1, repository_set_digest: 'dual' })
    } else {
      const receipt = JSON.parse(fs.readFileSync(receiptFile, 'utf8'))
      assert.equal(identity.client_id, receipt.client_id)
      const binding = await invoke('binding')
      assert.equal(binding.binding_id, 'binding')
      assert.deepEqual(binding.repositories.map(repo => repo.local_worktree_path), repositories.map(repo => repo.local_path))
      const replay = await invoke('capture', { operation_id: 'initial-capture' })
      assert.deepEqual(replay.manifest, receipt.manifest)
      assert.deepEqual(replay.objects, receipt.objects)
    }
    await invoke('status')
    await sleep(500)
    // onChanged resolves to an unsubscribe function, which cannot cross the process
    // boundary: the script must end on a serializable value instead of that call.
    const subscribe = () => window.webContents.executeJavaScript(`(() => {
      window.collaborationEvents = []
      window.sddDesktop.collaboration.onChanged(event => window.collaborationEvents.push(event))
      return true
    })()`)
    assert.equal(await subscribe(), true)
    for (const repo of repositories) fs.writeFileSync(path.join(repo.local_path, 'shared.txt'), `${repo.repo_slug}:${phase}\n`)
    const notifiedBy = Date.now() + 5000
    while (Date.now() < notifiedBy && !await window.webContents.executeJavaScript('window.collaborationEvents.length')) await sleep(100)
    assert.ok(await window.webContents.executeJavaScript('window.collaborationEvents.some(event => event.task_id === "dual")'))
    const status = await invoke('status', { background: true })
    assert.deepEqual(status.local_changes.map(file => file.task_repository_id).sort(), ['api', 'web'])
    const captured = await invoke('capture', { operation_id: `${phase}-capture` })
    assert.equal(captured.manifest.repositories.length, 2)
    for (const repo of repositories) {
      const digest = createHash('sha256').update(`${repo.repo_slug}:${phase}\n`).digest('hex')
      assert.ok(captured.objects.some(object => object.sha256 === digest))
      assert.equal(git(repo.local_path, 'rev-parse', 'HEAD'), repo.base_commit_sha)
    }
    assert.equal(process._getActiveHandles().filter(handle => handle instanceof Server && handle.listening).length, 0)
    const config = JSON.parse(fs.readFileSync(path.join(root, 'profile', 'local-resources', key, 'host.json'), 'utf8'))
    assert.ok(config.allowed_roots.includes(root))
    if (phase === 'initial') fs.writeFileSync(receiptFile, JSON.stringify({ client_id: identity.client_id, manifest: captured.manifest, objects: captured.objects }))
    console.log(JSON.stringify({ ok: true, phase, electron: process.versions.electron, production_ipc: true,
      preload: true, dual_repository_capture: true, file_events: true, http_listeners: 0, preserved_after_restart: phase === 'restart' }))
    app.quit()
  })().catch(error => { console.error(error); app.exit(1) })
}
