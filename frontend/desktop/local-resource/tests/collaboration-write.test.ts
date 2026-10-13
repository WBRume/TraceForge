import { afterEach, beforeEach, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { applyFile } from '../collaboration-write'
import { SyncObjects } from '../collaboration-store'
import { rejectManagedWrite } from '../collaboration-guard'
import { hash } from '../filesystem'

let root: string, objects: SyncObjects
beforeEach(() => {
  root = fs.mkdtempSync(path.join(tmpdir(), 'tf-collaboration-boundary-'))
  objects = new SyncObjects(path.join(root, 'state'))
  fs.writeFileSync(path.join(root, 'file.txt'), 'before')
})
afterEach(() => { fs.rmSync(root, { force: true, recursive: true }) })
const options = () => ({ state: path.join(root, 'state'), operation_id: 'write1', task_repository_id: 'repo', root,
  relative: 'file.txt', expected: { path: 'file.txt', sha256: objects.put(Buffer.from('before')), size: 6, mode: '100644' as const },
  target: { path: 'file.txt', sha256: objects.put(Buffer.from('after')), size: 5, mode: '100644' as const }, objects })

test('resumes after displacement and never replays a completed write over later local content', () => {
  const input = { ...options(), context: { task_id: 'task', snapshot_id: 'result', workspace_revision: 3, session_generation: 1, session_revision: 2, session_turn_id: 'turn', turn_index: 2, source: 'AGENT_OUTPUT', kind: 'restore' as const, repo_slug: 'repo', branch_name: 'main' } }
  expect(() => applyFile({ ...input, afterMove: () => { throw new Error('simulated process crash') } })).toThrow('simulated process crash')
  expect(fs.existsSync(path.join(root, 'file.txt'))).toBe(false)
  const receipt = applyFile(input)
  expect(receipt.state).toBe('SUCCEEDED')
  expect(receipt.context).toEqual(input.context)
  expect(Number.isFinite(Date.parse(receipt.created_at!))).toBe(true)
  expect(fs.readFileSync(path.join(root, 'file.txt'), 'utf8')).toBe('after')
  fs.writeFileSync(path.join(root, 'file.txt'), 'edit after receipt')
  expect(applyFile(input).state).toBe('SUCCEEDED')
  expect(applyFile(input).created_at).toBe(receipt.created_at)
  expect(fs.readFileSync(path.join(root, 'file.txt'), 'utf8')).toBe('edit after receipt')
})
test('revalidates the actually displaced file before resuming a crashed write', () => {
  const input = options()
  expect(() => applyFile({ ...input, afterMove: () => { throw new Error('simulated process crash') } })).toThrow()
  const displaced = fs.readdirSync(root).find(name => name.endsWith('-old'))!
  fs.writeFileSync(path.join(root, displaced), 'late old handle write')
  expect(() => applyFile(input)).toThrow('REPLACEMENT_BOUNDARY')
  expect(fs.readFileSync(path.join(root, 'file.txt'), 'utf8')).toBe('late old handle write')
  expect(objects.get(hash('late old handle write')).toString()).toBe('late old handle write')
})
test('backup corruption fails before replacing the working file', () => {
  const input = options()
  fs.mkdirSync(path.dirname(objects.file(input.expected.sha256)), { recursive: true })
  if (fs.existsSync(objects.file(input.expected.sha256))) fs.chmodSync(objects.file(input.expected.sha256), 0o600)
  fs.writeFileSync(objects.file(input.expected.sha256), 'corrupt')
  expect(() => applyFile(input)).toThrow('CORRUPT_LOCAL_CONTENT_OBJECT')
  expect(fs.readFileSync(path.join(root, 'file.txt'), 'utf8')).toBe('before')
})
test('legacy writes cannot target managed children or parent roots', () => {
  const registry = path.join(root, 'registry.json')
  fs.writeFileSync(registry, JSON.stringify([path.join(root, 'managed')]))
  for (const target of [root, path.join(root, 'managed'), path.join(root, 'managed', 'repo')]) {
    expect(() => rejectManagedWrite(registry, target)).toThrow('COLLABORATION_MANAGED_DIRECTORY')
  }
  expect(() => rejectManagedWrite(registry, path.join(root, 'other'))).not.toThrow()
})
