/** SHA256 wire identities backed by the snapshot engine's immutable Git blobs. */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { createHash, randomUUID } from 'node:crypto'
import { atomic, fail, hash, readJson } from './filesystem'
import { shadowGit } from './git-snapshots'

export interface GitBlob { git_dir: string; oid: string; size: number }
export interface GitEntry extends GitBlob { path: string; mode: string }
const validHash = (value: string) => { if (!/^[a-f0-9]{64}$/.test(value)) fail('INVALID_CONTENT_DIGEST'); return value }
const oidHash = (data: Buffer, oid: string) => createHash(oid.length === 64 ? 'sha256' : 'sha1').update(`blob ${data.length}\0`).update(data).digest('hex')

export function treeEntries(directory: string, tree: string, paths?: string[]): GitEntry[] {
  if (paths && !paths.length) return []
  return shadowGit(directory, ['--literal-pathspecs', 'ls-tree', '-r', '-l', '-z', tree, ...(paths ? ['--', ...paths] : [])]).toString().split('\0').filter(Boolean).map(row => {
    const match = /^(\d+) blob ([a-f0-9]+)\s+(\d+)\t([\s\S]+)$/.exec(row)
    if (!match) fail('COLLABORATION_LINK_OR_SUBMODULE_UNSUPPORTED')
    return { git_dir: directory, mode: match![1], oid: match![2], size: Number(match![3]), path: match![4] }
  })
}

export function readGitBlobs(directory: string, entries: GitBlob[], consume: (entry: GitBlob, data: Buffer) => void) {
  for (let start = 0; start < entries.length;) {
    let end = start, bytes = 0
    while (end < entries.length && (end === start || bytes + entries[end].size < 64 * 1024 * 1024)) bytes += entries[end++].size
    const batch = entries.slice(start, end), output = shadowGit(directory, ['cat-file', '--batch'], Buffer.from(batch.map(entry => entry.oid + '\n').join('')))
    let offset = 0
    for (const entry of batch) {
      const newline = output.indexOf(10, offset), header = output.subarray(offset, newline).toString()
      if (newline < offset || header !== `${entry.oid} blob ${entry.size}`) fail('CORRUPT_LOCAL_CONTENT_OBJECT')
      const data = output.subarray(newline + 1, newline + 1 + entry.size)
      if (data.length !== entry.size || output[newline + 1 + entry.size] !== 10 || oidHash(data, entry.oid) !== entry.oid) fail('CORRUPT_LOCAL_CONTENT_OBJECT')
      consume(entry, data); offset = newline + 2 + entry.size
    }
    if (offset !== output.length) fail('CORRUPT_LOCAL_CONTENT_OBJECT')
    start = end
  }
}

