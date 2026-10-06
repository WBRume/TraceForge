/** Explicit, optional resource preparation. Never called by install or normal builds. */
import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import { createReadStream, createWriteStream } from 'node:fs'
import { copyFile, mkdir, mkdtemp, readFile, rename, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import { promisify } from 'node:util'
import { OfflineSpeechService } from './service'

const execute = promisify(execFile)
const runtime = 'sherpa-onnx-v1.13.8-win-x64-shared-MT-Release-no-tts'
const model = 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17'
const sources = [
  { name: `${runtime}.tar.bz2`, url: `https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.8/${runtime}.tar.bz2`, sha256: '4b0a94f7b5c606b1b64a19a831c2127559e4b3d34e195465ebc7be73d9ed4783' },
  { name: `${model}.tar.bz2`, url: `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${model}.tar.bz2`, sha256: '7d1efa2138a65b0b488df37f8b89e3d91a60676e416f515b952358d83dfd347e' },
  { name: 'sherpa-LICENSE.txt', url: 'https://raw.githubusercontent.com/k2-fsa/sherpa-onnx/v1.13.8/LICENSE', sha256: 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30' },
  { name: 'onnxruntime-LICENSE.txt', url: 'https://raw.githubusercontent.com/microsoft/onnxruntime/v1.28.2/LICENSE', sha256: '2f07c72751aed99790b8a4869cf2311df85a860b22ded05fa22803587a48922c' },
]

async function sha256(path: string) {
  const hash = createHash('sha256')
  for await (const chunk of createReadStream(path)) hash.update(chunk)
  return hash.digest('hex')
}

async function download(source: typeof sources[number], cache: string) {
  const file = join(cache, source.name)
  if (await stat(file).catch(() => undefined)) {
    if (await sha256(file) !== source.sha256) throw new Error(`Checksum mismatch in cache: ${file}`)
    console.log(`Using verified cache: ${source.name}`)
    return file
  }
  console.log(`Downloading ${source.name}`)
  const partial = `${file}.${process.pid}.partial`
  try {
    const response = await fetch(source.url, { signal: AbortSignal.timeout(600000) })
    if (!response.ok || !response.body) throw new Error(`Download failed (${response.status}): ${source.name}`)
    await pipeline(Readable.fromWeb(response.body as unknown as Parameters<typeof Readable.fromWeb>[0]), createWriteStream(partial, { flags: 'wx' }))
    if (await sha256(partial) !== source.sha256) throw new Error(`Checksum mismatch: ${source.name}`)
    await rename(partial, file)
    return file
  } finally { await rm(partial, { force: true }) }
}

async function main() {
  if (process.platform !== 'win32' || process.arch !== 'x64') {
    throw new Error('Automatic preparation currently supports Windows x64. See README for other target runtimes.')
  }
  const destination = resolve(process.env.TRACEFORGE_SPEECH_ASSETS || 'offline-speech')
  if (await stat(destination).catch(() => undefined)) throw new Error(`Destination already exists; choose a new TRACEFORGE_SPEECH_ASSETS directory: ${destination}`)
  const cache = resolve(process.env.TRACEFORGE_SPEECH_CACHE || join(tmpdir(), 'traceforge-speech-cache'))
  await mkdir(cache, { recursive: true })
  // Fixed archive digests are checked before tar is allowed to extract anything.
  const files = await Promise.all(sources.map(source => download(source, cache)))
  await mkdir(dirname(destination), { recursive: true })
  const scratch = await mkdtemp(join(dirname(destination), '.speech-prepare-'))
  try {
    const assets = join(scratch, 'assets')
    const runtimeRoot = join(scratch, runtime)
    const modelRoot = join(scratch, model)
    await execute('tar', ['-xjf', files[0]!, '-C', scratch], { windowsHide: true, timeout: 120000 })
    await execute('tar', ['-xjf', files[1]!, '-C', scratch], { windowsHide: true, timeout: 120000 })
    await mkdir(join(assets, 'bin'), { recursive: true })
    await mkdir(join(assets, 'licenses'))
    const copies: Array<[string, string]> = [
      [join(modelRoot, 'model.int8.onnx'), 'model.int8.onnx'],
      [join(modelRoot, 'tokens.txt'), 'tokens.txt'],
      [join(modelRoot, 'LICENSE'), 'licenses/SenseVoice-Small.txt'],
      [files[2]!, 'licenses/sherpa-onnx.txt'],
      [files[3]!, 'licenses/onnxruntime.txt'],
      ...['sherpa-onnx-offline.exe', 'onnxruntime.dll', 'onnxruntime_providers_shared.dll'].map(name => [join(runtimeRoot, 'bin', name), `bin/${name}`] as [string, string]),
    ]
    await Promise.all(copies.map(([source, target]) => copyFile(source, join(assets, target))))
    // Real inference, including DLL loading, before publishing a usable asset directory.
    const service = new OfflineSpeechService({ available: true, temp: scratch, bundledAssets: assets })
    const result = await service.transcribe({ id: 'prepare', wavBase64: (await readFile(join(modelRoot, 'test_wavs', 'zh.wav'))).toString('base64') })
    if (!result.text.includes('早上9点至下午5点')) throw new Error(`Model verification failed: ${result.text}`)
    const manifest = {
      model: 'SenseVoice-Small', quantization: 'int8', runtime: 'sherpa-onnx 1.13.8', platform: process.platform, arch: process.arch,
      sources, files: Object.fromEntries(await Promise.all(copies.map(async ([, target]) => [target, await sha256(join(assets, target))]))),
    }
    await writeFile(join(assets, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n')
    await rename(assets, destination)
    console.log(`Verified SenseVoice-Small INT8: ${result.text}\nResources ready: ${destination}`)
    console.log(`No build settings were changed. Set TRACEFORGE_SPEECH_MODE=offline to use ${basename(destination)}.`)
  } finally {
    // Only remove the freshly allocated staging directory, never the destination/cache.
    if (dirname(scratch) === dirname(destination) && basename(scratch).startsWith('.speech-prepare-')) await rm(scratch, { recursive: true, force: true })
  }
}

await main().catch(error => { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1 })
