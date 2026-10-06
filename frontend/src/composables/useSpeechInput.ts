import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { SpeechRecorder } from '@/utils/speech/recorder'
import { speechMode } from '@/utils/speech/mode'
import { QwenSpeechStream, type SpeechSession } from '@/utils/speech/qwen'
import api from '@/utils/api'

type ApiConnection = {
  controller: AbortController
  stream: QwenSpeechStream
  promise: Promise<void>
  sampleRate: number
  ready: boolean
  silenceTimer?: number
}

export function useSpeechInput(options: { disabled: () => boolean; contextKey: () => string; onTranscript: (text: string) => void }) {
  const mode = speechMode()
  const ready = ref(mode === 'api')
  const state = ref<'idle' | 'starting' | 'recording' | 'transcribing'>('idle')
  const error = ref('')
  const connecting = ref(false)
  const seconds = ref(0)
  const level = ref(0)
  const busy = computed(() => state.value !== 'idle')
  const visible = mode !== 'off'
  let recorder: SpeechRecorder | undefined
  let connection: ApiConnection | undefined
  let prepared: ApiConnection | undefined
  let cachedSession: SpeechSession | undefined
  let preparationTimer: number | undefined
  let retryDelay = 1000
  let mounted = false
  let foreground = true
  let generation = 0
  let requestId = ''
  let timer: number | undefined
  let disposed = false

  function clearTimer() { window.clearInterval(timer); timer = undefined }

  function clearStandby(entry: ApiConnection) {
    window.clearInterval(entry.silenceTimer)
    entry.silenceTimer = undefined
  }

  function release(entry?: ApiConnection) {
    if (!entry) return
    clearStandby(entry); entry.controller.abort(); entry.stream.cancel()
  }

  function createConnection(sampleRate = 16000): ApiConnection {
    const controller = new AbortController()
    const failed = (reason: unknown) => {
      if (connection !== entry && prepared !== entry) return
      cachedSession = undefined
      if (connection === entry) { cancel(false); failure(reason); schedulePreparation(30000) }
      else if (prepared === entry) {
        prepared = undefined; release(entry)
        const status = (reason as { response?: { status?: number } })?.response?.status
        retryDelay = status === 429 ? 60000 : Math.min(retryDelay * 2, 60000)
        schedulePreparation(retryDelay)
      }
    }
    const remote = new QwenSpeechStream(text => {
      if (connection === entry && !options.disabled()) options.onTranscript(text)
    }, failed)
    const credentials = cachedSession && cachedSession.expires_at * 1000 > Date.now() + 15000
      ? Promise.resolve(cachedSession)
      : api.post<SpeechSession>('/speech/sessions', null, { signal: controller.signal, timeout: 8000 }).then(({ data }) => data)
    const entry: ApiConnection = {
      controller, stream: remote, sampleRate, ready: false,
      promise: credentials.then(async data => {
        if (controller.signal.aborted) return
        cachedSession = data
        await remote.start(data, sampleRate)
        if (controller.signal.aborted) return
        entry.ready = true
        retryDelay = 1000
        if (connection === entry) connecting.value = false
        else if (prepared === entry) {
          // A visible chat stays ready without accessing the microphone. Sparse synthetic
          // silence keeps the task alive without streaming a full second of audio per second.
          remote.keepAlive()
          entry.silenceTimer = window.setInterval(() => remote.keepAlive(), 1000)
        }
      }),
    }
    void entry.promise.catch(failed)
    return entry
  }

  function prepare() {
    if (!mounted || mode !== 'api' || busy.value || options.disabled() || disposed || document.hidden || !foreground || prepared) return
    prepared = createConnection()
  }

  function schedulePreparation(delay = 0) {
    window.clearTimeout(preparationTimer)
    if (!mounted || disposed || mode !== 'api') return
    preparationTimer = window.setTimeout(prepare, delay)
  }

  function cancel(reprepare = true) {
    generation++
    clearTimer()
    window.clearTimeout(preparationTimer)
    recorder?.dispose(); recorder = undefined
    release(connection); connection = undefined
    release(prepared); prepared = undefined
    if (requestId) void window.sddDesktop?.speech?.cancel(requestId).catch(() => {})
    requestId = ''; connecting.value = false; level.value = 0; state.value = 'idle'; error.value = ''
    if (reprepare) schedulePreparation()
  }

  async function refresh() {
    if (mode !== 'offline') return
    try {
      const next = await window.sddDesktop!.speech!.status()
      if (!disposed) ready.value = next.ready
    } catch { if (!disposed) ready.value = false }
  }

  function failure(reason: unknown) {
    const detail = reason instanceof Error || reason instanceof DOMException ? reason : undefined
    const name = detail?.name || ''
    const message = detail?.message || ''
    error.value = name === 'NotAllowedError' || name === 'SecurityError' ? 'permission_denied'
      : name === 'NotFoundError' ? 'no_microphone'
        : ['unsupported', 'too_short'].includes(message) ? message : 'failed'
  }

  async function start() {
    if (busy.value || options.disabled() || !ready.value) return
    const current = ++generation
    window.clearTimeout(preparationTimer)
    const capture = new SpeechRecorder()
    recorder = capture
    error.value = ''; seconds.value = 0; state.value = 'starting'
    const failed = (reason: Error) => { if (current === generation) { cancel(); failure(reason) } }
    try {
      if (mode === 'api') {
        connection = prepared ?? createConnection()
        prepared = undefined; clearStandby(connection)
        connecting.value = !connection.ready
      }
      await capture.start(mode === 'api' ? pcm => {
        if (current === generation) connection?.stream.sendPcm(pcm)
      } : undefined, () => failed(new Error('Microphone disconnected')), mode === 'api' ? sampleRate => {
        if (current !== generation || !connection) return
        // Some devices ignore the requested 16 kHz. Match their actual format before any PCM arrives.
        if (connection.sampleRate !== sampleRate) {
          release(connection); connection = createConnection(sampleRate); connecting.value = true
        }
        connection.stream.beginCapture()
      } : undefined, value => { if (current === generation) level.value = value })
      if (current !== generation) { capture.dispose(); return }
      state.value = 'recording'
      const startedAt = Date.now()
      timer = window.setInterval(() => {
        seconds.value = Math.min(60, Math.floor((Date.now() - startedAt) / 1000))
        if (seconds.value >= 60) void stop()
      }, 250)
    } catch (reason) { if (current === generation) { cancel(); failure(reason) } }
  }

  async function stop() {
    if (state.value !== 'recording' || !recorder) return
    const current = generation
    const capture = recorder
    const active = connection
    clearTimer(); level.value = 0; state.value = 'transcribing'
    try {
      const wavBase64 = await capture.stop()
      if (current !== generation) return
      let text: string
      if (active) {
        await active.promise
        if (current !== generation) return
        text = await active.stream.finish()
      }
      else {
        requestId = crypto.randomUUID()
        text = (await window.sddDesktop!.speech!.transcribe({ id: requestId, wavBase64 })).text
      }
      if (current !== generation || options.disabled()) return
      if (text.trim()) options.onTranscript(text.trim())
      else error.value = 'no_speech'
    } catch (reason) { if (current === generation) failure(reason) }
    finally {
      if (current === generation) {
        capture.dispose(); release(active)
        requestId = ''; recorder = undefined; connection = undefined
        state.value = 'idle'; connecting.value = false
        schedulePreparation()
      }
    }
  }

  watch(options.disabled, disabled => { if (disabled) cancel(false); else prepare() }, { flush: 'sync' })
  watch(options.contextKey, () => { cancel(false); schedulePreparation() }, { flush: 'sync' })
  function suspendPreparation() {
    window.clearTimeout(preparationTimer)
    release(prepared); prepared = undefined
  }
  function visibilityChanged() {
    if (document.hidden) suspendPreparation()
    else prepare()
  }
  function blurred() { foreground = false; suspendPreparation() }
  function focused() { foreground = true; prepare() }
  function pageHidden() { foreground = false; cancel(false) }
  function contextChanged() { cachedSession = undefined; cancel(false); schedulePreparation() }
  onMounted(() => {
    mounted = true
    void refresh()
    prepare()
    window.addEventListener('pagehide', pageHidden)
    window.addEventListener('pageshow', focused)
    window.addEventListener('blur', blurred)
    window.addEventListener('focus', focused)
    window.addEventListener('sdd-server-changed', contextChanged)
    document.addEventListener('visibilitychange', visibilityChanged)
  })
  onBeforeUnmount(() => {
    disposed = true; cachedSession = undefined; cancel(false)
    window.removeEventListener('pagehide', pageHidden)
    window.removeEventListener('pageshow', focused)
    window.removeEventListener('blur', blurred)
    window.removeEventListener('focus', focused)
    window.removeEventListener('sdd-server-changed', contextChanged)
    document.removeEventListener('visibilitychange', visibilityChanged)
  })
  return { mode, ready, state, error, connecting, seconds, level, busy, visible, start, stop, cancel: () => cancel() }
}
