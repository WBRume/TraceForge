import { afterEach, expect, test } from 'bun:test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { startServer } from '../server'

const roots: string[] = []
const services: Awaited<ReturnType<typeof startServer>>[] = []
const headers = { Authorization: 'Bearer ' + 'x'.repeat(32) }

afterEach(async () => {
  await Promise.all(services.splice(0).map(service => service.close()))
  for (const root of roots.splice(0)) {
    if (!root.startsWith(join(tmpdir(), 'tf-resource-lifecycle-'))) throw new Error('Invalid test directory')
    rmSync(root, { recursive: true, force: true })
  }
})

function config() {
  const root = mkdtempSync(join(tmpdir(), 'tf-resource-lifecycle-'))
  roots.push(root)
  return { state_root: root, allowed_roots: [], token: 'x'.repeat(32), port: 0 }
}

test('embedded startup failure does not stop the desktop runtime', async () => {
  for (const script of ["throw new Error('worker crash fixture')", 'self.close()']) {
    const settings = config()
    const workerFile = join(settings.state_root, 'failed-worker.ts')
    writeFileSync(workerFile, script)
    await expect(startServer(settings, { workerUrl: pathToFileURL(workerFile).href })).rejects.toThrow()
    const service = await startServer(settings)
    services.push(service)
    expect(service.isRunning()).toBe(true)
    expect((await fetch(new URL('/v1/identity', service.server.url), { headers })).status).toBe(200)
  }
})

test('occupied ports release initialization state and leave the running service intact', async () => {
  const service = await startServer(config())
  services.push(service)
  const other = config()
  await expect(startServer({ ...other, port: service.server.port })).rejects.toThrow()
  expect((await fetch(new URL('/v1/identity', service.server.url), { headers })).status).toBe(200)
  const retry = await startServer(other)
  services.push(retry)
  expect(retry.isRunning()).toBe(true)
})

test('shutdown is idempotent and releases the port and journal for restart', async () => {
  const settings = config()
  const service = await startServer(settings)
  services.push(service)
  const port = service.server.port
  const url = new URL('/v1/identity', service.server.url)
  const identity = await fetch(url, { headers }).then(response => response.json())
  await Promise.all([service.close(), service.close()])
  expect(service.isRunning()).toBe(false)
  await expect(fetch(url, { headers })).rejects.toThrow()
  const restarted = await startServer({ ...settings, port })
  services.push(restarted)
  expect(await fetch(url, { headers }).then(response => response.json())).toEqual(identity)
})
