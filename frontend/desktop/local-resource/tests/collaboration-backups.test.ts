import { afterEach, beforeEach, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { CollaborationRuntime } from '../collaboration'

let root: string, runtime: CollaborationRuntime
beforeEach(() => {
  root = fs.mkdtempSync(path.join(tmpdir(), 'tf-backups-'))
  runtime = new CollaborationRuntime(path.join(root, 'state'), () => [root])
})
afterEach(() => {
  runtime.close()
  const target = path.resolve(root)
  if (path.dirname(target) !== path.resolve(tmpdir()) || !path.basename(target).startsWith('tf-backups-')) throw new Error('Invalid test root')
  fs.rmSync(target, { recursive:true, force:true })
})

test('returns no local backups for a cloud-only task without preparing or scanning a repository', async () => {
  runtime.index.scan = () => { throw new Error('Backup listing must not scan code') }
  const result = await runtime.executeAsync('backups', { task_id:'cloud-only-task' })
  expect(result).toEqual({ backup_directory:'', backup_directories:[], backups:[] })
  expect(fs.existsSync(path.join(runtime.state, 'bindings'))).toBe(false)
  expect(fs.existsSync(path.join(runtime.state, 'operations'))).toBe(false)
  expect(() => runtime.execute('status', { task_id:'cloud-only-task' })).toThrow('ENOENT')
})

test('does not hide corrupt binding data or invalid task IDs as an empty backup list', () => {
  fs.mkdirSync(path.join(runtime.state, 'bindings'), { recursive:true })
  fs.writeFileSync(path.join(runtime.state, 'bindings', 'broken.json'), '{broken')
  expect(() => runtime.execute('backups', { task_id:'broken' })).toThrow(SyntaxError)
  expect(() => runtime.execute('backups', { task_id:'../invalid' })).toThrow('INVALID_COLLABORATION_ID')
})
