import { afterEach, beforeEach, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { CollaborationRuntime } from '../collaboration'
import { durableJson } from '../collaboration-store'
import { hash } from '../filesystem'

let root: string, runtime: CollaborationRuntime
beforeEach(() => {
  root = fs.mkdtempSync(path.join(tmpdir(), 'tf-queries-'))
  runtime = new CollaborationRuntime(path.join(root, 'state'), () => [root])
})
afterEach(() => {
  runtime.close()
  const target = path.resolve(root)
  if (path.dirname(target) !== path.resolve(tmpdir()) || !path.basename(target).startsWith('tf-queries-')) throw new Error('Invalid test root')
  fs.rmSync(target, { recursive: true, force: true })
})

test('optional binding queries return null without scans or writes, while required operations fail', async () => {
  runtime.index.scan = () => { throw new Error('A binding lookup must not scan code') }
  expect(await runtime.executeAsync('binding', { task_id: 'cloud-only', optional: true, delta_transport: true })).toBeNull()
  expect(fs.existsSync(runtime.state)).toBe(false)
  for (const kind of ['binding', 'status', 'capture', 'reconcile']) {
    expect(() => runtime.execute(kind, { task_id: 'cloud-only' })).toThrow('COLLABORATION_BINDING_MISSING')
  }
})

test('optional binding queries preserve invalid IDs, corrupt JSON and directory validation errors', () => {
  expect(() => runtime.execute('binding', { task_id: '../invalid', optional: true })).toThrow('INVALID_COLLABORATION_ID')
  const file = path.join(runtime.state, 'bindings', 'broken.json')
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, '{broken')
  expect(() => runtime.execute('binding', { task_id: 'broken', optional: true })).toThrow(SyntaxError)
  durableJson(file, { task_root: path.dirname(root), repositories: [] })
  expect(() => runtime.execute('binding', { task_id: 'broken', optional: true })).toThrow('PATH_OUTSIDE_RESOURCE_ROOT')
})

test('optional queries retain released bindings so reconnection can reuse their baseline', () => {
  const binding = { task_id: 'retained', task_root: fs.realpathSync(root), repositories: [], released: true, suspended: true, baseline: { snapshot_id: 'before' } }
  durableJson(path.join(runtime.state, 'bindings', 'retained.json'), binding)
  expect(runtime.execute('binding', { task_id: 'retained', optional: true })).toEqual(binding)
  expect(() => runtime.execute('status', { task_id: 'retained' })).toThrow('binding released')
})

test('optional content reads distinguish a cache miss, cached bytes and a cached empty file', () => {
  const sha256 = hash('cloud-only')
  expect(runtime.execute('read_object', { sha256, optional: true, delta_transport: true })).toBeNull()
  expect(fs.existsSync(runtime.state)).toBe(false)
  expect(() => runtime.execute('read_object', { sha256 })).toThrow('LOCAL_CONTENT_OBJECT_MISSING')
  for (const content of ['local text', '']) {
    const digest = runtime.objects.put(Buffer.from(content))
    expect(runtime.execute('read_object', { sha256: digest, optional: true })).toEqual({ sha256: digest, content: Buffer.from(content).toString('base64') })
  }
}, 30_000)

test('optional content reads still reject invalid digests and corrupted cache entries', () => {
  expect(() => runtime.execute('read_object', { sha256: '../invalid', optional: true })).toThrow('INVALID_CONTENT_DIGEST')
  const sha256 = hash('expected'), file = path.join(runtime.state, 'objects', sha256.slice(0, 2), sha256)
  fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, 'corrupt')
  expect(() => runtime.execute('read_object', { sha256, optional: true })).toThrow('CORRUPT_LOCAL_CONTENT_OBJECT')
})
