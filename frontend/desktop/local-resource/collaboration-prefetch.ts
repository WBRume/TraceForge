import * as fs from 'node:fs'
import * as path from 'node:path'
import { Worker } from 'node:worker_threads'
import { availableParallelism } from 'node:os'
import { BINARY_PROBE, normalizeEol } from './content-identity'
import { fail } from './filesystem'
import type { PreparedGitImport } from './git-snapshots'

export interface CaptureInventory { names: string[]; modes: Map<string, string>; stats: Map<string, fs.Stats> }
export interface PreparedCapture { inventory: CaptureInventory; stream: PreparedGitImport; bytes: number; elapsed_ms: number; dispose(): void }
export type CaptureBudget = number | {remaining: number}
export function reserveCaptureBudget(budget: CaptureBudget, bytes: number) {
  if (bytes > (typeof budget === 'number' ? budget : budget.remaining)) fail('COLLABORATION_SNAPSHOT_LIMIT')
  if (typeof budget !== 'number') budget.remaining -= bytes
}
const statFields = ['size', 'mtimeMs', 'ctimeMs', 'ino', 'dev', 'mode'] as const

/** Workers write disjoint frames into one private import stream; no source index is touched. */
export async function prefetchCapture(root: string, inventory: CaptureInventory, state: string, algorithm: string, maxBytes: CaptureBudget = 512 * 1024 * 1024): Promise<PreparedCapture> {
  const started = performance.now(), names = inventory.names
  if (names.length > 100_000) fail('COLLABORATION_SNAPSHOT_LIMIT')
  const count = Math.min(4, availableParallelism(), Math.ceil(names.length / 256))
  const groups = Array.from({ length: count }, () => [] as {name: string; full: string}[])
  names.forEach((name, i) => groups[i % count].push({name, full: path.join(root, name)}))
  const stats = await workers(groups.map(files => ({phase: 'stat', files}))) as [string, fs.Stats][][]
  inventory.stats.clear()
  for (const records of stats) for (const [name, stat] of records) inventory.stats.set(name, Object.setPrototypeOf(stat, fs.Stats.prototype))
  inventory.names = names.filter(name => inventory.stats.has(name))
  const bytes = [...inventory.stats.values()].reduce((sum, stat) => sum + stat.size, 0)
  reserveCaptureBudget(maxBytes, bytes)
  fs.mkdirSync(state, {recursive: true})
  const directory = fs.mkdtempSync(path.toNamespacedPath(path.join(state, '.capture-')))
  const file = path.join(directory, 'blobs'), marks = path.join(directory, 'marks')
  let input = fs.openSync(file, 'wx+')
  let disposed = false
  const dispose = () => {
    if (disposed) return
    disposed = true
    try { if (input >= 0) fs.closeSync(input) } finally {
      fs.rmSync(file, {force: true}); fs.rmSync(marks, {force: true}); fs.rmdirSync(directory)
    }
  }
  try {
    let position = 0
    const frames = Array.from({length: count}, () => [] as any[])
    inventory.names.forEach((name, i) => {
      const stat = inventory.stats.get(name)!, header = 'blob\nmark :' + (i + 1) + '\ndata ' + stat.size + '\n'
      frames[i % count].push({name, full: path.join(root, name), header, position,
        stat: Object.fromEntries(statFields.map(key => [key, stat[key]]))})
      position += Buffer.byteLength(header) + stat.size + 1
    })
    fs.ftruncateSync(input, position + 5)
    const identity = fs.fstatSync(input)
    const results = await workers(frames.map(files => ({phase: 'write', files, output: file, identity: {ino: identity.ino, dev: identity.dev, size: identity.size, mode: identity.mode}, algorithm, binaryProbe: BINARY_PROBE, normalizer: normalizeEol.toString()}))) as [string, PreparedGitImport['digests'] extends ReadonlyMap<string, infer T> ? T : never][][]
    fs.writeSync(input, Buffer.from('done\n'), 0, 5, position)
    const output = input; input = -1; fs.closeSync(output); input = fs.openSync(file, 'r')
    const digests = new Map(results.flat())
    return {inventory, stream: {input, marks, digests}, bytes, elapsed_ms: performance.now() - started, dispose}
  } catch (error) { dispose(); throw error }
}

