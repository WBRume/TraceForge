import './platform-bun'
import { Runtime, type Config } from './runtime'
let runtime: Runtime
self.onmessage = (event: MessageEvent) => {
  const { id, kind, payload } = event.data
  try {
    if (kind === 'configure') { runtime = new Runtime(payload as Config); self.postMessage({ id, result: true }); return }
    if (kind === 'shutdown') { runtime.db.close(); self.postMessage({ id, result: true }); return }
    const result = kind === 'inspect' ? runtime.inspect(payload) : runtime.operation(payload)
    self.postMessage({ id, result })
  } catch (error) { self.postMessage({ id, error: error instanceof Error ? error.message : String(error) }) }
}
