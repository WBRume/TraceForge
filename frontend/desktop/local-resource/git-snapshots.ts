/** Raw-byte persistent Git indexes. No command failure falls back to copying. */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { spawnSync } from 'node:child_process'
import { atomic, fail, gitEnvironment, hash, readJson, writeJson, type Receipt } from './filesystem'
import { contentHash } from './content-identity'

const excluded = new Set(['node_modules', 'dist', 'build', 'coverage', '.next', '.nuxt', '.output', '.vite', '.cache', '.turbo', '.parcel-cache', '.svelte-kit', 'target', '.gradle', '.venv', 'venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox', '.nox', 'htmlcov'])
type Policy = { excluded_dirs: string[]; excluded_suffixes: string[] }
const defaultPolicy: Policy = { excluded_dirs: [...excluded], excluded_suffixes: ['.pyc', '.pyo', '.class'] }
const ignored = (p: string, policy: Policy) => p.split('/').some(x => policy.excluded_dirs.includes(x)) || policy.excluded_suffixes.some(suffix => p.endsWith(suffix))
const nul = (xs: Iterable<string>) => Buffer.from([...xs].map(x => x + '\0').join(''))
function git(cwd: string, args: string[], input?: Buffer, inputFile?: number): Buffer {
  const result = spawnSync('git', args, { cwd, input, stdio: [inputFile ?? 'pipe', 'pipe', 'pipe'], windowsHide: true, timeout: 180_000, maxBuffer: 256 * 1024 * 1024, env: gitEnvironment() })
  if (result.error) throw result.error
  if (result.status === 1 && args.includes('update-index') && args.includes('--refresh')
    && !result.stderr.toString().trim() && result.stdout.toString().includes('needs update')) fail('SNAPSHOT_FILE_CHANGED_DURING_CAPTURE')
  if (result.status !== 0) fail(`SNAPSHOT_GIT_ERROR: ${(result.stderr.toString() || result.stdout.toString()).slice(-500)}`)
  return result.stdout
}
export function shadowGit(directory: string, args: string[], input?: Buffer, inputFile?: number): Buffer {
  // Git checks GIT_DIR's UTF-8 length before core.longpaths can help.
  return git(directory, ['--git-dir=.', '-c', 'core.longpaths=true', ...args], input, inputFile)
}
const text = (cwd: string, ...args: string[]) => git(cwd, args).toString().trim()
function safe(root: string, relative: string, checked?: Set<string>) {
  if (!relative || relative.includes(':') || relative.includes('\\') || relative.split('/').some(p => !p || ['.', '..', '.git'].includes(p.toLowerCase()))) fail('INVALID_SNAPSHOT_PATH')
  const target = path.resolve(root, relative)
  let parent = path.dirname(target)
  const pending: string[] = []
  while (parent !== root && !checked?.has(parent)) {
    if (parent === path.dirname(parent)) fail('INVALID_SNAPSHOT_PATH')
    try { if (fs.lstatSync(parent).isSymbolicLink()) fail('SNAPSHOT_LINK_PARENT') }
    catch (error: any) { if (!['ENOENT', 'ENOTDIR'].includes(error.code)) throw error }
    pending.push(parent)
    parent = path.dirname(parent)
  }
  for (const p of pending) checked?.add(p)
  return target
}
function exists(p: string) { try { fs.lstatSync(p); return true } catch (e: any) { if (e.code === 'ENOENT') return false; throw e } }

type Repo = { repo_rel_path: string; repo_path: string; head: string | null; branch: string | null; git_dir: string; index_path: string; index_copy: string | null; index_sha256: string | null }
export type Part = { relative: string; git_dir: string; tree: string; ref: string }
export type GitSnapshot = { version: 4; task_root: string; object_store: string; policy: Policy; directory_links: string[]; directories: string[]; modes: Record<string, number>; tracked: string[]; partitions: Part[]; repositories: Repo[]; quarantined_controls?: Record<string, string> }
type Entry = { oid: string; mode: string; git_dir: string }

