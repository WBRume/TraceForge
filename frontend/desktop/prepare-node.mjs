import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { chmod, copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// Keep the runtime deterministic and new enough for node:sqlite and Zstd.
export const NODE_VERSION = '24.11.1'
export const targets = {
  'x86_64-pc-windows-msvc': ['win', 'x64', 'win32'],
  'aarch64-pc-windows-msvc': ['win', 'arm64', 'win32'],
  'x86_64-unknown-linux-gnu': ['linux', 'x64', 'linux'],
  'aarch64-unknown-linux-gnu': ['linux', 'arm64', 'linux'],
  'x86_64-apple-darwin': ['darwin', 'x64', 'darwin'],
  'aarch64-apple-darwin': ['darwin', 'arm64', 'darwin'],
}
const frontend = fileURLToPath(new URL('../', import.meta.url))

async function download(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(120000) })
  if (!response.ok) throw new Error(`Node runtime download failed (${response.status}): ${url}`)
  return Buffer.from(await response.arrayBuffer())
}

export async function prepareNode(target) {
  const spec = targets[target]
  if (!spec) throw new Error(`Unsupported desktop Node target: ${target}`)
  const [distribution, arch, platform] = spec
  const binaries = join(frontend, 'src-tauri/binaries')
  const resources = join(frontend, 'dist-desktop-host')
  await mkdir(binaries, { recursive: true })
  await mkdir(resources, { recursive: true })
  const output = join(binaries, `traceforge-node-${target}${platform === 'win32' ? '.exe' : ''}`)
  const localLicense = join(dirname(process.execPath), 'LICENSE')
  const license = await readFile(localLicense).catch(() => undefined)
  if (process.version === `v${NODE_VERSION}` && process.platform === platform && process.arch === arch && license) {
    await copyFile(process.execPath, output)
    await writeFile(join(resources, 'NODE-LICENSE.txt'), license)
  } else {
    const base = `https://nodejs.org/dist/v${NODE_VERSION}/`
    const artifact = platform === 'win32' ? `win-${arch}/node.exe` : `node-v${NODE_VERSION}-${distribution}-${arch}.tar.gz`
    const checksums = (await download(base + 'SHASUMS256.txt')).toString('utf8')
    const expected = checksums.split(/\r?\n/).map(line => line.trim().split(/\s+/)).find(([, name]) => name === artifact)?.[0]
    if (!expected) throw new Error(`Missing official Node checksum: ${artifact}`)
    const cache = join(frontend, '.verify/node-runtime', `v${NODE_VERSION}`, artifact.replaceAll('/', '_'))
    const cached = await readFile(cache).catch(error => { if (error.code !== 'ENOENT') throw error })
    const data = cached || await download(base + artifact)
    if (createHash('sha256').update(data).digest('hex') !== expected) throw new Error(`Node checksum mismatch: ${artifact}`)
    if (!cached) { await mkdir(dirname(cache), { recursive: true }); await writeFile(cache, data) }
    if (platform === 'win32') {
      await writeFile(output, data)
      await writeFile(join(resources, 'NODE-LICENSE.txt'), await download(`https://raw.githubusercontent.com/nodejs/node/v${NODE_VERSION}/LICENSE`))
    } else {
      const staging = await mkdtemp(join(binaries, '.node-'))
      try {
        const archive = join(staging, 'runtime.tar.gz')
        await writeFile(archive, data)
        const folder = `node-v${NODE_VERSION}-${distribution}-${arch}`
        execFileSync('tar', ['-xzf', archive, '-C', staging, `${folder}/bin/node`, `${folder}/LICENSE`], { windowsHide: true })
        await copyFile(join(staging, folder, 'bin/node'), output)
        await copyFile(join(staging, folder, 'LICENSE'), join(resources, 'NODE-LICENSE.txt'))
      } finally {
        if (!resolve(staging).startsWith(resolve(binaries) + '/.node-') && !resolve(staging).startsWith(resolve(binaries) + '\\.node-')) throw new Error('Invalid Node staging directory')
        await rm(staging, { recursive: true, force: true })
      }
    }
  }
  if (platform !== 'win32') await chmod(output, 0o755)
  await writeFile(join(resources, 'package.json'), JSON.stringify({ private: true, type: 'module' }) + '\n')
  await writeFile(join(resources, 'runtime.json'), JSON.stringify({ version: NODE_VERSION, target }) + '\n')
  console.log(`Prepared Node ${NODE_VERSION} for ${target}`)
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const target = process.env.TAURI_ENV_TARGET_TRIPLE || execFileSync('rustc', ['--print', 'host-tuple'], { encoding: 'utf8', windowsHide: true }).trim()
  await prepareNode(target)
}
