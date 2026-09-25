export interface JournalDatabase {
  exec(sql: string): unknown
  query(sql: string): { get(...args: any[]): unknown; all(...args: any[]): unknown[]; run(...args: any[]): unknown }
  close(): void
}

export interface RuntimePlatform {
  database(file: string): JournalDatabase
  compress(data: string): Uint8Array
  decompress(data: Uint8Array): Buffer
}

let configured: RuntimePlatform | undefined
export function configurePlatform(platform: RuntimePlatform) { configured = platform }
export function platform(): RuntimePlatform {
  if (!configured) throw new Error('Resource Host runtime platform is not configured')
  return configured
}
