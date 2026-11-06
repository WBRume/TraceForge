import { DatabaseSync } from 'node:sqlite'
import { zstdCompressSync, zstdDecompressSync } from 'node:zlib'
import { configurePlatform } from './platform'

export function decompressFrames(data: Uint8Array): Buffer {
  const frames: Buffer[] = []
  let offset = 0
  while (offset < data.byteLength) {
    // Node 24 decodes one frame per call. DSH appends independent Zstd frames.
    const result = zstdDecompressSync(data.subarray(offset), { info: true }) as unknown as { buffer: Buffer; engine: { bytesWritten: number } }
    if (!result.engine.bytesWritten) throw new Error('Invalid Zstd frame')
    offset += result.engine.bytesWritten
    frames.push(result.buffer)
  }
  return Buffer.concat(frames)
}

configurePlatform({
  database: file => {
    const db = new DatabaseSync(file)
    return { exec: sql => db.exec(sql), query: sql => db.prepare(sql), close: () => db.close() }
  },
  compress: data => zstdCompressSync(Buffer.from(data)),
  decompress: decompressFrames,
})
