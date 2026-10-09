import { afterEach, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { captureGitSnapshot } from '../git-snapshots'
import { documents } from '../plan-documents'

const temporary: string[] = []
afterEach(() => { temporary.splice(0).forEach(root => fs.rmSync(root, { recursive: true, force: true })) })
const write = (root: string, relative: string, content: string) => {
  const file = path.join(root, relative)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, content)
  return file
}

test('uses the initial snapshot across configured roots and exact same-name paths', () => {
  const store = fs.mkdtempSync(path.join(os.tmpdir(), 'tf-plan-docs-')); temporary.push(store)
  const root = path.join(store, 'task'), owner = path.join(store, 'snapshots'), checkpoint = path.join(owner, 'turn-initial')
  write(root, 'archive/old.md', 'original')
  write(root, 'other/old.md', 'existing')
  fs.mkdirSync(checkpoint, { recursive: true })
  captureGitSnapshot({ task_id: 'task', task_root: root, repositories: [], repositories_input: [] }, checkpoint, owner)
  const config = { roots: ['archive', 'archive/nested', 'other'], initial_checkpoint: checkpoint }
  const list = () => documents(root, 'task', { ...config, action: 'list' }, owner)
  expect(list().plans).toEqual([])
  const old = path.join(root, 'archive/old.md')
  fs.utimesSync(old, new Date(), new Date())
  expect(list().plans).toEqual([])
  write(root, 'archive/old.md', 'modified')
  write(root, 'archive/nested/new.md', 'archive')
  write(root, 'other/nested/new.md', 'other')
  expect(list().plans.map((entry: any) => entry.relative_path)).toEqual(['archive/nested/new.md', 'archive/old.md', 'other/nested/new.md'])
  documents(root, 'task', { ...config, action: 'save', section: 'plans', path: 'other/nested/new.md', content: 'edited' }, owner)
  expect(fs.readFileSync(path.join(root, 'archive/nested/new.md'), 'utf8')).toBe('archive')
  expect(documents(root, 'task', { ...config, action: 'read', section: 'plans', path: 'other/nested/new.md' }, owner).content).toBe('edited')
  write(root, 'archive/old.md', 'original')
  expect(list().plans).toHaveLength(2)
  expect(documents(root, 'task', { ...config, roots: ['other'], action: 'list' }, owner).plans).toHaveLength(1)
  expect(documents(root, 'task', { action: 'list' }, owner)).toMatchObject({ configured: false, plans: [], specs: [] })
  expect(documents(root, 'task', { roots: ['archive'], action: 'list' }, owner)).toMatchObject({ baseline_available: false, plans: [], specs: [] })
  for (const relative of ['../outside.md', 'not-configured/file.md', '/absolute.md', 'archive/.git/file.md']) {
    expect(() => documents(root, 'task', { ...config, action: 'save', section: 'plans', path: relative, content: 'bad' }, owner)).toThrow()
  }
}, 30_000)