export class GitContent {
  readonly state: string
  private records: Record<string, GitBlob>
  private byOid = new Map<string, string>()
  private destination?: string
  constructor(state: string) {
    this.state = state
    const index = path.join(state, 'git-content.json')
    this.records = fs.existsSync(index) ? readJson(index).objects : {}
    for (const [sha, entry] of Object.entries(this.records)) this.byOid.set(entry.oid, sha)
  }
  private save() { atomic(path.join(this.state, 'git-content.json'), JSON.stringify({ version: 1, objects: this.records })) }
  preferStore(directory: string) { this.destination = directory }
  private legacy(digest: string) { return path.join(this.state, 'objects', digest.slice(0, 2), validHash(digest)) }
  private register(digest: string, entry: GitBlob) { this.records[digest] = entry; this.byOid.set(entry.oid, digest) }
  registerTree(entries: GitEntry[]) {
    let count = 0, bytes = 0
    const missing = new Map<string, GitBlob>()
    for (const entry of entries) {
      if (entry.size > 64 * 1024 * 1024) fail('COLLABORATION_FILE_TOO_LARGE: ' + entry.path)
      if (!this.byOid.has(entry.oid)) missing.set(entry.oid, entry)
    }
    if (entries.length) readGitBlobs(entries[0].git_dir, [...missing.values()], (entry, data) => {
      if (data.subarray(0, 80).toString().startsWith('version https://git-lfs.github.com/spec/v1\n')) fail('COLLABORATION_LFS_CONTENT_REQUIRED')
      this.register(hash(data), entry); count++; bytes += data.length
    })
    const files = entries.map(entry => {
      const sha256 = this.byOid.get(entry.oid)!
      this.register(sha256, { git_dir: entry.git_dir, oid: entry.oid, size: entry.size })
      return { path: entry.path, mode: entry.mode, sha256, size: entry.size }
    })
    if (entries.length) this.save()
    return { files, new_blobs: count, new_blob_bytes: bytes }
  }
  private lookup(digest: string, migrate = true): GitBlob | undefined {
    validHash(digest)
    if (migrate && !this.records[digest] && fs.existsSync(this.legacy(digest))) {
      const data = fs.readFileSync(this.legacy(digest))
      if (hash(data) !== digest) fail('CORRUPT_LOCAL_CONTENT_OBJECT')
      this.putMany([{ sha256: digest, data }])
    }
    return this.records[digest]
  }
  file(digest: string) {
    const entry = this.lookup(digest)
    return entry ? path.join(entry.git_dir, 'objects', entry.oid.slice(0, 2), entry.oid.slice(2)) : this.legacy(digest)
  }
  get(digest: string): Buffer {
    const entry = this.lookup(digest)
    if (!entry) fail('LOCAL_CONTENT_OBJECT_MISSING')
    let value: Buffer | undefined
    try { readGitBlobs(entry!.git_dir, [entry!], (_entry, data) => { value = Buffer.from(data) }) }
    catch { fail('CORRUPT_LOCAL_CONTENT_OBJECT') }
    if (!value || hash(value) !== digest) fail('CORRUPT_LOCAL_CONTENT_OBJECT')
    return value!
  }
  /** Git validates immutable object type/size in batches; raw bytes are verified when used. */
  check(entries: { sha256: string; size?: number }[], migrate = true) {
    if (migrate) {
      let batch: { sha256: string; data: Buffer }[] = [], bytes = 0
      for (const digest of new Set(entries.map(entry => validHash(entry.sha256)))) {
        if (this.records[digest] || !fs.existsSync(this.legacy(digest))) continue
        const data = fs.readFileSync(this.legacy(digest))
        if (hash(data) !== digest) fail('CORRUPT_LOCAL_CONTENT_OBJECT')
        batch.push({ sha256: digest, data }); bytes += data.length
        if (bytes >= 32 * 1024 * 1024) { this.putMany(batch); batch = []; bytes = 0 }
      }
      if (batch.length) this.putMany(batch)
    }
    const missing = new Set<string>(), groups = new Map<string, Map<string, { digest: string; size: number }>>()
    for (const entry of entries) {
      const object = this.lookup(entry.sha256, false)
      if (!object) { missing.add(entry.sha256); continue }
      if (entry.size !== undefined && entry.size !== object.size) fail('CONTENT_OBJECT_SIZE_MISMATCH')
      if (!groups.has(object.git_dir)) groups.set(object.git_dir, new Map())
      groups.get(object.git_dir)!.set(object.oid, { digest: entry.sha256, size: object.size })
    }
    for (const [directory, objects] of groups) {
      let rows: string[]
      try { rows = shadowGit(directory, ['cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)'], Buffer.from([...objects.keys()].join('\n') + '\n')).toString().trim().split('\n') }
      catch { fail('CORRUPT_LOCAL_CONTENT_OBJECT') }
      if (rows!.length !== objects.size) fail('CORRUPT_LOCAL_CONTENT_OBJECT')
      const expectedRows = [...objects]
      rows!.forEach((row, index) => {
        const [oid, expected] = expectedRows[index]
        if (row === oid + ' missing') missing.add(expected.digest)
        else if (row !== `${oid} blob ${expected.size}`) fail('CORRUPT_LOCAL_CONTENT_OBJECT')
      })
    }
    return [...missing]
  }
  putMany(entries: { sha256: string; data: Buffer }[]) {
    for (const entry of entries) {
      validHash(entry.sha256)
      if (entry.data.length > 64 * 1024 * 1024) fail('COLLABORATION_FILE_TOO_LARGE')
      if (hash(entry.data) !== entry.sha256) fail('CONTENT_OBJECT_DIGEST_MISMATCH')
      if (entry.data.subarray(0, 80).toString().startsWith('version https://git-lfs.github.com/spec/v1\n')) fail('COLLABORATION_LFS_CONTENT_REQUIRED')
    }
    const missing = new Set(this.check(entries.map(entry => ({ sha256: entry.sha256, size: entry.data.length })), false))
    const added = [...new Map(entries.filter(entry => missing.has(entry.sha256)).map(entry => [entry.sha256, entry])).values()]
    if (!added.length) return
    const directory = this.destination ?? path.join(this.state, 'transfer.git')
    if (!fs.existsSync(directory)) { fs.mkdirSync(directory, { recursive: true }); shadowGit(directory, ['init', '--bare', '.']) }
    const temporary = path.join(directory, 'import-' + randomUUID()), marks = temporary + '.marks'
    const fd = fs.openSync(temporary, 'wx')
    try {
      for (const [index, entry] of added.entries()) {
        fs.writeSync(fd, `blob\nmark :${index + 1}\ndata ${entry.data.length}\n`); fs.writeSync(fd, entry.data); fs.writeSync(fd, '\n')
      }
      fs.writeSync(fd, 'done\n'); fs.fsyncSync(fd)
    } finally { fs.closeSync(fd) }
    try {
      const input = fs.openSync(temporary, 'r')
      try { shadowGit(directory, ['-c', 'core.fsync=committed', 'fast-import', '--quiet', '--done', '--export-marks=' + path.basename(marks)], undefined, input) }
      finally { fs.closeSync(input) }
      const ids = new Map(fs.readFileSync(marks, 'utf8').trim().split('\n').map(row => row.split(' ') as [string, string]))
      const records = added.map((entry, index) => ({ digest: entry.sha256, git_dir: directory, oid: ids.get(':' + (index + 1))!, size: entry.data.length }))
      shadowGit(directory, ['update-ref', '--stdin'], Buffer.from(records.map(entry => `update refs/traceforge/collaboration/objects/${entry.digest} ${entry.oid}\n`).join('')))
      for (const { digest, ...entry } of records) this.register(digest, entry)
      this.save()
    } finally { fs.rmSync(temporary, { force: true }); fs.rmSync(marks, { force: true }) }
  }
}
