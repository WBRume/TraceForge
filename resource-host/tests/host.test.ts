import '../src/platform-bun'
import { afterEach, beforeEach, describe, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { startServer } from '../src/server'
import { canonical } from '../src/runtime'
import { git, hash, inside, remoteKey } from '../src/filesystem'
import { encodeSegment, forkSession, locateSession, projectKey } from '../src/provider'

let root: string, workspace: string, host: Awaited<ReturnType<typeof startServer>>, gitServer: ReturnType<typeof Bun.serve> | null
const headers = { Authorization: 'Bearer ' + 'x'.repeat(32), 'Content-Type': 'application/json' }
const body = (kind: string, payload: any, operation_id: string, task_id = 'task') => {
  const content = { task_id, resource_id: 'resource', kind, payload, operation_id }
  return { ...content, payload_hash: hash(canonical(content)) }
}
async function post(kind: string, payload: any, key: string, task = 'task') {
  const response = await fetch(new URL('/v1/operations', host.server.url), { method: 'POST', headers, body: JSON.stringify(body(kind, payload, key, task)) })
  return { status: response.status, data: await response.json() as any }
}
async function ok(kind: string, payload: any, key: string, task = 'task') {
  const response = await post(kind, payload, key, task)
  expect(response, JSON.stringify(response.data)).toMatchObject({ status: 200 })
  return response.data.result
}
beforeEach(async () => {
  root = fs.mkdtempSync(path.join(tmpdir(), 'tf-ts-host-'))
  workspace = path.join(root, 'workspace'); fs.mkdirSync(workspace)
  host = await startServer({ state_root: path.join(root, 'state'), allowed_roots: [workspace], token: 'x'.repeat(32), port: 0 })
  gitServer = null
})
afterEach(async () => { await host.close(); gitServer?.stop(true); fs.rmSync(root, { recursive: true, force: true }) })

async function repository() {
  const source = path.join(workspace, 'personal'), bare = path.join(root, 'remote.git')
  fs.mkdirSync(source)
  git(source, 'init', '-b', 'main'); git(source, 'config', 'core.autocrlf', 'false'); git(source, 'config', 'user.name', 'Test'); git(source, 'config', 'user.email', 'test@example.com')
  fs.writeFileSync(path.join(source, 'code.txt'), 'base\n')
  git(source, 'add', '.'); git(source, 'commit', '-m', 'base')
  git(root, 'clone', '--bare', source, bare); git(bare, 'update-server-info')
  gitServer = Bun.serve({ port: 0, hostname: '127.0.0.1', fetch(request) {
    const target = inside(path.join(bare, decodeURIComponent(new URL(request.url).pathname)), [bare])
    return fs.existsSync(target) && fs.statSync(target).isFile() ? new Response(Bun.file(target), { headers: { 'Content-Type': 'text/plain' } }) : new Response('missing', { status: 404 })
  } })
  const url = gitServer.url.toString().replace(/\/$/, '')
  git(source, 'remote', 'add', 'origin', 'https://git.example/upstream/project.git')
  git(source, 'remote', 'add', 'mine', url)
  const repo = { repository_id: 'repo', local_path: source, configured_git_url: url, branch_name: 'main', rel_path: 'repo', repo_url: 'https://git.example/upstream/project.git', repo_name: 'project' }
  return { source, repo }
}

describe('HTTP protocol and ownership', () => {
  test('auth, canonical Python hash, replay, ID conflict, path and .git guards', async () => {
    expect((await fetch(new URL('/v1/identity', host.server.url))).status).toBe(401)
    expect(canonical({ z: '中文', a: [1, true, null] })).toBe('{"a": [1, true, null], "z": "中文"}')
    const payload = { workspace_root: workspace, repositories: [] }
    expect((await post('provision', { ...payload, workspace_root: root }, 'escape')).status).toBe(409)
    expect((await post('materialize', { files: [] }, 'unbound')).status).toBe(409)
    const receipt = await ok('provision', payload, 'provision')
    expect(await ok('provision', payload, 'provision')).toEqual(receipt)
    expect((await post('provision', { ...payload, repositories: ['different'] }, 'provision')).status).toBe(409)
    for (const relative of ['../escape', '.git/config', 'x/../../escape']) {
      expect((await post('materialize', { files: [{ path: relative, content: 'eA==', sha256: hash('x') }] }, 'file-' + hash(relative))).status).toBe(409)
    }
    expect(fs.existsSync(path.join(workspace, 'tasks/escape'))).toBe(false)
  })
  test('serves monitoring dashboard and status API without requiring bearer auth', async () => {
    const dashRes = await fetch(new URL('/', host.server.url))
    expect(dashRes.status).toBe(200)
    expect(dashRes.headers.get('content-type')).toContain('text/html')
    const dashHtml = await dashRes.text()
    expect(dashHtml).toContain('TraceForge Resource Host')

    const statusRes = await fetch(new URL('/v1/status', host.server.url))
    expect(statusRes.status).toBe(200)
    const statusData = await statusRes.json() as any
    expect(statusData.status).toBe('running')
    expect(statusData.port).toBe(host.server.port)
  })
  test('checks personal fork across all fetch remotes and keeps the original dirty tree', async () => {
    const { source, repo } = await repository()
    fs.writeFileSync(path.join(source, 'code.txt'), 'personal uncommitted\n')
    const inspection = await fetch(new URL('/v1/repositories/inspect', host.server.url), { method: 'POST', headers, body: JSON.stringify({ workspace_root: workspace, repositories: [repo] }) })
    expect((await inspection.json() as any).repositories[0].matched_remote).toBe('mine')
    const receipt = await ok('provision', { workspace_root: workspace, repositories: [repo] }, 'provision')
    expect(fs.readFileSync(path.join(receipt.task_root, 'repo/code.txt'), 'utf8')).toBe('base\n')
    expect(fs.readFileSync(path.join(source, 'code.txt'), 'utf8')).toBe('personal uncommitted\n')
    expect(remoteKey('git@example.com:person/repo.git')).toBe(remoteKey('https://example.com/person/repo.git'))
  }, 30_000)
})

test('binary patches use a temporary index and apply to a separate worktree', async () => {
  const { source, repo } = await repository()
  const receipt = await ok('provision', { workspace_root: workspace, repositories: [repo] }, 'provision')
  const cwd = path.join(receipt.task_root, 'repo')
  const index = path.resolve(cwd, git(cwd, 'rev-parse', '--git-path', 'index'))
  const before = hash(fs.readFileSync(index))
  fs.writeFileSync(path.join(cwd, 'code.txt'), 'changed\n')
  fs.writeFileSync(path.join(cwd, 'blob.bin'), Buffer.from([0, 1, 2, 255]))
  const patch = (await ok('generate_patch', {}, 'patch')).repositories[0]
  expect(hash(patch.patch_text)).toBe(patch.sha256)
  expect(patch.files.some((file: any) => file.is_binary)).toBe(true)
  expect(hash(fs.readFileSync(index))).toBe(before)
  const applied = await ok('apply_patch', { workspace_root: workspace, repositories: [{ ...repo, repo_slug: 'repo', base_branch: 'main', base_commit_sha: patch.base_commit_sha, patch: Buffer.from(patch.patch_text).toString('base64'), sha256: patch.sha256 }] }, 'apply', 'apply-task')
  expect(applied.status).toBe('applied')
  expect(fs.readFileSync(path.join(applied.repositories[0].path, 'blob.bin'))).toEqual(Buffer.from([0, 1, 2, 255]))
  expect(fs.readFileSync(path.join(source, 'code.txt'), 'utf8')).toBe('base\n')
  expect((await post('release', {}, 'release')).data.detail.message).toContain('WORKTREE_HAS_CHANGES')
}, 30_000)

test('checkpoint restores Git index and files while preserving dependencies, supports compensation', async () => {
  const { repo } = await repository()
  const receipt = await ok('provision', { workspace_root: workspace, repositories: [repo] }, 'provision')
  const cwd = path.join(receipt.task_root, 'repo')
  fs.mkdirSync(path.join(cwd, 'node_modules')); fs.writeFileSync(path.join(cwd, 'node_modules/keep'), 'old dependency')
  fs.writeFileSync(path.join(cwd, 'node_modules/tracked.txt'), 'tracked dependency')
  git(cwd, 'add', '-f', 'node_modules/tracked.txt')
  git(cwd, 'commit', '-m', 'tracked dependency')
  git(cwd, 'checkout', '--detach', 'HEAD')
  const checkpoint = await ok('snapshot', { action: 'create', provider: 'opencode' }, 'checkpoint')
  fs.writeFileSync(path.join(cwd, 'code.txt'), 'new\n'); git(cwd, 'add', 'code.txt')
  fs.writeFileSync(path.join(cwd, 'added.txt'), 'new file')
  fs.writeFileSync(path.join(cwd, 'node_modules/keep'), 'new dependency')
  fs.writeFileSync(path.join(cwd, 'node_modules/tracked.txt'), 'changed tracked dependency')
  const backup = path.join(checkpoint.root, 'current-worktree')
  await ok('snapshot', { action: 'restore_worktree', checkpoint_root: checkpoint.root, backup_path: backup }, 'restore')
  expect(fs.readFileSync(path.join(cwd, 'code.txt'), 'utf8')).toBe('base\n')
  expect(fs.existsSync(path.join(cwd, 'added.txt'))).toBe(false)
  expect(git(cwd, 'diff', '--cached')).toBe('')
  expect(fs.readFileSync(path.join(cwd, 'node_modules/keep'), 'utf8')).toBe('new dependency')
  expect(fs.readFileSync(path.join(cwd, 'node_modules/tracked.txt'), 'utf8')).toBe('tracked dependency')
  await ok('snapshot', { action: 'restore_worktree', checkpoint_root: backup, backup_path: path.join(checkpoint.root, 'compensation') }, 'compensate')
  expect(git(cwd, 'diff', '--cached')).toContain('+new')
  expect(fs.readFileSync(path.join(cwd, 'added.txt'), 'utf8')).toBe('new file')
}, 30_000)

test('documents and skills preserve runtime folders and reject traversal', async () => {
  await ok('provision', { workspace_root: workspace, repositories: [] }, 'provision')
  const saved = await ok('documents', { action: 'save', section: 'plans', path: 'nested/design.md', content: '# Design' }, 'save')
  expect(saved.relative_path).toBe('docs/superpowers/plans/nested/design.md')
  expect((await ok('documents', { action: 'list' }, 'list')).plans).toHaveLength(1)
  const file = { path: '.agents/skills/runtime/SKILL.md', content: Buffer.from('skill').toString('base64'), sha256: hash('skill') }
  await ok('skills', { action: 'replace', files: [file], preserve: false }, 'skill')
  await ok('skills', { action: 'replace', files: [], preserve: true }, 'preserve')
  expect((await ok('skills', { action: 'read', folder: 'runtime', path: 'SKILL.md' }, 'read')).content).toBe('skill')
  expect((await ok('skills', { action: 'manifest' }, 'manifest')).items[0].config_deleted).toBe(true)
  expect((await post('skills', { action: 'read', folder: 'runtime', path: '../../elsewhere' }, 'invalid')).status).toBe(409)
})

test.each([false, true])('DSH cold fork rewrites identity and truncates stale sequence tail, zstd=%s', compressed => {
  const sessions = path.join(root, 'sessions'), cwd = workspace, id = 'original'
  const directory = path.join(sessions, projectKey(cwd), encodeSegment(id))
  fs.mkdirSync(directory, { recursive: true })
  const header = JSON.stringify({ type: 'session', id, cwd }) + '\n'
  const events = [JSON.stringify({ seq: 0, text: 'first' }), JSON.stringify({ seq0: 1, data: { dt: [1, 2] } }), JSON.stringify({ seq: 99 })].join('\n') + '\n'
  fs.writeFileSync(path.join(directory, 'session.jsonl' + (compressed ? '.zstd' : '')), compressed ? Buffer.concat([Bun.zstdCompressSync(header), Bun.zstdCompressSync(events)]) : header + events)
  fs.writeFileSync(path.join(directory, 'attachment.txt'), 'attachment')
  const next = forkSession(sessions, id, cwd), file = locateSession(sessions, next)!
  const data = fs.readFileSync(file), rows = (compressed ? Bun.zstdDecompressSync(data) : data).toString().trim().split('\n').map(line => JSON.parse(line))
  expect(rows).toHaveLength(3); expect(rows[0].id).toBe(next); expect(rows[0].cwd).toBe(cwd)
  expect(fs.readFileSync(path.join(path.dirname(file), 'attachment.txt'), 'utf8')).toBe('attachment')
})

test('starts without directory grants and reloads explicit grants without restart', async () => {
  await host.close()
  const configPath = path.join(root, 'host.json')
  const config = { state_root: path.join(root, 'state'), allowed_roots: [] as string[], token: 'x'.repeat(32), port: 0 }
  fs.writeFileSync(configPath, JSON.stringify(config))
  host = await startServer({ ...config, roots_config_path: configPath })
  const identity = await fetch(new URL('/v1/identity', host.server.url), { headers }).then(r => r.json())
  const inspect = () => fetch(new URL('/v1/repositories/inspect', host.server.url), { method: 'POST', headers, body: JSON.stringify({ workspace_root: workspace, repositories: [] }) })
  expect((await inspect()).status).toBe(409)
  fs.writeFileSync(configPath, JSON.stringify({ ...config, allowed_roots: [workspace] }))
  expect((await inspect()).status).toBe(200)
  expect(await fetch(new URL('/v1/identity', host.server.url), { headers }).then(r => r.json())).toEqual(identity)
})

test('grants directory roots via authenticated API and persists to config file', async () => {
  await host.close()
  const configPath = path.join(root, 'host-grant.json')
  const config = { state_root: path.join(root, 'state'), allowed_roots: [] as string[], token: 'x'.repeat(32), port: 0 }
  fs.writeFileSync(configPath, JSON.stringify(config))
  host = await startServer({ ...config, roots_config_path: configPath })

  const inspect = () => fetch(new URL('/v1/repositories/inspect', host.server.url), { method: 'POST', headers, body: JSON.stringify({ workspace_root: workspace, repositories: [] }) })
  expect((await inspect()).status).toBe(409)

  // Unauthenticated grant is rejected
  const unauthRes = await fetch(new URL('/v1/roots/grant', host.server.url), { method: 'POST', body: JSON.stringify({ workspace_root: workspace }) })
  expect(unauthRes.status).toBe(401)

  // Authenticated grant succeeds
  const grantRes = await fetch(new URL('/v1/roots/grant', host.server.url), { method: 'POST', headers, body: JSON.stringify({ workspace_root: workspace }) })
  expect(grantRes.status).toBe(200)
  const grantData = await grantRes.json()
  expect(grantData.ok).toBe(true)

  // Now inspect succeeds without restarting host
  expect((await inspect()).status).toBe(200)

  // Config file is also persisted
  const updatedCfg = JSON.parse(fs.readFileSync(configPath, 'utf8'))
  expect(updatedCfg.allowed_roots).toContain(path.resolve(workspace))
})