async function workers(jobs: object[]): Promise<unknown[]> {
  const results = await Promise.allSettled(jobs.map(workerData => new Promise<unknown>((resolve, reject) => {
    const worker = new Worker(readFiles, {eval: true, workerData, trackUnmanagedFds: false})
    let result: unknown
    worker.once('message', value => {result = value})
    worker.once('error', reject)
    worker.once('exit', code => code === 0 && result ? resolve(result) : reject(new Error('SNAPSHOT_PREFETCH_WORKER_FAILED')))
  })))
  const failure = results.find(result => result.status === 'rejected')
  if (failure?.status === 'rejected') throw failure.reason
  return results.map(result => (result as PromiseFulfilledResult<unknown>).value)
}

const readFiles = `
const fs = require('node:fs'), { createHash } = require('node:crypto'), { parentPort, workerData } = require('node:worker_threads');
const records = [];
if (workerData.phase === 'stat') {
  for (const {name, full} of workerData.files) {
    let stat;
    try { stat = fs.lstatSync(full); } catch (error) { if (['ENOENT','ENOTDIR'].includes(error.code)) continue; throw error; }
    if (stat.isSymbolicLink()) throw new Error('COLLABORATION_SYMLINK_UNSUPPORTED');
    if (stat.isDirectory()) continue;
    if (!stat.isFile()) throw new Error('COLLABORATION_UNSUPPORTED_FILE');
    if (stat.size > 64 * 1024 * 1024) throw new Error('COLLABORATION_FILE_TOO_LARGE');
    records.push([name, stat]);
  }
} else {
  const normalize = (0,eval)('(' + workerData.normalizer + ')');
  const output = fs.openSync(workerData.output, 'r+');
  try {
  const opened = fs.fstatSync(output);
  if (fs.lstatSync(workerData.output).isSymbolicLink() || Object.keys(workerData.identity).some(key => opened[key] !== workerData.identity[key])) throw new Error('SNAPSHOT_IMPORT_STREAM_CHANGED');
  const write = (data, position) => {
    let offset = 0;
    while (offset < data.length) {
      const count = fs.writeSync(output, data, offset, data.length - offset, position + offset);
      if (!count) throw new Error('SNAPSHOT_IMPORT_STREAM_WRITE_FAILED');
      offset += count;
    }
  };
  for (const {name, full, stat, header, position} of workerData.files) {
    const file = fs.openSync(full, 'r');
    try {
      const prefix = Buffer.from(header);
      const frame = Buffer.allocUnsafeSlow(prefix.length + stat.size + 1);
      prefix.copy(frame); frame[frame.length - 1] = 10;
      const data = frame.subarray(prefix.length, prefix.length + stat.size);
      let offset = 0;
      while (offset < data.length) {
        const count = fs.readSync(file, data, offset, data.length - offset, null);
        if (!count) throw new Error('SNAPSHOT_FILE_CHANGED_DURING_CAPTURE');
        offset += count;
      }
      const after = fs.fstatSync(file);
      if (Object.keys(stat).some(key => after[key] !== stat[key])) throw new Error('SNAPSHOT_FILE_CHANGED_DURING_CAPTURE');
      if (data.subarray(0,80).toString().startsWith('version https://git-lfs.github.com/spec/v1' + String.fromCharCode(10))) throw new Error('COLLABORATION_LFS_CONTENT_REQUIRED');
      const sha256 = createHash('sha256').update(data).digest('hex');
      const oid = createHash(workerData.algorithm).update('blob ' + data.length).update(Buffer.from([0])).update(data).digest('hex');
      const normalized = normalize(data, workerData.binaryProbe);
      const content = normalized === data ? sha256 : createHash('sha256').update(normalized).digest('hex');
      write(frame, position);
      records.push([name, {oid, sha256, content, size: data.length}]);
    } finally { fs.closeSync(file); }
  }
  } finally { fs.closeSync(output); }
}
parentPort.postMessage(records);
`
