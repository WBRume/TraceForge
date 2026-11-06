// Vitest 2 predates node:sqlite and strips its mandatory node: prefix.
import { createRequire } from 'node:module'
export const { DatabaseSync } = createRequire(import.meta.url)('node:sqlite') as typeof import('node:sqlite')
