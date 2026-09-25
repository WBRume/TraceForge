import { parentPort } from 'node:worker_threads'
import { DatabaseSync } from 'node:sqlite'
import { zstdCompressSync, zstdDecompressSync } from 'node:zlib'
import { configurePlatform } from '../../resource-host/src/platform'
import { Runtime } from '../../resource-host/src/runtime'

configurePlatform({
  database: file => {
    const db = new DatabaseSync(file)
    return { exec: sql => db.exec(sql), query: sql => db.prepare(sql), close: () => db.close() }
  },
  compress: data => zstdCompressSync(Buffer.from(data)),
  decompress: data => zstdDecompressSync(data),
})
let runtime: Runtime
parentPort!.on('message', ({ id, kind, payload }) => {
  try {
    if (kind === 'configure') runtime = new Runtime(payload)
    const result = kind === 'inspect' ? runtime.inspect(payload)
      : kind === 'operation' ? runtime.operation(payload) : true
    parentPort!.postMessage({ id, result })
  } catch (error) {
    parentPort!.postMessage({ id, error: error instanceof Error ? error.message : String(error) })
  }
})
