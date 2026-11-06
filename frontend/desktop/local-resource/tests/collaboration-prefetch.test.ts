import { expect, test } from 'vitest'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { prefetchCapture } from '../collaboration-prefetch'

test('parallel repositories share one byte budget and release their temporary streams', async () => {
  const root = fs.mkdtempSync(path.join(tmpdir(), 'tf-prefetch-budget-'))
  try {
    const names = ['a.bin', 'b.bin'], state = path.join(root, 'private')
    for (const name of names) fs.writeFileSync(path.join(root, name), Buffer.alloc(6 * 1024 * 1024))
    const budget = {remaining: 10 * 1024 * 1024}
    const outcomes = await Promise.allSettled(names.map(name => prefetchCapture(root,
      {names: [name], modes: new Map([[name, '100644']]), stats: new Map()}, state, 'sha1', budget)))
    for (const outcome of outcomes) if (outcome.status === 'fulfilled') outcome.value.dispose()
    expect(outcomes.filter(outcome => outcome.status === 'fulfilled')).toHaveLength(1)
    expect(outcomes.find(outcome => outcome.status === 'rejected')).toMatchObject({reason: {message: 'COLLABORATION_SNAPSHOT_LIMIT'}})
    expect(fs.readdirSync(state)).toEqual([])
  } finally { fs.rmSync(root, {recursive: true, force: true}) }
}, 60_000)
