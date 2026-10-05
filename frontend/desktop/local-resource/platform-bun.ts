import { Database } from 'bun:sqlite'
import { configurePlatform } from './platform'
configurePlatform({
  database: file => new Database(file, { create: true }),
  compress: data => Bun.zstdCompressSync(data),
  decompress: data => Buffer.from(Bun.zstdDecompressSync(data)),
})
