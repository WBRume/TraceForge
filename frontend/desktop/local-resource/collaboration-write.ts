import * as fs from 'node:fs'
import * as path from 'node:path'
import { randomUUID } from 'node:crypto'
import { child, fail, hash, readJson } from './filesystem'
import { durableFile, durableJson, identifier, localFile, repositoryFileModes, sameFile, type SyncFile, SyncObjects, validateFileMode } from './collaboration-store'

interface WriteRecord {
  task_repository_id: string; relative: string; root: string; expected: SyncFile | null;
  target: SyncFile | null; displaced: string; staged: string; state: string;
  error?: string; actual_backup_sha256?: string;
}

/** A persistent file operation. Never overwrites an unexpected replacement at the destination. */
export function applyFile(options: {
  state: string; operation_id: string; task_repository_id: string; root: string;
  expected: SyncFile | null; target: SyncFile | null; relative: string; objects: SyncObjects;
  scratch_root?: string;
  beforeMove?: () => void; afterMove?: () => void;
}) {
  const { state, operation_id, task_repository_id, root, expected, target, relative, objects } = options
  const validatePlaceholder = () => {
    if (expected?.mode !== '120000' && target?.mode !== '120000') return
    const indexed = repositoryFileModes(root)
    if (expected) validateFileMode(relative, expected.mode, indexed)
    if (target) validateFileMode(relative, target.mode, indexed)
  }
  validatePlaceholder()
  const destination = child(root, relative)
  const journal = path.join(state, 'operations', identifier(operation_id), hash(task_repository_id + ':' + relative) + '.json')
  let record: WriteRecord
  if (fs.existsSync(journal)) {
    record = readJson(journal)
    if (record.root !== root || !sameFile(record.expected, expected) || !sameFile(record.target, target)) fail('COLLABORATION_OPERATION_ID_CONFLICT')
    // A completed receipt remains authoritative; later local changes must never be replayed over.
    if (record.state === 'SUCCEEDED') return record
    if (record.state === 'CONCURRENT_CHANGE') fail('LOCAL_FILE_CHANGED_RECONFIRM')
  } else {
    const token = '.traceforge-sync-' + randomUUID()
    const scratch = options.scratch_root ?? root
    fs.mkdirSync(scratch, { recursive: true })
    record = { task_repository_id, relative, root, expected, target,
      displaced: path.join(scratch, token + '-old'),
      staged: path.join(scratch, token + '-new'), state: 'PLANNED' }
    durableJson(journal, record)
  }
  const save = (step: string) => { record.state = step; durableJson(journal, record) }
  const readCurrent = () => {
    // Directory replacements are permitted only after related file deletions left an empty directory.
    if (!expected && target && fs.existsSync(destination) && fs.lstatSync(destination).isDirectory()) {
      const pruneEmpty = (directory: string) => {
        for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
          if (!entry.isDirectory() || entry.isSymbolicLink()) fail('COLLABORATION_PATH_STRUCTURE_CONFLICT')
          pruneEmpty(path.join(directory, entry.name))
        }
        fs.rmdirSync(directory)
      }
      pruneEmpty(destination)
    }
    const current = localFile(root, relative, objects)
    if (current && process.platform === 'win32') current.mode = expected?.mode ?? target?.mode ?? current.mode
    return current
  }
  try {
    if (['STAGED', 'MOVED', 'PLACED'].includes(record.state) && fs.existsSync(record.displaced)) {
      const actual = fs.lstatSync(record.displaced)
      if (!actual.isFile() || actual.isSymbolicLink()) fail('COLLABORATION_DISPLACED_TYPE_CHANGED')
      const bytes = fs.readFileSync(record.displaced)
      record.actual_backup_sha256 = objects.put(bytes)
      durableJson(journal, record)
      if (record.actual_backup_sha256 !== expected?.sha256) {
        try { fs.linkSync(record.displaced, destination) } catch { /* Preserve the newly appeared destination. */ }
        fail('LOCAL_FILE_CHANGED_AT_REPLACEMENT_BOUNDARY')
      }
      if (record.state === 'STAGED') save('MOVED')
    }
    if (['PLACED', 'MOVED'].includes(record.state) && sameFile(readCurrent(), target)) {
      save('SUCCEEDED'); return record
    }
    if (record.state === 'PLANNED') {
      if (!sameFile(readCurrent(), expected)) fail('LOCAL_FILE_CHANGED_RECONFIRM')
      // CAS backup is flushed before moving anything out of the working directory.
      if (expected) objects.get(expected.sha256)
      if (target) {
        const data = objects.get(target.sha256)
        if (data.length !== target.size) fail('CONTENT_OBJECT_SIZE_MISMATCH')
        fs.mkdirSync(path.dirname(destination), { recursive: true })
        if (fs.statSync(path.dirname(destination)).dev !== fs.statSync(path.dirname(record.staged)).dev) fail('COLLABORATION_NESTED_VOLUME_UNSUPPORTED')
        durableFile(record.staged, data)
        fs.chmodSync(record.staged, target.mode === '100755' ? 0o755 : 0o644)
      }
      save('STAGED')
    }
    if (record.state === 'STAGED') {
      if (!sameFile(readCurrent(), expected)) fail('LOCAL_FILE_CHANGED_RECONFIRM')
      options.beforeMove?.()
      validatePlaceholder()
      if (expected) {
        // The same-volume displacement keeps the actual boundary version, including concurrent saves.
        fs.renameSync(destination, record.displaced)
        save('MOVED')
        const actual = fs.lstatSync(record.displaced)
        if (!actual.isFile() || actual.isSymbolicLink()) fail('COLLABORATION_DISPLACED_TYPE_CHANGED')
        const displaced = fs.readFileSync(record.displaced)
        record.actual_backup_sha256 = objects.put(displaced)
        durableJson(journal, record)
        if (record.actual_backup_sha256 !== expected.sha256) {
          // Link is exclusive: compensation cannot overwrite a newly saved destination either.
          try { fs.linkSync(record.displaced, destination) } catch { /* Both copies remain recoverable. */ }
          fail('LOCAL_FILE_CHANGED_AT_REPLACEMENT_BOUNDARY')
        }
      } else save('MOVED')
      options.afterMove?.()
    }
    if (record.state === 'MOVED') {
      // Replacing a file via rename() would clobber a concurrent save; exclusive hard link never does.
      if (fs.existsSync(destination)) fail('LOCAL_FILE_CHANGED_AT_REPLACEMENT_BOUNDARY')
      if (child(root, relative) !== destination) fail('COLLABORATION_DESTINATION_CHANGED')
      validatePlaceholder()
      if (target) fs.linkSync(record.staged, destination)
      save('PLACED')
    }
    if (!sameFile(readCurrent(), target)) fail('LOCAL_FILE_CHANGED_AFTER_REPLACEMENT')
    save('SUCCEEDED')
    // Displaced material remains in place while a writer might still have its old handle open.
    // The journal and verified CAS backup retain both original and actual boundary content.
    if (target) fs.rmSync(record.staged, { force: true })
    return record
  } catch (error) {
    record.error = error instanceof Error ? error.message : String(error)
    save(record.error.startsWith('LOCAL_FILE_CHANGED') || (error as any).code === 'EEXIST' ? 'CONCURRENT_CHANGE' : record.state)
    throw error
  }
}
