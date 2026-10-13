import { afterEach, expect, test } from 'bun:test'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { startServer } from '../server'
import { git, resolved } from '../filesystem'

const roots: string[] = []
const services: Awaited<ReturnType<typeof startServer>>[] = []
const headers = { Authorization: 'Bearer ' + 'x'.repeat(32) }

afterEach(async () => {
  await Promise.all(services.splice(0).map(service => service.close()))
  for (const root of roots.splice(0)) {
    if (!root.startsWith(join(tmpdir(), 'tf-resource-lifecycle-'))) throw new Error('Invalid test directory')
    rmSync(root, { recursive: true, force: true })
  }
})

function config() {
  const root = mkdtempSync(join(tmpdir(), 'tf-resource-lifecycle-'))
  roots.push(root)
  return { state_root: root, allowed_roots: [], token: 'x'.repeat(32), port: 0 }
}

test('embedded startup failure does not stop the desktop runtime', async () => {
  for (const script of ["throw new Error('worker crash fixture')", 'self.close()']) {
    const settings = config()
    const workerFile = join(settings.state_root, 'failed-worker.ts')
    writeFileSync(workerFile, script)
    await expect(startServer(settings, { workerUrl: pathToFileURL(workerFile).href })).rejects.toThrow()
    const service = await startServer(settings)
    services.push(service)
    expect(service.isRunning()).toBe(true)
    expect((await fetch(new URL('/v1/identity', service.server.url), { headers })).status).toBe(200)
  }
})

test('occupied ports release initialization state and leave the running service intact', async () => {
  const service = await startServer(config())
  services.push(service)
  const other = config()
  await expect(startServer({ ...other, port: service.server.port })).rejects.toThrow()
  expect((await fetch(new URL('/v1/identity', service.server.url), { headers })).status).toBe(200)
  const retry = await startServer(other)
  services.push(retry)
  expect(retry.isRunning()).toBe(true)
})

test('shutdown is idempotent and releases the port and journal for restart', async () => {
  const settings = config()
  const service = await startServer(settings)
  services.push(service)
  const port = service.server.port
  const url = new URL('/v1/identity', service.server.url)
  const identity = await fetch(url, { headers }).then(response => response.json())
  await Promise.all([service.close(), service.close()])
  expect(service.isRunning()).toBe(false)
  await expect(fetch(url, { headers })).rejects.toThrow()
  const restarted = await startServer({ ...settings, port })
  services.push(restarted)
  expect(await fetch(url, { headers }).then(response => response.json())).toEqual(identity)
})

test('dual repository file changes notify the desktop without polling and stop when suspended', async () => {
  const settings = config()
  const repositories = ['api', 'web'].map(slug => {
    const local_path = join(settings.state_root, slug)
    mkdirSync(local_path)
    git(local_path, 'init', '-b', slug === 'api' ? 'main' : 'release')
    git(local_path, 'config', 'user.name', 'Test'); git(local_path, 'config', 'user.email', 'test@example.com')
    git(local_path, 'config', 'core.autocrlf', 'false')
    const repo_url = `https://example.invalid/${slug}.git`
    git(local_path, 'remote', 'add', 'origin', repo_url)
    writeFileSync(join(local_path, 'shared.txt'), 'before\n')
    git(local_path, 'add', '.'); git(local_path, 'commit', '-m', 'base')
    return { task_repository_id: slug, repository_id: slug, repo_slug: slug, rel_path: slug, repo_url,
      branch_name: slug === 'api' ? 'main' : 'release', base_commit_sha: git(local_path, 'rev-parse', 'HEAD'), local_path: resolved(local_path) }
  })
  const events: { task_id: string }[] = []
  let changeReady: (() => void) | undefined
  const service = await startServer({ ...settings, allowed_roots: [settings.state_root] }, { onCollaborationChanged: event => { events.push(event); changeReady?.() } })
  services.push(service)
  const prepared = await service.dispatch('collaboration', { kind: 'prepare', payload: { directory_mode: 'MAPPED', task_id: 'dual', binding_id: 'binding', repositories,
    session_generation: 1, session_revision: 1, repository_set_digest: 'dual', workspace_revision: 1 } })
  await Bun.sleep(400); events.length = 0
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => { changeReady = undefined; reject(new Error('No file change notification')) }, 5000)
    changeReady = () => { clearTimeout(timer); changeReady = undefined; resolve() }
    for (const repo of repositories) writeFileSync(join(repo.local_path, 'shared.txt'), `${repo.repo_slug}:edited\n`)
  })
  expect(events.every(event => event.task_id === 'dual')).toBe(true)
  const changed = await service.dispatch('collaboration', { kind: 'status', payload: { task_id: 'dual', background: true } })
  expect(changed.local_changes.map((file: any) => file.task_repository_id).sort()).toEqual(['api', 'web'])
  expect(changed.scan_metrics.every((scan: any) => scan.kind === 'git-delta' && scan.files_read === 1)).toBe(true)
  await Bun.sleep(400); events.length = 0
  // Reading status uses a filesystem barrier; it must not trigger another refresh.
  await service.dispatch('collaboration', { kind: 'status', payload: { task_id: 'dual', background: true } })
  await Bun.sleep(400)
  expect(events).toHaveLength(0)
  await service.dispatch('collaboration', { kind: 'suspend', payload: { task_id: 'dual', binding_id: prepared.binding_id } })
  for (const repo of repositories) writeFileSync(join(repo.local_path, 'shared.txt'), 'disconnected edit\n')
  await Bun.sleep(400)
  expect(events).toHaveLength(0)
}, 60000)
