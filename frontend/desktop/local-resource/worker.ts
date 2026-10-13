import './platform-bun'
import { Runtime, type Config } from './runtime'
let runtime: Runtime
let pending = Promise.resolve()
self.onmessage = (event: MessageEvent) => {
  pending = pending.then(async () => {
  const { id, kind, payload } = event.data
  try {
    if (kind === 'configure') {
      runtime = new Runtime(payload as Config)
      runtime.collaboration.index.onChanged = task_id => self.postMessage({ event: 'collaboration_changed', task_id })
      self.postMessage({ id, result: true }); return
    }
    if (kind === 'shutdown') { runtime?.collaboration.close(); runtime?.db.close(); self.postMessage({ id, result: true }); return }
    const result = kind === 'inspect' ? runtime.inspect(payload)
      : kind === 'collaboration' ? await runtime.collaboration.executeAsync(payload.kind, payload.payload) : runtime.operation(payload)
    self.postMessage({ id, result })
  } catch (error) { self.postMessage({ id, error: error instanceof Error ? error.message : String(error) }) }
  })
}
