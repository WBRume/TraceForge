import * as fs from 'node:fs'
import * as path from 'node:path'
import { randomUUID } from 'node:crypto'
import { atomic, child, copyTree, fail, readJson, writeFiles, writeJson } from './filesystem'

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
