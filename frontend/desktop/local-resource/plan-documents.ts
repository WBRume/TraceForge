import * as fs from 'node:fs'
import * as path from 'node:path'
import { createHash } from 'node:crypto'
import { atomic, child, fail, hash, inside, readJson } from './filesystem'
import { entries } from './git-snapshots'

const sectionFor = (relative: string) => relative.toLowerCase().split('/').slice(0, -1).includes('specs') ? 'specs' : 'plans'
const relativePath = (root: string, file: string) => path.relative(root, file).replaceAll('\\', '/')
function loadBaseline(root: string, checkpoint: string | undefined, owner: string): any {
  if (!checkpoint) return null
  const directory = inside(checkpoint, [owner])
  if (!fs.existsSync(path.join(directory, 'worktree.json'))) return null
  const saved = readJson(path.join(directory, 'worktree.json'))
  if (saved.version === 4) {
    if (path.resolve(saved.task_root) !== path.resolve(root) || path.resolve(saved.object_store) !== path.resolve(owner)) fail('SNAPSHOT_IDENTITY_CHANGED')
    saved.entries = entries(saved)
  } else if (saved.version === 3) saved.entries = saved.manifest
  else return null
  return saved
}

export function documents(root: string, taskId: string, payload: any, owner: string): any {
  const docRoots: string[] = payload.roots || []
  if (!Array.isArray(docRoots) || docRoots.length > 32) fail('INVALID_DOCUMENT_ROOTS')
  const roots = docRoots.map(relative => {
    if (typeof relative !== 'string' || relative.replaceAll('\\', '/').split('/').some(part => part.toLowerCase() === '.git')) fail('INVALID_DOCUMENT_ROOTS')
    return relative === '.' ? root : child(root, relative)
  })
  const entry = (file: string) => {
    const relative = relativePath(root, file), stat = fs.statSync(file)
    return { section: sectionFor(relative), name: path.basename(file), section_path: relative, relative_path: relative, size: stat.size, updated_at: stat.mtime.toISOString() }
  }
  if (payload.action === 'list') {
    const result: any = { task_id: taskId, root_relative_path: docRoots.join(', '), configured: roots.length > 0, baseline_available: false, plans: [], specs: [] }
    if (!roots.length) return result
    const baseline = loadBaseline(root, payload.initial_checkpoint, owner)
    if (!baseline) return result
    result.baseline_available = true
    const seen = new Set<string>()
    const excluded = new Set<string>(['.git', ...(baseline.policy?.excluded_dirs || [])])
    function visit(directory: string) {
      if (!fs.existsSync(directory)) return
      for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
        if (item.isSymbolicLink() || excluded.has(item.name)) continue
        const file = child(directory, item.name)
        if (item.isDirectory()) { visit(file); continue }
        if (!item.isFile() || !/\.(md|markdown)$/i.test(item.name)) continue
        const relative = relativePath(root, file)
        const seenKey = process.platform === 'win32' ? relative.toLowerCase() : relative
        if (seen.has(seenKey)) continue
        seen.add(seenKey)
        const previous = baseline.entries[relative]
        if (!previous && (relative.split('/').some(part => excluded.has(part)) || (baseline.policy?.excluded_suffixes || []).some((suffix: string) => relative.endsWith(suffix)))) continue
        if (previous) {
          const data = fs.readFileSync(file)
          const digest = baseline.version === 4 ? createHash('sha1').update(`blob ${data.length}\0`).update(data).digest('hex') : hash(data)
          if (digest === (previous.oid || previous.hash)) continue
        }
        result[sectionFor(relative)].push(entry(file))
      }
    }
    roots.forEach(visit)
    for (const section of ['plans', 'specs']) result[section].sort((a: any, b: any) => a.relative_path.localeCompare(b.relative_path))
    return result
  }
  if (!roots.length || typeof payload.path !== 'string' || !/\.(md|markdown)$/i.test(payload.path)) fail('INVALID_DOCUMENT_PATH')
  if (payload.path.replaceAll('\\', '/').split('/').some((part: string) => part.toLowerCase() === '.git')) fail('INVALID_DOCUMENT_PATH')
  const file = inside(child(root, payload.path), roots)
  if (payload.section !== sectionFor(relativePath(root, file))) fail('INVALID_DOCUMENT_SECTION')
  if (payload.action === 'save') atomic(file, String(payload.content || ''))
  else if (payload.action !== 'read') fail('Unsupported document operation')
  return { task_id: taskId, ...entry(file), content: fs.readFileSync(file, 'utf8') }
}
