const { readFileSync, statSync } = require('node:fs')
const { resolve, join } = require('node:path')

function speechBuildOptions(env = process.env) {
  const mode = env.TRACEFORGE_SPEECH_MODE || 'api'
  if (!['off', 'api', 'offline'].includes(mode)) throw new Error('TRACEFORGE_SPEECH_MODE must be off, api or offline')
  const enabled = mode === 'offline'
  const bundled = env.TRACEFORGE_BUNDLE_SPEECH === '1'
  if (bundled && !enabled) throw new Error('TRACEFORGE_BUNDLE_SPEECH=1 requires TRACEFORGE_SPEECH_MODE=offline')
  return { mode, enabled, bundled, assetsDirectory: resolve(env.TRACEFORGE_SPEECH_ASSETS || 'offline-speech') }
}

function validateSpeechAssets(options, platform = process.platform, arch = process.arch) {
  if (!options.bundled) return // Never inspect or require Sherpa in ordinary builds.
  const required = ['tokens.txt', 'model.int8.onnx', join('bin', platform === 'win32' ? 'sherpa-onnx-offline.exe' : 'sherpa-onnx-offline')]
  if (platform === 'win32') required.push('bin/onnxruntime.dll')
  for (const file of required) {
    const path = join(options.assetsDirectory, file)
    let valid = false
    try { const info = statSync(path); valid = info.isFile() && info.size > 0 } catch {}
    if (!valid) throw new Error(`Missing offline speech asset: ${path}`)
  }
  let manifest
  try { manifest = JSON.parse(readFileSync(join(options.assetsDirectory, 'manifest.json'), 'utf8')) }
  catch (error) { if (error.code !== 'ENOENT') throw error }
  if (manifest && (manifest.model !== 'SenseVoice-Small' || manifest.quantization !== 'int8'
    || manifest.platform !== platform || manifest.arch !== arch)) {
    throw new Error(`Offline speech assets must be SenseVoice-Small INT8 for ${platform}/${arch}`)
  }
}

module.exports = { speechBuildOptions, validateSpeechAssets }
