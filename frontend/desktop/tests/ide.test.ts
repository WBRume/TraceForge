import { afterEach, expect, test } from 'bun:test'
import { mkdtemp, mkdir, writeFile, rm, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { ideTarget, vscodeUrl, launchIde } from '../ide'

const roots: string[] = []
afterEach(async () => { for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true }) })
test('resolves same-named files by repository and preserves unicode, spaces and 1-based position', async () => {
  const root = await mkdtemp(join(tmpdir(), 'tf-ide-')); roots.push(root)
  for (const repo of ['first', 'second']) { await mkdir(join(root, repo)); await writeFile(join(root, repo, '中文 # a.txt'), repo) }
  const request = { workspaceId: 'ws', remoteUrl: 'remote', path: '中文 # a.txt', line: 42, column: 3 }
  const first = await ideTarget(join(root, 'first'), request), second = await ideTarget(join(root, 'second'), request)
  expect(first.file).not.toBe(second.file)
  const url = vscodeUrl(second)
  expect(url).toStartWith('vscode://file/')
  expect(url).toContain('%23%20a.txt:42:3')
  const opened: string[] = []
  await launchIde({ editor: 'vscode' }, second, async value => { opened.push(value) })
  expect(opened).toEqual([url])
  await expect(ideTarget(root, { ...request, path: '../outside' })).rejects.toThrow('IDE_PATH_INVALID')
  await expect(ideTarget(root, { ...request, path: 'C:/outside' })).rejects.toThrow('IDE_PATH_INVALID')
  await expect(ideTarget(root, { ...request, path: 'missing.txt' })).rejects.toThrow('IDE_FILE_MISSING')
  await expect(ideTarget(join(root, 'second'), { ...request, line: 0 })).rejects.toThrow('IDE_POSITION_INVALID')
  await expect(launchIde({ editor: 'idea', executable: join(root, 'absent.exe') }, second, async () => {})).rejects.toThrow('IDE_LAUNCH_FAILED')
})
test('rejects directory junctions that escape the mapped repository', async () => {
  const root = await mkdtemp(join(tmpdir(), 'tf-ide-')); roots.push(root)
  await mkdir(join(root, 'repo')); await mkdir(join(root, 'outside')); await writeFile(join(root, 'outside', 'file.txt'), 'private')
  await symlink(join(root, 'outside'), join(root, 'repo', 'link'), 'junction')
  await expect(ideTarget(join(root, 'repo'), { workspaceId: 'ws', remoteUrl: 'remote', path: 'link/file.txt' })).rejects.toThrow('IDE_PATH_OUTSIDE_REPOSITORY')
})
