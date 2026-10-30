import '../platform-bun'
import { afterEach, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { createInterface } from 'node:readline'
import { startServer } from '../server'
import { canonical } from '../runtime'
import { git, hash, inside } from '../filesystem'

const roots: string[] = []
type Host = { server: { url: URL }; close: () => Promise<void>; dispatch: (kind: string, payload: any) => Promise<any> }
const services: Host[] = []
const remotes: ReturnType<typeof Bun.serve>[] = []
afterEach(async () => {
  for (const service of services.splice(0)) await service.close()
  for (const remote of remotes.splice(0)) remote.stop(true)
  for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true })
})
const operation = (task_id: string, kind: string, payload: any, operation_id = `${kind}-${task_id}`) => {
  const content = { resource_id: 'test', task_id, kind, payload, operation_id }
  return { ...content, payload_hash: hash(canonical(content)) }
}

async function setup(instrument = true) {
  const root = fs.mkdtempSync(path.join(tmpdir(), 'tf-parallel-host-')); roots.push(root)
  const source = path.join(root, 'source'), workspace = path.join(root, 'workspace'), bare = path.join(root, 'remote.git')
  fs.mkdirSync(source); fs.mkdirSync(workspace)
  git(source, 'init', '-b', 'main'); git(source, 'config', 'user.name', 'Test'); git(source, 'config', 'user.email', 'test@example.com')
  git(source, 'config', 'core.autocrlf', 'false')
  for (let index = 0; index < Number(process.env.TF_PROVISION_FILES || 200); index++) fs.writeFileSync(path.join(source, `file-${index}.txt`), `${index}:` + 'content\n'.repeat(128))
  git(source, 'add', '.'); git(source, 'commit', '-m', 'main')
  git(root, 'clone', '--bare', source, bare); git(bare, 'update-server-info')
  const remote = Bun.serve({ port: 0, hostname: '127.0.0.1', fetch(request) {
    const file = inside(path.join(bare, decodeURIComponent(new URL(request.url).pathname)), [bare])
    return fs.existsSync(file) && fs.statSync(file).isFile() ? new Response(Bun.file(file)) : new Response('missing', { status: 404 })
  } }); remotes.push(remote)
  git(source, 'remote', 'add', 'origin', remote.url.toString())
  const control = path.join(root, 'control'); fs.mkdirSync(control)
  const wrapper = path.join(root, 'worker.ts')
  const electron = process.env.TF_RESOURCE_ENGINE === 'electron'
  const workerEntry = fileURLToPath(new URL(electron ? '../../../electron/localResourceWorker.ts' : '../worker.ts', import.meta.url)).replaceAll('\\', '/')
  // Only the observation barriers are injected. Git, SQLite and snapshot work
  // execute unchanged in the real worker and through the authenticated HTTP API.
  fs.writeFileSync(wrapper, `
    import * as fs from 'node:fs'; import * as path from 'node:path';
    import { Runtime } from ${JSON.stringify(fileURLToPath(new URL('../runtime.ts', import.meta.url)).replaceAll('\\', '/'))};
    import ${JSON.stringify(workerEntry)};
    const original = Runtime.prototype.operation, control = ${JSON.stringify(control)};
    Runtime.prototype.operation = function(command, phase) {
      const name = phase === 'checkout' ? 'checkout' : command.kind === 'snapshot' ? 'snapshot' : '';
      if (name && ['a', 'b'].includes(command.task_id)) {
        fs.writeFileSync(path.join(control, name + '-' + command.task_id), String(Date.now()));
        const deadline = Date.now() + 45000;
        while (!['a', 'b'].every(id => fs.existsSync(path.join(control, name + '-' + id)))) {
          if (Date.now() > deadline) throw new Error('PARALLEL_STAGE_DID_NOT_OVERLAP:' + name);
          Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
        }
      }
      const result = original.call(this, command, phase);
      if (name) fs.writeFileSync(path.join(control, name + '-' + command.task_id + '-done'), String(Date.now()));
      return result;
    };
  `)
  const config = { state_root: path.join(root, 'state'), allowed_roots: [root], token: 't'.repeat(32), port: 0 }
  let service: Host
  if (electron) {
    // Exercise the actual bundled Electron host with Node worker_threads/sqlite.
    const hostScript = path.join(root, 'electron-host.mjs')
    const output = await Bun.build({ entrypoints: [wrapper], outdir: path.join(root, 'build'), naming: 'worker.mjs', target: 'node', format: 'esm' })
    if (!output.success) throw new Error(output.logs.join('\n'))
    fs.writeFileSync(hostScript, `
      import { startLocalResourceService } from ${JSON.stringify(new URL('../../../dist-electron/localResourceService.js', import.meta.url).href)};
      const host = await startLocalResourceService(${JSON.stringify(config)}, ${instrument ? `{ workerUrl: new URL(${JSON.stringify(pathToFileURL(path.join(root, 'build/worker.mjs')).href)}) }` : '{}'});
      console.log(JSON.stringify({ port: host.server.address().port }));
      process.stdin.once('data', async () => { await host.close(); process.exit(0); });
    `)
    const child = spawn('node', [hostScript], { windowsHide: true, stdio: ['pipe', 'pipe', 'inherit'] })
    const lines = createInterface({ input: child.stdout })
    const [line] = await Promise.race([once(lines, 'line'), once(child, 'exit').then(() => { throw new Error('Electron host exited during startup') })])
    const url = new URL(`http://127.0.0.1:${JSON.parse(line).port}`)
    service = { server: { url }, close: async () => {
      if (child.exitCode !== null) return
      const exited = once(child, 'exit'); child.stdin.end('stop'); await exited; lines.close()
    }, dispatch: async (kind, payload) => {
      const response = await fetch(new URL(kind === 'operation' ? '/v1/operations' : '/v1/' + kind, url), { method: 'POST', headers: { Authorization: 'Bearer ' + config.token, 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      const result = await response.json() as any
      if (!response.ok) throw new Error(JSON.stringify(result))
      return result
    } }
  } else service = await startServer(config, instrument ? { workerUrl: pathToFileURL(wrapper).href } : {})
  services.push(service)
  const repo = { repository_id: 'repo', local_path: source, configured_git_url: remote.url.toString(), branch_name: 'main', rel_path: 'repo', repo_url: remote.url.toString(), repo_name: 'repo' }
  const post = async (command: ReturnType<typeof operation>) => {
    const response = await fetch(new URL('/v1/operations', service.server.url), { method: 'POST', headers: { Authorization: 'Bearer ' + 't'.repeat(32), 'Content-Type': 'application/json' }, body: JSON.stringify(command) })
    const value = await response.json() as any
    expect(response.status, JSON.stringify(value)).toBe(200)
    return value
  }
  return { root, source, workspace, bare, control, service, repo, post }
}

test('two tasks pin different main commits, overlap checkout/snapshot, and replay without resetting edits', async () => {
  const { source, workspace, bare, control, repo, post } = await setup()
  const initial = git(source, 'rev-parse', 'HEAD')
  const payload = { workspace_root: workspace, repositories: [repo] }
  const first = post(operation('a', 'provision', payload))
  const deadline = Date.now() + 45000
  while (!fs.existsSync(path.join(control, 'checkout-a'))) {
    if (Date.now() > deadline) throw new Error('First checkout did not start')
    await Bun.sleep(20)
  }
  fs.writeFileSync(path.join(source, 'remote.txt'), 'remote advance')
  git(source, 'add', '.'); git(source, 'commit', '-m', 'advance main')
  git(source, 'push', bare, 'main'); git(bare, 'update-server-info')
  const [a, b] = await Promise.all([first, post(operation('b', 'provision', payload))])
  expect(a.state).toBe('SUCCEEDED'); expect(b.state).toBe('SUCCEEDED')
  expect(a.result.repositories[0].base_commit_sha).toBe(initial)
  expect(b.result.repositories[0].base_commit_sha).toBe(git(source, 'rev-parse', 'HEAD'))
  expect(fs.existsSync(path.join(a.result.task_root, 'repo', 'remote.txt'))).toBe(false)
  expect(fs.existsSync(path.join(b.result.task_root, 'repo', 'remote.txt'))).toBe(true)
  const snapshots = await Promise.all(['a', 'b'].map(task => post(operation(task, 'snapshot', { action: 'create', provider: 'opencode' }))))
  for (const captured of snapshots) expect(fs.existsSync(path.join(captured.result.root, 'worktree.json'))).toBe(true)
  for (const stage of ['checkout', 'snapshot']) {
    const read = (id: string) => Number(fs.readFileSync(path.join(control, stage + '-' + id), 'utf8'))
    expect(Math.max(read('a'), read('b'))).toBeLessThan(Math.min(read('a-done'), read('b-done')))
  }
  const marker = path.join(a.result.task_root, 'repo', 'file-0.txt'); fs.writeFileSync(marker, 'local edit')
  await Promise.all([post(operation('a', 'provision', payload)), post(operation('a', 'provision', payload))])
  expect(fs.readFileSync(marker, 'utf8')).toBe('local edit')
  await post(operation('b', 'release', {}))
  expect(fs.existsSync(path.join(b.result.task_root, 'repo'))).toBe(false)
  expect(fs.readFileSync(marker, 'utf8')).toBe('local edit')
  console.log('DESKTOP_CONCURRENCY_EVIDENCE', JSON.stringify(Object.fromEntries(fs.readdirSync(control).map(file => [file, fs.readFileSync(path.join(control, file), 'utf8')]))))
}, 180_000)

test('duplicate active provisioning is materialized once and partial registration can resume', async () => {
  const { workspace, source, bare, repo, service, post } = await setup(false)
  const hook = path.join(source, '.git/hooks/post-checkout')
  fs.writeFileSync(hook, '#!/bin/sh\nprintf "1\\n" >> "$(git rev-parse --git-common-dir)/checkout-hook-count"\n')
  fs.chmodSync(hook, 0o755)
  const payload = { workspace_root: workspace, repositories: [repo] }
  const command = operation('duplicate', 'provision', payload)
  const [a, b] = await Promise.all([post(command), post(command)])
  expect(a).toEqual(b)
  expect(fs.readFileSync(path.join(source, '.git/checkout-hook-count'), 'utf8').trim()).toBe('1')
  expect(git(path.join(a.result.task_root, 'repo'), 'status', '--porcelain')).toBe('')
  // Failure in the second repository preserves the first registration. Retrying
  // the identical operation after fixing the remote resumes that pinned SHA.
  const missing = { ...repo, repository_id: 'other', rel_path: 'other', branch_name: 'later' }
  const partial = operation('partial', 'provision', { ...payload, repositories: [repo, missing] })
  await expect(service.dispatch('operation', partial)).rejects.toThrow()
  expect(fs.existsSync(path.join(workspace, 'tasks/partial/repo/.git'))).toBe(true)
  expect(fs.existsSync(path.join(workspace, 'tasks/partial/repo/file-0.txt'))).toBe(false)
  git(bare, 'branch', 'later', 'main'); git(bare, 'update-server-info')
  const resumed = await post(partial)
  expect(resumed.result.repositories.length).toBe(2)
  expect(fs.existsSync(path.join(workspace, 'tasks/partial/other/file-0.txt'))).toBe(true)
  await service.dispatch('operation', operation('partial', 'release', {}))
  expect(fs.existsSync(path.join(workspace, 'tasks/partial/repo'))).toBe(false)
  const abandoned = operation('abandoned', 'provision', { ...payload, repositories: [repo, { ...missing, branch_name: 'absent' }] })
  await expect(service.dispatch('operation', abandoned)).rejects.toThrow()
  await service.dispatch('operation', operation('abandoned', 'release', {}))
  expect(fs.existsSync(path.join(workspace, 'tasks/abandoned/repo'))).toBe(false)
  expect(fs.existsSync(path.join(a.result.task_root, 'repo/file-0.txt'))).toBe(true)
}, 120_000)
