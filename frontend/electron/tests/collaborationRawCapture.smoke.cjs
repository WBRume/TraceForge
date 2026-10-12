// Run with: node electron/tests/collaborationRawCapture.smoke.cjs
// The assertions run inside the installed Electron's Node runtime, never Bun.
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')

if (!process.versions.electron) {
  const result = execFileSync(require('electron'), [__filename, ...process.argv.slice(2)], {
    env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' }, windowsHide: true,
    encoding: 'utf8', timeout: 240_000,
  })
  process.stdout.write(result)
} else {
  ;(async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'tf-electron-raw-'))
  const oldLoader = require.extensions['.ts']
  let runtime
  try {
    const ts = require('typescript')
    require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.CommonJS }, fileName: filename,
    }).outputText, filename)
    const { CollaborationRuntime } = require('../../desktop/local-resource/collaboration.ts')
    const source = path.join(root, 'source'); fs.mkdirSync(source)
    const git = (...args) => execFileSync('git', args, { cwd: source, windowsHide: true, encoding: 'utf8' }).trim()
    git('init', '-b', 'main'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.com')
    git('config', 'core.autocrlf', 'false')
    fs.writeFileSync(path.join(source, 'source.txt'), 'before')
    git('add', '.'); git('commit', '-m', 'fixture')
    const url = 'https://example.com/team/source.git'; git('remote', 'add', 'origin', url)
    runtime = new CollaborationRuntime(path.join(root, 'state'), () => [root])
    const mapped = process.argv.includes('--mapped')
    const prepared = runtime.execute('prepare', { task_id: 'task', binding_id: 'binding', workspace_root: path.join(root, 'tasks'), directory_mode: mapped ? 'MAPPED' : undefined,
      session_generation: 1, session_revision: 1, repository_set_digest: 'set', workspace_revision: 1,
      repositories: [{ task_repository_id: 'repo', repository_id: 'repo', repo_url: url, repo_slug: 'source', rel_path: 'source',
        branch_name: 'main', base_commit_sha: git('rev-parse', 'HEAD'), local_path: source, configured_git_url: url }] })
    if (mapped) assert.equal(prepared.repositories[0].local_worktree_path, fs.realpathSync(source))
    const file = path.join(prepared.repositories[0].local_worktree_path, 'source.txt')
    const digest = data => require('node:crypto').createHash('sha256').update(data).digest('hex')
    const entry = manifest => manifest.repositories[0].files.find(item => item.path === 'source.txt')
    const fixedTime = 1_700_000_000
    const write = content => { fs.writeFileSync(file, content); fs.utimesSync(file, fixedTime, fixedTime) }
    const incremental = status => {
      assert.ok(status.scan_metrics.length > 0)
      assert.ok(status.scan_metrics.every(scan => ['git', 'git-delta', 'cached'].includes(scan.kind)))
      assert.ok(status.scan_metrics.every(scan => scan.forced_content_checks === 0))
    }
    incremental(prepared)
    write('before')
    runtime.execute('status', { task_id: 'task' })
    const before = fs.statSync(file, { bigint: true })
    write('edited')
    await new Promise(resolve => setTimeout(resolve, 100))
    const after = fs.statSync(file, { bigint: true })
    assert.equal(before.ino, after.ino)
    assert.equal(before.size, after.size)
    assert.equal(before.mtimeNs, after.mtimeNs, 'mtime restoration must be exact, without Date truncation')
    const captured = await runtime.executeAsync('capture', { task_id: 'task', operation_id: 'fixed-input', include_objects: false, background: true })
    assert.equal(entry(captured.manifest).sha256, digest('edited'))
    incremental(captured.status)
    assert.equal(captured.status.scan_metrics[0].new_blobs, 1)
    assert.equal(captured.status.scan_metrics[0].new_blob_bytes, 6)
    assert.equal(captured.status.scan_metrics[0].kind, 'git-delta')
    assert.equal(captured.status.scan_metrics[0].paths_checked, 1)
    write('laterr')
    await new Promise(resolve => setTimeout(resolve, 100))
    const repeated = runtime.execute('capture', { task_id: 'task', operation_id: 'fixed-input', include_objects: false })
    assert.deepEqual(repeated.manifest, captured.manifest)
    const accepted = { ...captured.manifest, snapshot_id: 'input', workspace_revision: 2 }
    incremental(runtime.execute('accept_input', { task_id: 'task', operation_id: 'fixed-input', target: accepted }))
    const target = structuredClone(accepted)
    target.snapshot_id = 'output'; target.workspace_revision = 3; target.source = 'AGENT_OUTPUT'
    entry(target).sha256 = runtime.objects.put(Buffer.from('cloud!'))
    runtime.execute('status', { task_id: 'task' })
    write('local!')
    const pending = runtime.execute('reconcile', { task_id: 'task', operation_id: 'delivery', target })
    assert.equal(pending.state, 'CONFLICT_PENDING')
    assert.equal(pending.conflicts[0].expected_sha256, digest('local!'))
    assert.equal(pending.scan_metrics[0].kind, 'git')
    write('raced!')
    const refused = runtime.execute('restore', { task_id: 'task', operation_id: 'stale-restore', conflict_set_id: pending.conflict_set_id,
      selected: [{ task_repository_id: 'repo', path: 'source.txt', expected_sha256: digest('local!') }] })
    assert.equal(refused.state, 'RECOVERY_REQUIRED')
    assert.equal(fs.readFileSync(file, 'utf8'), 'raced!')
    const refreshed = runtime.execute('reconcile', { task_id: 'task', operation_id: 'delivery-recheck', target })
    const restored = runtime.execute('restore', { task_id: 'task', operation_id: 'confirmed-restore', conflict_set_id: refreshed.conflict_set_id,
      selected: [{ task_repository_id: 'repo', path: 'source.txt', expected_sha256: digest('raced!') }] })
    assert.equal(restored.state, 'READY')
    assert.deepEqual(restored.scan_metrics, [], 'selected restore must not capture any whole repository')
    assert.equal(fs.readFileSync(file, 'utf8'), 'cloud!')
    assert.equal(runtime.objects.get(digest('raced!')).toString(), 'raced!')
    console.log(JSON.stringify({ ok: true, electron: process.versions.electron, node: process.versions.node,
      platform: process.platform, directory_mode: mapped ? 'MAPPED' : 'ISOLATED', exact_mtime_restored: true, ctime_collided: before.ctimeNs === after.ctimeNs,
      verified: ['Git prepare', 'immutable Git input', 'only new OID exported', 'Git accept receipt', 'Git delivery', 'stale restore refused', 'selected restore backup'] }))
  } finally {
    runtime?.close()
    if (oldLoader) require.extensions['.ts'] = oldLoader; else delete require.extensions['.ts']
    // This directory is created exclusively by this test and never contains a user worktree.
    fs.rmSync(root, { recursive: true, force: true })
  }
  })().catch(error => { console.error(error); process.exitCode = 1 })
}
