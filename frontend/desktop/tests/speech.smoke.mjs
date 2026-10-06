// Opt-in integration check; requires an offline build and prepared SenseVoice-Small assets.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { mkdtemp, mkdir, readFile, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { createInterface } from 'node:readline'
import { once } from 'node:events'

test('compiled offline desktop host performs real inference, cancellation and shutdown cleanup', { timeout: 60000 }, async () => {
  assert.ok(process.env.TRACEFORGE_SPEECH_TEST_WAV, 'Set TRACEFORGE_SPEECH_TEST_WAV to the official SenseVoice-Small test_wavs/zh.wav')
  const wavBase64 = (await readFile(resolve(process.env.TRACEFORGE_SPEECH_TEST_WAV))).toString('base64')
  const target = process.env.TAURI_ENV_TARGET_TRIPLE || execFileSync('rustc', ['--print', 'host-tuple'], { encoding: 'utf8' }).trim()
  const executable = resolve(`src-tauri/binaries/traceforge-desktop-host-${target}${process.platform === 'win32' ? '.exe' : ''}`)
  const resources = resolve(process.env.TRACEFORGE_SPEECH_TEST_RESOURCE_ROOT || '.')
  const root = await mkdtemp(join(tmpdir(), 'traceforge-speech-smoke-'))
  const audioTemp = join(root, '录音 temp')
  await mkdir(audioTemp)
  const child = spawn(executable, [join(root, 'config'), root, resources], {
    windowsHide: true, stdio: 'pipe',
    env: { ...process.env, TRACEFORGE_SPEECH_ASSETS: '', TMPDIR: audioTemp, TMP: audioTemp, TEMP: audioTemp },
  })
  const exit = once(child, 'exit')
  const pending = new Map()
  let sequence = 0
  let diagnostics = ''
  child.stderr.on('data', data => { diagnostics += data })
  const input = createInterface({ input: child.stdout })
  input.on('line', line => {
    const reply = JSON.parse(line)
    if (reply.kind !== 'result') return
    const waiter = pending.get(reply.id)
    pending.delete(reply.id)
    if (reply.error) waiter?.reject(new Error(reply.error))
    else waiter?.resolve(reply.result)
  })
  child.on('exit', () => {
    for (const waiter of pending.values()) waiter.reject(new Error(`Host exited: ${diagnostics}`))
    pending.clear()
  })
  const invoke = (channel, payload = {}) => new Promise((resolve, reject) => {
    const id = String(++sequence)
    pending.set(id, { resolve, reject })
    child.stdin.write(JSON.stringify({ id, channel: `sdd:speech:${channel}`, payload }) + '\n')
  })
  const waitForRecording = async () => {
    for (let attempt = 0; attempt < 100; attempt++) {
      if ((await readdir(audioTemp)).some(name => name.startsWith('traceforge-speech-'))) return
      await new Promise(resolve => setTimeout(resolve, 10))
    }
    throw new Error('Host did not create a temporary recording')
  }
  try {
    assert.deepEqual(await invoke('status'), { available: true, ready: true, reason: 'ready' })
    const result = await invoke('transcribe', { id: 'real-model', wavBase64 })
    assert.match(result.text, /早上9点至下午5点/)
    console.log(`SenseVoice-Small: ${result.text}`)
    assert.deepEqual(await readdir(audioTemp), [])
    const canceled = assert.rejects(invoke('transcribe', { id: 'cancel', wavBase64 }), /canceled/)
    await waitForRecording()
    await invoke('cancel', { id: 'cancel' })
    await canceled
    assert.deepEqual(await readdir(audioTemp), [])
    // A new recording must work after cancellation.
    assert.match((await invoke('transcribe', { id: 'retry', wavBase64 })).text, /早上9点至下午5点/)
    const interrupted = assert.rejects(invoke('transcribe', { id: 'shutdown', wavBase64 }), /canceled|Host exited/)
    await waitForRecording()
    child.stdin.end(JSON.stringify({ kind: 'shutdown' }) + '\n')
    const [code] = await exit
    await interrupted
    assert.equal(code, 0)
    assert.deepEqual(await readdir(audioTemp), [])
    assert.equal(diagnostics, '')
  } finally {
    if (child.exitCode === null) { child.stdin.end(); await exit }
    input.close()
    assert.ok(root.startsWith(join(tmpdir(), 'traceforge-speech-smoke-')))
    await rm(root, { recursive: true, force: true })
  }
})
