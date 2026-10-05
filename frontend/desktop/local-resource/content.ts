import * as fs from 'node:fs'
import * as path from 'node:path'
import { randomUUID } from 'node:crypto'
import { atomic, child, copyTree, fail, readJson, walk, writeFiles, writeJson } from './filesystem'

const manifestName = '.sdd-runtime-skills.json'
const manifest = (root: string): any[] => {
  if (!fs.existsSync(path.join(root, manifestName))) return []
  const data = readJson(path.join(root, manifestName))
  return Array.isArray(data) ? data : data.items || []
}
function tree(root: string, prefix = ''): any[] {
  if (!fs.existsSync(root)) return []
  return fs.readdirSync(root, { withFileTypes: true }).filter(entry => !entry.isSymbolicLink()).sort((a, b) => a.name.localeCompare(b.name)).map(entry => {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name
    return { name: entry.name, path: relative, node_type: entry.isDirectory() ? 'directory' : 'file', children: entry.isDirectory() ? tree(path.join(root, entry.name), relative) : [] }
  })
}
function textFile(file: string) {
  const data = fs.readFileSync(file)
  let content: string | null = null
  try { if (!data.includes(0)) content = new TextDecoder('utf-8', { fatal: true }).decode(data) } catch { /* binary */ }
  return { content, is_binary: content === null, size: data.length }
}
export function skills(root: string, payload: any): any {
  const directory = child(root, '.agents/skills')
  if (payload.action === 'replace') {
    const temporary = child(root, '.agents/skills.tmp-' + randomUUID()), previous = child(root, '.agents/skills.old-' + randomUUID())
    fs.mkdirSync(temporary, { recursive: true })
    let moved = false
    try {
      writeFiles(temporary, payload.files.map((entry: any) => ({ ...entry, path: entry.path.replace(/^\.agents\/skills\//, '') })))
      const items = manifest(temporary)
      if (payload.preserve && fs.existsSync(directory)) {
        const old = manifest(directory)
        for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
          if (!entry.isDirectory() || entry.isSymbolicLink() || entry.name.startsWith('.') || items.some(item => item.materialized_dir === entry.name)) continue
          const item = old.find(item => item.materialized_dir === entry.name) || { skill_id: 'runtime:' + entry.name, name: entry.name, description: null, dimension: 'TASK_RUNTIME', materialized_dir: entry.name }
          if (items.some(current => current.skill_id === item.skill_id)) continue
          copyTree(child(directory, entry.name), child(temporary, entry.name))
          items.push({ ...item, config_deleted: true })
        }
        writeJson(path.join(temporary, manifestName), { version: 1, items })
      }
      if (fs.existsSync(directory)) { fs.renameSync(directory, previous); moved = true }
      fs.renameSync(temporary, directory)
      if (moved) fs.rmSync(previous, { recursive: true })
    } catch (error) { if (moved && !fs.existsSync(directory)) fs.renameSync(previous, directory); throw error }
    finally { fs.rmSync(temporary, { recursive: true, force: true }) }
    return { ok: true }
  }
  if (payload.action === 'manifest') return { items: manifest(directory), folders: fs.existsSync(directory) ? fs.readdirSync(directory, { withFileTypes: true }).filter(entry => entry.isDirectory() && !entry.isSymbolicLink() && !entry.name.startsWith('.')).map(entry => entry.name) : [] }
  if (path.basename(payload.folder) !== payload.folder) fail('INVALID_SKILL_FOLDER')
  const folder = child(directory, payload.folder)
  if (payload.action === 'tree') return { tree: tree(folder) }
  const file = child(folder, payload.path)
  if (payload.action === 'write') {
    const data = Buffer.from(payload.content)
    if (data.length > 10 * 1024 * 1024) fail('Skill text exceeds size limit')
    if (fs.existsSync(file) && textFile(file).is_binary) fail('Binary file is read-only')
    atomic(file, data)
  } else if (payload.action !== 'read') fail('Unsupported skill operation')
  return { path: payload.path, ...textFile(file) }
}

export function documents(root: string, taskId: string, payload: any, docRoots = ['docs/superpowers', 'superpowers/docs/superpowers', '.']): any {
  const roots = docRoots.map(relative => relative === '.' ? root : child(root, relative))
  const sections = ['plans', 'specs']
  const entry = (section: string, sectionRoot: string, file: string) => ({ section, name: path.basename(file), section_path: path.relative(sectionRoot, file).replaceAll('\\', '/'), relative_path: path.relative(root, file).replaceAll('\\', '/'), size: fs.statSync(file).size, updated_at: fs.statSync(file).mtime.toISOString() })
  if (payload.action === 'list') {
    const listing: Record<string, any> = { task_id: taskId, root_relative_path: docRoots.join(', ') }
    for (const section of sections) {
      const seen = new Set<string>()
      listing[section] = roots.flatMap(base => {
        const directory = child(base, section)
        return walk(directory).filter(relative => /\.(md|markdown)$/i.test(relative)).map(relative => entry(section, directory, child(directory, relative)))
      }).filter(item => { if (seen.has(item.relative_path.toLowerCase())) return false; seen.add(item.relative_path.toLowerCase()); return true }).sort((a, b) => a.section_path.localeCompare(b.section_path))
    }
    return listing
  }
  if (!sections.includes(payload.section) || !/\.(md|markdown)$/i.test(payload.path)) fail('INVALID_DOCUMENT_PATH')
  const candidates = roots.map(base => child(child(base, payload.section), payload.path))
  const file = candidates.find(candidate => fs.existsSync(candidate)) || candidates.find(candidate => fs.existsSync(path.dirname(candidate))) || candidates[0]
  if (payload.action === 'save') atomic(file, String(payload.content || ''))
  else if (payload.action !== 'read') fail('Unsupported document operation')
  return { task_id: taskId, ...entry(payload.section, child(roots[candidates.indexOf(file)], payload.section), file), content: fs.readFileSync(file, 'utf8') }
}
