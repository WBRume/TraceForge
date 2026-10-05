import { platform } from './platform'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { homedir } from 'node:os'
import { randomUUID } from 'node:crypto'
import { atomic, child, copyTree, fail, inside, readJson, writeJson } from './filesystem'

export const sessionRoot = (configured?: string) => path.resolve(configured || process.env.DSH_SESSION_ROOT || path.join(process.env.DSH_HOME || path.join(homedir(), '.dsh'), 'sessions'))
export function encodeSegment(raw: string) {
  if (!raw) fail('EMPTY_SESSION_ID')
  if (raw === '.' || raw === '..') return raw.replaceAll('.', '~002E')
  return raw.split('').map(unit => /^[A-Za-z0-9._-]$/.test(unit) ? unit : '~' + unit.charCodeAt(0).toString(16).toUpperCase().padStart(4, '0')).join('')
}
export function projectKey(cwd: string) {
  const slug = cwd.replace(/[/\\:]+/g, '-').split('').map(unit => /^[A-Za-z0-9._-]$/.test(unit) ? unit : '~' + unit.charCodeAt(0).toString(16).toUpperCase().padStart(4, '0')).join('').replace(/^-+/, '') || 'root'
  return '--' + slug.slice(0, 251) + '--'
}
export function locateSession(root: string, id: string): string | null {
  if (!fs.existsSync(root)) return null
  const found: string[] = []
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.isSymbolicLink()) continue
    for (const suffix of ['.jsonl', '.jsonl.zstd']) {
      const file = child(root, `${entry.name}/${encodeSegment(id)}/session${suffix}`)
      if (fs.existsSync(file)) found.push(file)
    }
  }
  if (found.length > 1) fail('DSH_SESSION_AMBIGUOUS')
  return found[0] || null
}
export function forkSession(root: string, id: string, cwd: string) {
  const source = locateSession(root, id)
  if (!source) fail('DSH_SESSION_NOT_FOUND')
  const compressed = source!.endsWith('.zstd')
  const data = fs.readFileSync(source!)
  const text = (compressed ? platform().decompress(data) : data).toString('utf8')
  const lines = text.trimEnd().split('\n')
  const header = JSON.parse(lines[0])
  if (header.type !== 'session' || header.id !== id) fail('DSH_SESSION_HEADER_INVALID')
  const next = 'session-tf-revert-' + randomUUID().replaceAll('-', '')
  header.id = next; header.cwd = path.resolve(cwd)
  let expected = 0
  const events: string[] = []
  for (const line of lines.slice(1)) {
    const row = JSON.parse(line)
    const start = Number.isInteger(row.seq) ? row.seq : row.seq0
    const span = Number.isInteger(row.seq) ? 1 : Array.isArray(row.data?.dt) ? row.data.dt.length + 1 : 0
    if (!Number.isInteger(start) || start < 0 || !span) fail('DSH_SESSION_SEQUENCE_INVALID')
    if (start !== expected) break
    expected += span; events.push(line)
  }
  const directory = child(root, projectKey(header.cwd) + '/' + encodeSegment(next))
  if (fs.existsSync(directory)) fail('DSH_FORK_EXISTS')
  const first = JSON.stringify(header) + '\n', rest = events.length ? events.join('\n') + '\n' : ''
  atomic(path.join(directory, compressed ? 'session.jsonl.zstd' : 'session.jsonl'), compressed
    ? Buffer.concat([platform().compress(first), ...(rest ? [platform().compress(rest)] : [])]) : first + rest)
  for (const entry of fs.readdirSync(path.dirname(source!), { withFileTypes: true })) {
    if (entry.isSymbolicLink() || ['session.jsonl', 'session.jsonl.zstd'].includes(entry.name)) continue
    const from = child(path.dirname(source!), entry.name), to = child(directory, entry.name)
    if (entry.isDirectory()) copyTree(from, to); else atomic(to, fs.readFileSync(from))
  }
  return next
}
export function cleanupSession(root: string, id: string) {
  if (!/^session-tf-revert-[a-f0-9]{32}$/.test(id)) fail('DSH_FORK_OWNERSHIP_REQUIRED')
  const file = locateSession(root, id)
  if (file) fs.rmSync(inside(path.dirname(file), [root]), { recursive: true })
}
export function captureProvider(root: string, checkpoint: string, provider: string, id: string | null, current = false) {
  const file = provider === 'dsh' && id ? locateSession(root, id) : null
  const source = file ? path.dirname(file) : null
  const copy = source ? child(checkpoint, current ? 'current-provider/session' : 'provider/session') : null
  if (source && copy) copyTree(source, copy)
  const metadata = { provider, kind: provider === 'dsh' ? 'dsh_session_dir' : 'none', session_id: id, source, source_exists: !!source, copy }
  writeJson(path.join(checkpoint, current ? 'current-provider.json' : 'provider.json'), metadata)
  return metadata
}
export function restoreProvider(root: string, checkpoint: string, current = false) {
  const metadata = readJson(path.join(checkpoint, current ? 'current-provider.json' : 'provider.json'))
  if (metadata.kind !== 'dsh_session_dir' || !metadata.source) return
  const target = inside(metadata.source, [root])
  if (target === path.resolve(root)) fail('INVALID_SESSION_ROOT')
  if (metadata.copy) {
    const copy = inside(metadata.copy, [checkpoint])
    if (!fs.existsSync(copy)) fail('PROVIDER_BACKUP_MISSING')
    fs.rmSync(target, { recursive: true, force: true }); copyTree(copy, target)
  } else fs.rmSync(target, { recursive: true, force: true })
}
