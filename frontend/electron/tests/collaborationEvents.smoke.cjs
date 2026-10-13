// Run after npm run build:electron:main: node electron/tests/collaborationEvents.smoke.cjs
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const assert = require('node:assert/strict')
const { pathToFileURL } = require('node:url')
const { execFileSync } = require('node:child_process')

if (!process.versions.electron) {
  process.stdout.write(execFileSync(require('electron'), [__filename], {
    env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' }, windowsHide: true, encoding: 'utf8', timeout: 120000,
  }))
} else {
  ;(async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'tf-electron-events-'))
    let service
    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
    try {
      const { startLocalResourceService } = await import(pathToFileURL(path.resolve(__dirname, '../../dist-electron/localResourceService.js')).href)
      const repositories = ['api', 'web'].map(slug => {
        const directory = path.join(root, slug); fs.mkdirSync(directory)
        const git = (...args) => execFileSync('git', args, { cwd: directory, windowsHide: true, encoding: 'utf8' }).trim()
        const branch = slug === 'api' ? 'main' : 'release', repo_url = `https://example.invalid/${slug}.git`
        git('init', '-b', branch); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.com')
        git('config', 'core.autocrlf', 'false'); git('remote', 'add', 'origin', repo_url)
        fs.writeFileSync(path.join(directory, 'shared.txt'), 'before\n'); git('add', '.'); git('commit', '-m', 'base')
        return { task_repository_id: slug, repository_id: slug, repo_slug: slug, rel_path: slug, repo_url,
          branch_name: branch, base_commit_sha: git('rev-parse', 'HEAD'), local_path: fs.realpathSync(directory) }
      })
      let notify
      const events = []
      service = await startLocalResourceService({ state_root: path.join(root, 'state'), allowed_roots: [root], token: 'x'.repeat(32), port: 0 }, {
        onCollaborationChanged: event => { events.push(event); notify?.() },
      })
      const run = (kind, payload = {}) => service.dispatch('collaboration', { kind, payload: { task_id: 'dual', binding_id: 'binding', ...payload } })
      await run('prepare', { directory_mode: 'MAPPED', repositories, workspace_revision: 1, session_generation: 1, session_revision: 1, repository_set_digest: 'dual' })
      await sleep(400); events.length = 0
      const began = Date.now()
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => { notify = undefined; reject(new Error('No native file notification')) }, 5000)
        notify = () => { clearTimeout(timer); notify = undefined; resolve() }
        for (const repo of repositories) fs.writeFileSync(path.join(repo.local_path, 'shared.txt'), `${repo.repo_slug}:edited\n`)
      })
      const notificationMs = Date.now() - began
      assert.ok(events.every(event => event.task_id === 'dual'))
      const status = await run('status', { background: true })
      assert.deepEqual(status.local_changes.map(file => file.task_repository_id).sort(), ['api', 'web'])
      assert.ok(status.scan_metrics.every(scan => scan.kind === 'git-delta' && scan.files_read === 1))
      await sleep(400); events.length = 0
      await run('status', { background: true }); await sleep(400)
      assert.equal(events.length, 0, 'reading status must not create a refresh loop')
      await run('suspend')
      for (const repo of repositories) fs.writeFileSync(path.join(repo.local_path, 'shared.txt'), 'disconnected\n')
      await sleep(400)
      assert.equal(events.length, 0, 'suspended bindings must stop notifying')
      console.log(JSON.stringify({ ok: true, electron: process.versions.electron, notificationMs, repositories: 2, filesRead: status.scan_metrics.map(scan => scan.files_read), idleEvents: 0, suspendedEvents: 0 }))
    } finally {
      await service?.close()
      const resolved = path.resolve(root)
      if (path.dirname(resolved) !== path.resolve(os.tmpdir()) || !path.basename(resolved).startsWith('tf-electron-events-')) throw new Error('Invalid test root')
      fs.rmSync(resolved, { recursive: true, force: true })
    }
  })().catch(error => { console.error(error); process.exitCode = 1 })
}