function scan(root: string, policy: Policy) {
  const repos: string[] = [], directories: string[] = [], leaves: string[] = []
  function visit(directory: string, prefix = '') {
    for (const e of fs.readdirSync(directory, { withFileTypes: true })) {
      if (e.name.toLowerCase() === '.git') { repos.push(directory); continue }
      const rel = prefix + e.name
      if (ignored(rel, policy)) continue
      if (e.name.includes(':') || e.name.includes('\\')) fail('INVALID_SNAPSHOT_PATH')
      const full = path.join(directory, e.name)
      if (e.isSymbolicLink()) leaves.push(rel)
      else if (e.isDirectory()) { directories.push(rel); visit(full, rel + '/') }
      else if (e.isFile()) leaves.push(rel)
      else fail('SNAPSHOT_UNSUPPORTED_FILE')
    }
  }
  visit(root)
  return { repos, directories, leaves }
}

function repoState(root: string, repo: string, destination: string): Repo {
  const relative = path.relative(root, repo).replaceAll('\\', '/') || '.'
  const [index, gitDir] = text(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'index', '--absolute-git-dir').split(/\r?\n/)
  // HEAD can be unborn. Keep its symbolic name even when no object exists yet.
  const headFile = fs.readFileSync(path.join(gitDir, 'HEAD'), 'utf8').trim()
  const branch = headFile.startsWith('ref: refs/heads/') ? headFile.slice(16) : null
  const refs = text(repo, 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads/')
  const head = branch ? refs.split('\n').find(row => row.startsWith('refs/heads/' + branch + ' '))?.split(' ')[1] || null : headFile
  const copy = fs.existsSync(index) ? path.join(destination, 'git', hash(relative) + '.index') : null
  if (copy) { fs.mkdirSync(path.dirname(copy), { recursive: true }); fs.copyFileSync(index, copy) }
  return { repo_rel_path: relative, repo_path: repo, head, branch, git_dir: gitDir, index_path: index, index_copy: copy, index_sha256: copy ? hash(fs.readFileSync(copy)) : null }
}

export interface CapturedBlob { git_dir: string; oid: string; size: number; sha256: string; content: string }
export interface PreparedGitImport { input: number; marks: string; digests: ReadonlyMap<string, Omit<CapturedBlob, 'git_dir'>> }
export interface GitCaptureOptions { modes?: Map<string, string>; stats?: ReadonlyMap<string, fs.Stats>; prepared?: PreparedGitImport; rejectLinks?: boolean; forceContent?: boolean; changedPaths?: ReadonlySet<string>; onBlobs?: (blobs: CapturedBlob[]) => void }
/** Update only the journal's paths; read-tree anchors a shared rollback index to the known cut. */
export function capturePartPaths(root: string, part: Part, existing: string[], removed: string[], options: GitCaptureOptions, retain = true): Part {
  const cwd = part.relative === '.' ? root : safe(root, part.relative)
  const owner = readJson(path.join(part.git_dir, 'owner.json'))
  if (owner.root !== root || owner.relative !== part.relative) fail('SNAPSHOT_IDENTITY_CHANGED')
  const run = (args: string[], data?: Buffer) => shadowGit(part.git_dir, ['--work-tree=' + cwd, ...args], data)
  run(['read-tree', '-m', part.tree])
  if (removed.length) run(['update-index', '--force-remove', '-z', '--stdin'], nul(removed))
  if (existing.length) importBlobs(cwd, part.git_dir, existing, run, options)
  const tree = run(['write-tree']).toString().trim()
  if (retain) run(['update-ref', part.ref, tree])
  return { ...part, tree }
}
export function capturePart(root: string, store: string, relative: string, source: string | null, protectedPaths: string[], ref: string, options: GitCaptureOptions = {}): Part {
  const cwd = relative === '.' ? root : safe(root, relative)
  const directory = path.join(store, 'shadow', hash(relative).slice(0, 24))
  const run = (args: string[], input?: Buffer) => shadowGit(directory, ['--work-tree=' + cwd, '-c', 'core.autocrlf=false', '-c', 'core.safecrlf=false', '-c', 'core.attributesFile=', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=', ...args], input)
  const cold = !fs.existsSync(directory)
  let sourceObjects: string | undefined
  if (cold) {
    const sourceInfo = source ? git(source, ['rev-parse', '--show-object-format', '--path-format=absolute', '--git-path', 'objects', '--git-path', 'index']).toString().trimEnd().split('\n') : null
    const format = sourceInfo?.[0] ?? 'sha1'
    sourceObjects = sourceInfo?.[1]
    fs.mkdirSync(directory, { recursive: true })
    run(['init', '--object-format=' + format, '.'])
    // This newly created private config has one owner. Write its settings in a
    // single append instead of starting Git once per key for every repository.
    const quotedRoot = '"' + cwd.replace(/[\\"\n\t\b]/g, value => ({ '\\': '\\\\', '"': '\\"', '\n': '\\n', '\t': '\\t', '\b': '\\b' })[value]!) + '"'
    fs.appendFileSync(path.join(directory, 'config'), `\n[core]\n bare = false\n worktree = ${quotedRoot}\n autocrlf = false\n symlinks = ${options.rejectLinks && process.platform === 'win32' ? 'false' : 'true'}\n longpaths = true\n fsmonitor = false\n untrackedCache = true\n[index]\n version = 4\n threads = true\n[gc]\n auto = 0\n`)
    fs.writeFileSync(path.join(directory, 'info/attributes'), '* -text -filter -ident -working-tree-encoding -eol\n')
    if (source) {
      const objects = sourceObjects!
      fs.writeFileSync(path.join(directory, 'objects/info/alternates'), objects.replaceAll('\\', '/') + '\n')
      const index = sourceInfo![2]
      if (fs.existsSync(index)) {
        fs.copyFileSync(index, path.join(directory, 'index'))
        const sharedIndexes = fs.readdirSync(path.dirname(index)).filter(name => name.startsWith('sharedindex.'))
        for (const name of sharedIndexes) fs.copyFileSync(path.join(path.dirname(index), name), path.join(directory, name))
        if (sharedIndexes.length) run(['update-index', '--no-split-index'])
      }
    }
    if (!fs.existsSync(path.join(directory, 'index'))) run(['read-tree', '--empty'])
    writeJson(path.join(directory, 'owner.json'), { root, relative })
  } else {
    const owner = readJson(path.join(directory, 'owner.json'))
    if (owner.root !== root || owner.relative !== relative || !fs.existsSync(path.join(directory, 'index')) || fs.existsSync(path.join(directory, 'objects/info/alternates'))) fail('SNAPSHOT_INDEX_INVALID')
  }
  if (!cold && options.rejectLinks && process.platform === 'win32') run(['config', '--replace-all', 'core.symlinks', 'false'])
  const rows = run(['ls-files', '--stage', '-z']).toString().split('\0').filter(Boolean).map(row => {
    const i = row.indexOf('\t'); return [row.slice(0, i).split(' '), row.slice(i + 1)] as const
  })
  if (rows.some(([header]) => header[2] !== '0')) fail('SNAPSHOT_INDEX_CONFLICT')
  const names = rows.map(([, name]) => name), selected = new Set(protectedPaths)
  if (cold && names.length) {
    run(['update-index', '--no-assume-unchanged', '--no-skip-worktree', '-z', '--stdin'], nul(names))
  }
  const remove = new Set(names.filter(name => !selected.has(name)))
  if (cold && source && protectedPaths.length && !options.rejectLinks) {
    const attrs = git(source, ['check-attr', '-z', '--stdin', 'text', 'filter', 'ident', 'working-tree-encoding', 'eol'], nul(protectedPaths)).toString().split('\0')
    const conversion = new Set<string>()
    for (let i = 0; i + 2 < attrs.length; i += 3) if (!['unspecified', 'unset'].includes(attrs[i + 2])) {
      if (['text', 'eol'].includes(attrs[i + 1])) conversion.add(attrs[i]); else remove.add(attrs[i])
    }
    const config = git(source, ['config', '--list', '--null']).toString().split('\0')
    if (config.some(row => row.toLowerCase().startsWith('core.autocrlf\n') && !['false', '0'].includes(row.split('\n')[1].toLowerCase()))) for (const name of names) conversion.add(name)
    if (conversion.size) {
      const equal = new Set<string>()
      for (const row of git(source, ['ls-files', '--eol', '-z']).toString().split('\0').filter(Boolean)) {
        const i = row.indexOf('\t'), [index, work] = row.slice(0, i).trim().split(/\s+/)
        if (index.slice(2) === work.slice(2) && ['lf', 'none', '-text'].includes(work.slice(2))) equal.add(row.slice(i + 1))
      }
      for (const name of conversion) if (!equal.has(name)) remove.add(name)
    }
  }
  if (remove.size) run(['update-index', '--force-remove', '-z', '--stdin'], nul(remove))
  const dirty = cold && options.rejectLinks ? new Set<string>() : new Set(run(['diff-files', '--name-only', '-z']).toString().split('\0').filter(Boolean))
  const remaining = new Set(names.filter(name => !remove.has(name)))
  const hinted = (name: string) => {
    if (!options.changedPaths?.size) return false
    const parts = name.split('/')
    return parts.some((_, index) => options.changedPaths!.has(parts.slice(0, index + 1).join('/')))
  }
  const changed = protectedPaths.filter(name => (cold && options.rejectLinks) || dirty.has(name) || !remaining.has(name) || hinted(name))
  const indexed = cold ? new Map(rows.map(([header, name]) => [name, `${header[0]} ${header[1]}`])) : undefined
  if (cold && options.prepared && options.rejectLinks && indexed) {
    // Reuse compressed bytes for precisely the blobs proved equal by the raw
    // readers. This pack contains the selected cut, without repository history.
    const reusable = protectedPaths.map(name => options.prepared!.digests.get(name)!)
      .filter((blob, i) => indexed.get(protectedPaths[i])?.split(' ')[1] === blob.oid)
    if (reusable.length > 500 || reusable.reduce((sum, blob) => sum + blob.size, 0) > 8 * 1024 * 1024) {
      run(['-c', 'core.fsync=committed', 'pack-objects', '--non-empty', '--window=0', '--compression=1',
        path.join(directory, 'objects/pack/pack').replaceAll('\\', '/')], Buffer.from([...new Set(reusable.map(blob => blob.oid))].join('\n') + '\n'))
    }
  }
  const captured = options.prepared && protectedPaths.length ? importPrepared(directory, protectedPaths, run, options, indexed)
    : changed.length ? importBlobs(cwd, directory, changed, run, options, indexed) : []
  // Windows Git uses creation time for index ctime. A restored mtime can hide a write;
  // authority may require Git itself to refresh bytes, with private attributes disabling filters.
  if (options.forceContent && protectedPaths.length) run(['add', '--renormalize', '-f', '--pathspec-from-file=-', '--pathspec-file-nul'], nul(protectedPaths))
  run(['update-index', '--refresh'])
  const tree = protectedPaths.length ? run(['write-tree']).toString().trim() : run(['hash-object', '-t', 'tree', '-w', '--stdin'], Buffer.alloc(0)).toString().trim()
  run(['update-ref', ref, tree])
  if (cold && source) {
    const roots = [sourceObjects!, ...text(source, 'count-objects', '-v').split('\n').filter(line => line.startsWith('alternate: ')).map(line => line.slice(11))]
    const target = path.join(directory, 'objects')
    if (options.rejectLinks && captured.length === protectedPaths.length) {
      // A raw first cut already imported every blob into its own pack. Retain
      // only the source cache-tree objects, without repacking all file bytes a
      // second time when the desktop profile and repository use different disks.
      const imported = new Set(captured.map(blob => blob.oid))
      const trees = text(directory, '--git-dir=.', 'rev-list', '--objects', '--no-object-names', tree).split('\n').filter(oid => !imported.has(oid))
      if (trees.length) run(['pack-objects', '--non-empty', '--window=0', path.join(directory, 'objects/pack/pack').replaceAll('\\', '/')], Buffer.from(trees.join('\n') + '\n'))
    } else if (roots.some(root => fs.statSync(root).dev !== fs.statSync(target).dev)) run(['repack', '-a', '-d', '--window=0'])
    else {
      // Copied cache-tree entries can reference source trees, not just blobs.
      const needed = new Set(run(['rev-list', '--objects', '--no-object-names', tree]).toString().trim().split('\n'))
      for (const sourceRoot of roots) {
        const packRoot = path.join(sourceRoot, 'pack')
        if (fs.existsSync(packRoot)) for (const name of fs.readdirSync(packRoot)) {
          if (!name.startsWith('pack-') || !/\.(pack|idx)$/.test(name)) continue
          const destination = path.join(target, 'pack', name)
          if (!fs.existsSync(destination)) fs.linkSync(path.join(packRoot, name), destination)
        }
        for (const prefix of new Set([...needed].map(oid => oid.slice(0, 2)))) {
          const shard = path.join(sourceRoot, prefix)
          if (!fs.existsSync(shard)) continue
          for (const name of fs.readdirSync(shard)) if (needed.has(prefix + name)) {
            const destination = path.join(target, prefix, name)
            if (!fs.existsSync(destination)) { fs.mkdirSync(path.dirname(destination), { recursive: true }); fs.linkSync(path.join(shard, name), destination) }
          }
        }
      }
    }
    fs.unlinkSync(path.join(directory, 'objects/info/alternates'))
    run(['fsck', '--connectivity-only', '--no-dangling', tree])
  }
  options.onBlobs?.(captured)
  return { relative, git_dir: directory, tree, ref }
}

/** Import all stream bytes into our pack even when the seed uses alternates. */
function importStream(directory: string, marks: string, input: number) {
  const alternates = path.join(directory, 'objects/info/alternates')
  const saved = fs.existsSync(alternates) ? fs.readFileSync(alternates) : undefined
  if (saved) fs.unlinkSync(alternates)
  try {
    shadowGit(directory, ['-c', 'core.fsync=committed', '-c', 'core.compression=0', 'fast-import', '--quiet', '--done',
      '--export-marks=' + path.relative(path.toNamespacedPath(directory), marks)], undefined, input)
  } finally { if (saved) fs.writeFileSync(alternates, saved) }
}

function importPrepared(directory: string, names: string[], run: (args: string[], data?: Buffer) => Buffer, options: GitCaptureOptions, indexed?: Map<string, string>): CapturedBlob[] {
  const prepared = options.prepared!
  importStream(directory, prepared.marks, prepared.input)
  const marks = new Map(fs.readFileSync(prepared.marks, 'utf8').trim().split('\n').map(line => line.split(' ') as [string, string]))
  const updates: string[] = [], captured: CapturedBlob[] = []
  for (const [i, name] of names.entries()) {
    const digest = prepared.digests.get(name), oid = marks.get(':' + (i + 1)), stat = options.stats!.get(name)!
    if (!digest || digest.oid !== oid || digest.size !== stat.size) fail('SNAPSHOT_GIT_IMPORT_MISMATCH')
    const mode = options.modes?.get(name) ?? (process.platform !== 'win32' && (stat.mode & 0o111) ? '100755' : '100644')
    const entry = mode + ' ' + oid
    if (indexed?.get(name) !== entry) updates.push(entry + '\t' + name + '\0')
    captured.push({...digest!, git_dir: directory})
  }
  if (updates.length) run(['update-index', '-z', '--index-info'], Buffer.from(updates.join('')))
  return captured
}

function importBlobs(cwd: string, directory: string, changed: string[], run: (args: string[], data?: Buffer) => Buffer, options: GitCaptureOptions = {}, indexed?: Map<string, string>) {
  const temporary = fs.mkdtempSync(path.toNamespacedPath(path.join(directory, '.import-')))
  const streamPath = path.join(temporary, 'blobs'), marksPath = path.join(temporary, 'marks'), modes: string[] = []
  const digests: { sha256: string; content: string; size: number }[] = []
  const remember = (data: Buffer) => {
    if (data.subarray(0, 80).toString().startsWith('version https://git-lfs.github.com/spec/v1\n')) fail('COLLABORATION_LFS_CONTENT_REQUIRED')
    const sha256 = hash(data); digests.push({ sha256, content: contentHash(data, sha256), size: data.length })
  }
  try {
    const output = fs.openSync(streamPath, 'wx')
    try {
      const buffer = Buffer.alloc(1024 * 1024), checked = new Set<string>()
      for (let i = 0; i < changed.length; i++) {
        const validated = options.stats?.get(changed[i])
        const full = validated ? path.join(cwd, changed[i]) : safe(cwd, changed[i], checked)
        const before = validated ?? fs.lstatSync(full)
        if (options.onBlobs && before.size > 64 * 1024 * 1024) fail('COLLABORATION_FILE_TOO_LARGE')
        const link = before.isSymbolicLink() ? Buffer.from(fs.readlinkSync(full)) : null
        if (link && options.rejectLinks) fail('COLLABORATION_SYMLINK_UNSUPPORTED')
        if (!link && !before.isFile()) fail('SNAPSHOT_UNSUPPORTED_FILE')
        modes.push(link ? '120000' : options.modes?.get(changed[i]) ?? (process.platform !== 'win32' && (before.mode & 0o111) ? '100755' : '100644'))
        fs.writeSync(output, `blob\nmark :${i + 1}\ndata ${link ? link.length : before.size}\n`)
        if (link) fs.writeSync(output, link)
        else {
          const source = fs.openSync(full, 'r')
          try {
            // The allowlist already checked the leaf and its parents. Verify
            // the opened identity and stability before publishing this stream.
            if (!validated && !sameStat(before, fs.fstatSync(source))) fail('SNAPSHOT_FILE_CHANGED_DURING_CAPTURE')
            const raw = options.onBlobs ? Buffer.allocUnsafe(before.size) : null
            let remaining = before.size, offset = 0
            while (remaining) {
              const bytes = raw ?? buffer
              const count = fs.readSync(source, bytes, raw ? offset : 0, raw ? remaining : Math.min(buffer.length, remaining), null)
              if (!count) fail('SNAPSHOT_FILE_CHANGED_DURING_CAPTURE')
              fs.writeSync(output, bytes, raw ? offset : 0, count); remaining -= count; offset += count
            }
            if (!sameStat(before, fs.fstatSync(source))) fail('SNAPSHOT_FILE_CHANGED_DURING_CAPTURE')
            if (raw) remember(raw)
          }
          finally { fs.closeSync(source) }
        }
        if (!validated && !sameStat(before, fs.lstatSync(full))) fail('SNAPSHOT_FILE_CHANGED_DURING_CAPTURE')
        fs.writeSync(output, '\n')
      }
      fs.writeSync(output, 'done\n')
    } finally { fs.closeSync(output) }
    const input = fs.openSync(streamPath, 'r')
    try { importStream(directory, marksPath, input) }
    finally { fs.closeSync(input) }
    const marks = new Map(fs.readFileSync(marksPath, 'utf8').trim().split('\n').map(line => line.split(' ') as [string, string]))
    // Keep the seeded stat entries when raw bytes and mode really match. Writing
    // every unchanged OID back would make Git reopen the entire tree on refresh.
    const updates = changed.flatMap((name, i) => {
      const entry = `${modes[i]} ${marks.get(':' + (i + 1))}`
      return indexed?.get(name) === entry ? [] : [`${entry}\t${name}\0`]
    })
    if (updates.length) run(['update-index', '-z', '--index-info'], Buffer.from(updates.join('')))
    return digests.map((digest, i) => ({ ...digest, git_dir: directory, oid: marks.get(':' + (i + 1))! }))
  } finally { fs.rmSync(temporary, { recursive: true, force: true }) }
}

function sameStat(left: fs.Stats, right: fs.Stats) {
  return left.size === right.size && left.mtimeMs === right.mtimeMs && left.ctimeMs === right.ctimeMs
    && left.ino === right.ino && left.dev === right.dev && left.mode === right.mode
}

export function captureGitSnapshot(receipt: Receipt, destination: string, store: string, extraTracked: string[] = [], policy: Policy = defaultPolicy): GitSnapshot {
  const root = path.resolve(receipt.task_root), started = performance.now()
  const { repos, directories, leaves } = scan(root, policy)
  const tracked = new Set(extraTracked)
  for (const repo of repos) {
    if (path.resolve(text(repo, 'rev-parse', '--show-toplevel')) !== repo) fail('SNAPSHOT_REPOSITORY_IDENTITY')
    const prefix = path.relative(root, repo).replaceAll('\\', '/')
    for (const file of git(repo, ['ls-files', '--cached', '-z']).toString().split('\0').filter(Boolean)) tracked.add(prefix ? prefix + '/' + file : file)
  }
  const protectedPaths = new Set(leaves)
  for (const rel of tracked) { if (protectedPaths.has(rel)) continue; const p = safe(root, rel); if (exists(p) && (!fs.lstatSync(p).isDirectory() || fs.lstatSync(p).isSymbolicLink())) protectedPaths.add(rel) }
  const sources = new Map(repos.map(repo => [path.relative(root, repo).replaceAll('\\', '/') || '.', repo] as [string, string | null]))
  if (!sources.has('.')) sources.set('.', null)
  const groups = new Map([...sources.keys()].map(key => [key, [] as string[]]))
  const ordered = [...sources.keys()].sort((a, b) => b.length - a.length), modes: Record<string, number> = {}
  for (const rel of protectedPaths) {
    const group = ordered.find(p => p === '.' || rel.startsWith(p + '/'))!
    groups.get(group)!.push(group === '.' ? rel : rel.slice(group.length + 1))
    modes[rel] = fs.lstatSync(path.join(root, rel)).mode & 0o7777
  }
  const partitions = [...sources].map(([relative, source]) => capturePart(root, store, relative, source, groups.get(relative)!.sort(), 'refs/traceforge/' + hash(path.resolve(destination))))
  const directory_links = [...protectedPaths].filter(rel => {
    const full = path.join(root, rel)
    return fs.lstatSync(full).isSymbolicLink() && fs.existsSync(full) && fs.statSync(full).isDirectory()
  })
  const payload: GitSnapshot = { version: 4, task_root: root, object_store: store, policy, directory_links, directories, modes, tracked: [...tracked], partitions, repositories: repos.map(repo => repoState(root, repo, destination)) }
  writeJson(path.join(destination, 'worktree.json'), payload)
  console.info(`Snapshot captured: files=${protectedPaths.size} repositories=${repos.length} total_ms=${(performance.now() - started).toFixed(1)}`)
  return payload
}

export function entries(saved: GitSnapshot): Record<string, Entry> {
  const result: Record<string, Entry> = {}
  // Cache only within this read phase; restore writes still recheck parents.
  const checked = new Set<string>()
  for (const part of saved.partitions) {
    if (!path.resolve(part.git_dir).startsWith(path.resolve(saved.object_store) + path.sep)) fail('SNAPSHOT_STORE_ESCAPE')
    const rows = shadowGit(part.git_dir, ['ls-tree', '-r', '-z', part.tree]).toString().split('\0').filter(Boolean)
    for (const row of rows) {
      const i = row.indexOf('\t'), [mode, kind, oid] = row.slice(0, i).split(' '), name = row.slice(i + 1)
      const rel = part.relative === '.' ? name : part.relative + '/' + name
      safe(saved.task_root, rel, checked)
      if (kind !== 'blob' || result[rel]) fail('SNAPSHOT_PARTITION_INVALID')
      result[rel] = { mode, oid, git_dir: part.git_dir }
    }
  }
  return result
}

export function restoreGitSnapshot(receipt: Receipt, checkpoint: string, backup: string, store: string) {
  const saved = readJson<GitSnapshot>(path.join(checkpoint, 'worktree.json')), root = path.resolve(receipt.task_root)
  if (saved.version !== 4 || saved.task_root !== root || saved.object_store !== store) fail('SNAPSHOT_IDENTITY_CHANGED')
  const desired = entries(saved)
  for (const part of saved.partitions) shadowGit(part.git_dir, ['fsck', '--full', '--no-dangling', part.tree])
  for (const [rel, parked] of Object.entries(saved.quarantined_controls || {})) {
    if (!path.resolve(parked).startsWith(path.resolve(checkpoint) + path.sep)) fail('SNAPSHOT_CONTROL_ESCAPE')
    const directory = rel === '.' ? root : safe(root, rel), target = path.join(directory, '.git')
    if (!exists(target)) { fs.mkdirSync(directory, { recursive: true }); fs.renameSync(parked, target) }
  }
  for (const repo of saved.repositories) {
    if (text(repo.repo_path, 'rev-parse', '--absolute-git-dir') !== repo.git_dir) fail('SNAPSHOT_REPOSITORY_CHANGED')
    if (repo.index_copy && hash(fs.readFileSync(repo.index_copy)) !== repo.index_sha256) fail('SNAPSHOT_INDEX_CORRUPT')
  }
  const current = captureGitSnapshot(receipt, backup, store, saved.tracked, saved.policy), before = entries(current)
  const wantedRepos = new Set(saved.repositories.map(repo => repo.repo_rel_path))
  current.quarantined_controls = {}
  for (const repo of current.repositories) if (!wantedRepos.has(repo.repo_rel_path)) current.quarantined_controls[repo.repo_rel_path] = path.join(backup, 'git-created', hash(repo.repo_rel_path))
  writeJson(path.join(backup, 'worktree.json'), current)
  for (const [rel, parked] of Object.entries(current.quarantined_controls)) { fs.mkdirSync(path.dirname(parked), { recursive: true }); fs.renameSync(path.join(root, rel, '.git'), parked) }
  const changed = [...new Set([...Object.keys(before), ...Object.keys(desired)])].filter(p => before[p]?.oid !== desired[p]?.oid || before[p]?.mode !== desired[p]?.mode || current.modes[p] !== saved.modes[p])
  for (const rel of changed.filter(p => before[p]).sort((a, b) => b.length - a.length)) fs.unlinkSync(safe(root, rel))
  for (const rel of current.directories.filter(p => !saved.directories.includes(p)).sort((a, b) => b.length - a.length)) { const p = safe(root, rel); if (fs.existsSync(p) && fs.lstatSync(p).isDirectory() && !fs.readdirSync(p).length) fs.rmdirSync(p) }
  const existingDirectories = new Set(current.directories)
  for (const rel of saved.directories.filter(p => !existingDirectories.has(p)).sort((a, b) => a.length - b.length)) fs.mkdirSync(safe(root, rel), { recursive: true })
  for (const rel of changed.filter(p => desired[p]).sort()) {
    const entry = desired[rel], p = safe(root, rel)
    if (fs.existsSync(p) && fs.lstatSync(p).isDirectory()) fs.rmdirSync(p)
    const data = shadowGit(entry.git_dir, ['cat-file', 'blob', entry.oid])
    fs.mkdirSync(path.dirname(p), { recursive: true })
    if (entry.mode === '120000') fs.symlinkSync(data.toString(), p, saved.directory_links.includes(rel) ? 'dir' : 'file')
    else { atomic(p, data); fs.chmodSync(p, saved.modes[rel]) }
  }
  for (const repo of saved.repositories) {
    if (repo.branch) { git(repo.repo_path, ['symbolic-ref', 'HEAD', 'refs/heads/' + repo.branch]); git(repo.repo_path, repo.head ? ['update-ref', 'refs/heads/' + repo.branch, repo.head] : ['update-ref', '-d', 'refs/heads/' + repo.branch]) }
    else if (repo.head) git(repo.repo_path, ['update-ref', '--no-deref', 'HEAD', repo.head])
    if (repo.index_copy) atomic(repo.index_path, fs.readFileSync(repo.index_copy)); else fs.rmSync(repo.index_path, { force: true })
  }
  const verified = captureGitSnapshot(receipt, path.join(backup, 'verification'), store, saved.tracked, saved.policy)
  const actual = entries(verified)
  const signature = (rows: Record<string, Entry>) => JSON.stringify(Object.keys(rows).sort().map(p => [p, rows[p].oid, rows[p].mode]))
  if (signature(actual) !== signature(desired)) fail('SNAPSHOT_RESTORE_VERIFY_FAILED')
  if (Object.keys(saved.modes).some(p => verified.modes[p] !== saved.modes[p]) || saved.directories.some(p => !verified.directories.includes(p))) fail('SNAPSHOT_RESTORE_METADATA_VERIFY_FAILED')
}

export function collectGitSnapshots(store: string) {
  const live = new Map<string, Set<string>>()
  function walk(directory: string) {
    for (const e of fs.readdirSync(directory, { withFileTypes: true })) {
      const p = path.join(directory, e.name)
      if (e.isSymbolicLink()) continue
      if (e.isDirectory() && e.name !== 'git-created') walk(p)
      else if (e.name === 'worktree.json') { const saved = readJson(p); if (saved.version === 4) for (const part of saved.partitions as Part[]) { if (!live.has(part.git_dir)) live.set(part.git_dir, new Set()); live.get(part.git_dir)!.add(part.ref) } }
    }
  }
  for (const e of fs.readdirSync(store, { withFileTypes: true })) if (e.isDirectory() && e.name.startsWith('turn-')) walk(path.join(store, e.name))
  const shadows = path.join(store, 'shadow')
  if (!fs.existsSync(shadows)) return
  for (const name of fs.readdirSync(shadows)) {
    const directory = path.join(shadows, name)
    const refs = shadowGit(directory, ['for-each-ref', '--format=%(refname)', 'refs/traceforge/']).toString().trim().split('\n').filter(Boolean)
    for (const ref of refs) if (!ref.startsWith('refs/traceforge/collaboration/') && !live.get(directory)?.has(ref)) shadowGit(directory, ['update-ref', '-d', ref])
    shadowGit(directory, ['-c', 'pack.window=0', 'gc', '--prune=now'])
  }
}

export function withSnapshotLock<T>(owner: string, action: () => T): T {
  fs.mkdirSync(owner, { recursive: true })
  const lock = path.join(owner, '.snapshot.lock'), fd = fs.openSync(lock, 'wx')
  try { return action() } finally { fs.closeSync(fd); fs.unlinkSync(lock) }
}
