import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const require = createRequire(import.meta.url)
for (const runtime of ['node', 'electron']) test(`${runtime} workers survive closed stdout and stderr pipes`, { timeout: 15000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'tf-closed-output-'))
  const report = join(root, 'report.txt')
  const service = pathToFileURL(resolve(`${runtime === 'electron' ? 'dist-electron' : 'dist-desktop-host'}/localResourceService.js`)).href
  const script = join(root, 'fixture.cjs')
  await writeFile(script, `
    const fs = require('node:fs'), { Worker } = require('node:worker_threads');
    let exit = code => process.exit(code);
    const fail = error => { fs.writeFileSync(${JSON.stringify(report)}, String(error.stack || error)); exit(1); };
    process.on('uncaughtException', fail);
    async function run() {
      const { startLocalResourceService } = await import(${JSON.stringify(service)});
      const host = await startLocalResourceService({ state_root: ${JSON.stringify(join(root, 'state'))}, allowed_roots: [], token: 'x'.repeat(32) }, { http: false });
      const worker = new Worker("console.log('worker stdout'); console.error('worker stderr');", { eval: true });
      await new Promise((resolve, reject) => { worker.once('exit', resolve); worker.once('error', reject); });
      console.log('main stdout'); console.error('main stderr');
      await new Promise(resolve => setTimeout(resolve, 100));
      await host.close();
      fs.writeFileSync(${JSON.stringify(report)}, 'ok'); exit(0);
    }
    if (process.versions.electron) {
      const { app } = require('electron'); app.disableHardwareAcceleration();
      exit = code => app.exit(code); app.whenReady().then(run).catch(fail);
    } else run().catch(fail);
  `)
  const env = { ...process.env }
  delete env.ELECTRON_RUN_AS_NODE
  const child = spawn(runtime === 'electron' ? require('electron') : process.execPath, [script], { env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
  const exited = once(child, 'exit')
  child.stdout.destroy(); child.stderr.destroy()
  try {
    const [code] = await exited
    const result = await readFile(report, 'utf8')
    assert.equal(code, 0, result)
    assert.equal(result, 'ok')
  } finally {
    if (child.exitCode === null) { child.kill(); await exited }
    assert.ok(root.startsWith(join(tmpdir(), 'tf-closed-output-')))
    await rm(root, { recursive: true, force: true })
  }
})
